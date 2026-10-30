"""Raw clips in -> finished 9:16 reel out.

1. join + normalise every clip to 1080x1920 / 30fps
2. transcribe with word timings (faster-whisper)
3. plan the edit (bad takes, filler) and the hook/caption -> planner.py
4. cut to kept speech, strip dead air, punch-in zoom on alternating cuts
5. burn word-by-word captions + hook headline, loudness-normalise
6. optionally lay a music bed under the voice that ducks while you talk
"""
import json
import os
import re
import subprocess

import numpy as np

from . import captions, planner

W, H, FPS = captions.W, captions.H, 30
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
PAD_IN, PAD_OUT = 0.06, 0.12   # breathing room around kept words
MAX_GAP = 0.30                  # pauses longer than this are cut
ZOOM = 1.10                     # punch-in on every other cut
HOOK_SECONDS = 3.2
MUSIC_VOLUME = float(os.environ.get("MUSIC_VOLUME", "0.30"))  # bed level before ducking

_model = None


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr[-1500:]}")
    return p


def _model_get():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def normalise(clips, out):
    """Concatenate clips in order, cover-crop to 9:16, constant 30fps, stereo 48k."""
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for c in clips:
        cmd += ["-i", c]
    parts = []
    for i, c in enumerate(clips):
        has_audio = bool(_run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                               "stream=index", "-of", "csv=p=0", c]).stdout.strip())
        parts.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"setsar=1,fps={FPS},format=yuv420p[v{i}];"
        )
        if has_audio:
            parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}];")
        else:
            parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{_duration(c)}[a{i}];")
    joins = "".join(f"[v{i}][a{i}]" for i in range(len(clips)))
    fc = "".join(parts) + f"{joins}concat=n={len(clips)}:v=1:a=1[v][a]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset",
            "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", out]
    _run(cmd)


def _duration(path):
    return float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                       "csv=p=0", path]).stdout.strip())


def transcribe(path):
    raw = _run_bytes(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"])
    audio = np.frombuffer(raw, np.float32)
    segs, _ = _model_get().transcribe(audio, word_timestamps=True, language=os.environ.get("WHISPER_LANG") or None)
    words, seg_ranges = [], []
    for s in segs:
        first = len(words)
        for w in s.words or []:
            words.append({"word": w.word.strip(), "start": float(w.start), "end": float(w.end)})
        if len(words) > first:
            seg_ranges.append((first, len(words) - 1))
    return words, seg_ranges


def _run_bytes(cmd):
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode()[-1500:])
    return p.stdout


def silences(path, noise="-35dB", min_len=0.35):
    err = subprocess.run(["ffmpeg", "-i", path, "-af", f"silencedetect=noise={noise}:d={min_len}",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return list(zip(starts, ends))


def build_segments(words, keep_ranges, quiet, total):
    """Kept words -> source time ranges, split at long pauses, minus detected silence."""
    kept = sorted({i for a, b in keep_ranges for i in range(max(a, 0), min(b, len(words) - 1) + 1)})
    segs = []
    for i in kept:
        w = words[i]
        s, e = max(w["start"] - PAD_IN, 0), min(w["end"] + PAD_OUT, total)
        if segs and i - 1 == segs[-1][2] and s - segs[-1][1] <= MAX_GAP:
            segs[-1][1] = max(segs[-1][1], e)
            segs[-1][2] = i
        elif segs and s <= segs[-1][1]:
            segs[-1][1] = max(segs[-1][1], e)
            segs[-1][2] = i
        else:
            segs.append([s, e, i])
    out = []
    for s, e, _ in segs:
        pieces = [(s, e)]
        for qs, qe in quiet:
            # trim silence that whisper stretched a word over (keep a little air)
            qs2, qe2 = qs + 0.08, qe - 0.08
            if qe2 - qs2 < MAX_GAP:
                continue
            nxt = []
            for ps, pe in pieces:
                if qe2 <= ps or qs2 >= pe:
                    nxt.append((ps, pe))
                    continue
                if qs2 > ps:
                    nxt.append((ps, qs2))
                if qe2 < pe:
                    nxt.append((qe2, pe))
            pieces = nxt
        out += [(round(a, 3), round(b, 3)) for a, b in pieces if b - a >= 0.2]
    return out


def remap_words(words, keep_ranges, segments):
    kept = {i for a, b in keep_ranges for i in range(a, b + 1)}
    out, offset, seg_starts = [], 0.0, []
    for s, e in segments:
        seg_starts.append(offset)
        offset += e - s
    for i, w in enumerate(words):
        if i not in kept:
            continue
        mid = (w["start"] + w["end"]) / 2
        for (s, e), o in zip(segments, seg_starts):
            if s <= mid <= e:
                out.append({"word": w["word"],
                            "start": o + max(w["start"], s) - s,
                            "end": o + min(w["end"], e) - s})
                break
    return out


def render(master, segments, ass_path, hook_png, out, music=None):
    fc = []
    for i, (s, e) in enumerate(segments):
        zoom = ""
        if i % 2 == 1:
            zoom = (f",crop=iw/{ZOOM}:ih/{ZOOM}:(iw-iw/{ZOOM})/2:(ih-ih/{ZOOM})*0.35,"
                    f"scale={W}:{H}")
        zoom += ",setsar=1"
        fade = min(0.015, (e - s) / 4)
        fc.append(f"[0:v]trim={s}:{e},setpts=PTS-STARTPTS{zoom}[v{i}];")
        fc.append(f"[0:a]atrim={s}:{e},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d={fade},afade=t=out:st={e - s - fade}:d={fade}[a{i}];")
    n = len(segments)
    fc.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac];")
    ass = ass_path.replace("\\", "/").replace(":", "\\:")
    fonts = os.path.abspath(captions.FONT_DIR).replace(":", "\\:")
    fc.append(f"[vc]ass='{ass}':fontsdir='{fonts}'[vs];")
    fc.append(f"[1:v]format=rgba,fade=t=out:st={HOOK_SECONDS - 0.25}:d=0.25:alpha=1[hk];")
    fc.append(f"[vs][hk]overlay=0:0:enable='lt(t,{HOOK_SECONDS})'[v];")
    if music:
        dur = sum(e - s for s, e in segments)
        fc.append("[ac]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,asplit=2[voice][sc];")
        fc.append(f"[2:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{dur},"
                  f"volume={MUSIC_VOLUME},afade=t=in:d=0.8,afade=t=out:st={max(dur - 1.5, 0)}:d=1.5[m];")
        # music dips under speech and swells back in pauses
        fc.append("[m][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[md];")
        fc.append("[voice][md]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
        extra = ["-stream_loop", "-1", "-i", music]
    else:
        fc.append("[ac]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
        extra = []
    _run(["ffmpeg", "-y", "-v", "error", "-i", master, "-loop", "1", "-t", str(HOOK_SECONDS + 0.5),
          "-i", hook_png, *extra, "-filter_complex", "".join(fc), "-map", "[v]", "-map", "[a]",
          "-c:v", "libx264", "-preset", os.environ.get("X264_PRESET", "veryfast"), "-crf", "20", "-pix_fmt", "yuv420p",
          "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out])


def process(clips, workdir, brand, opts=None, progress=lambda stage: None):
    """opts: video_type, notes, hashtags_on, extra_hashtags, music ("none"|"auto"|path),
    music_library [{id,name,mood,path}]"""
    opts = opts or {}
    os.makedirs(workdir, exist_ok=True)
    master = os.path.join(workdir, "master.mp4")
    progress("Joining clips")
    normalise(clips, master)
    total = _duration(master)

    progress("Transcribing")
    words, seg_ranges = transcribe(master)
    if not words:
        raise RuntimeError("No speech found in the footage")

    progress("Cutting bad takes")
    want_auto_music = opts.get("music") == "auto" and opts.get("music_library")
    plan = planner.plan(words, seg_ranges, brand, {
        "video_type": opts.get("video_type", ""), "notes": opts.get("notes", ""),
        "music_library": opts.get("music_library") if want_auto_music else [],
        "hook": opts.get("hook", ""), "caption": opts.get("caption", ""),
    })
    plan["keep_ranges"] = [r for r in plan["keep_ranges"] if len(r) == 2 and r[0] <= r[1]]
    segments = build_segments(words, plan["keep_ranges"], silences(master), total)
    if not segments:
        raise RuntimeError("Nothing left after cutting")
    out_words = remap_words(words, plan["keep_ranges"], segments)

    progress("Adding captions")
    ass_path = os.path.join(workdir, "captions.ass")
    hook_png = os.path.join(workdir, "hook.png")
    captions.build_ass(out_words, ass_path)
    captions.build_hook_png(plan["hook_title"], plan["hook_subtitle"], hook_png)

    progress("Rendering")
    final = os.path.join(workdir, "final.mp4")
    music, music_name = None, ""
    if want_auto_music:
        pick = next((m for m in opts["music_library"] if m["id"] == plan.get("music_id")), None)
        if pick:
            music, music_name = pick["path"], pick["name"]
    elif opts.get("music") not in (None, "", "none", "auto"):
        music = opts["music"]
        music_name = opts.get("music_name", "")
    render(master, segments, ass_path, hook_png, final, music)
    _run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", final, "-frames:v", "1", "-vf",
          "scale=360:-1", os.path.join(workdir, "thumb.jpg")])

    hashtags = []
    if opts.get("hashtags_on", True):
        hashtags = planner.merge_hashtags(plan["hashtags"], brand, opts.get("extra_hashtags", []))
    caption = plan["post_caption"].strip()
    if hashtags:
        caption += "\n\n" + " ".join(hashtags)
    result = {
        "video": "final.mp4",
        "thumb": "thumb.jpg",
        "caption": caption,
        "music": music_name,
        "hook_title": plan["hook_title"],
        "hook_subtitle": plan["hook_subtitle"],
        "hashtags": hashtags,
        "planner": plan.get("planner"),
        "raw_seconds": round(total, 1),
        "final_seconds": round(sum(e - s for s, e in segments), 1),
        "cuts": len(segments),
    }
    with open(os.path.join(workdir, "edit.json"), "w") as f:
        json.dump({"words": words, "plan": plan, "segments": segments}, f)
    os.remove(master)
    return result
