"""Decides what to keep and writes the hook + post caption.

With ANTHROPIC_API_KEY set, Claude reads the word-level transcript, removes bad
takes / false starts / filler, and writes the on-screen hook, the post caption
and topical hashtags. Without a key a heuristic fallback still cuts filler and
obvious restarts so the pipeline keeps working.
"""
import json
import os
import random
import re

import anthropic

from . import writer

MODEL = os.environ.get("REELCUT_MODEL", "claude-opus-5-5")
FILLERS = {"um", "uh", "erm", "uhm", "hmm", "mm", "ah"}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "keep_ranges": {
            "type": "array",
            "description": "Inclusive [first_word_index, last_word_index] ranges to keep, in order.",
            "items": {"type": "array", "items": {"type": "integer"}},
        },
        "hook_title": {"type": "string"},
        "hook_subtitle": {"type": "string"},
        "post_caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "music_id": {"type": "string", "description": "id of the chosen track, or empty string"},
    },
    "required": ["keep_ranges", "hook_title", "hook_subtitle", "post_caption", "hashtags", "music_id"],
    "additionalProperties": False,
}

SYSTEM = """You are the editor for a short-form creator who posts talking-head Reels and TikToks \
(often UGC-style videos promoting a brand or app). You receive the raw word-level transcript of \
their footage. Several clips may have been joined; the creator often repeats a line until they get \
it right.

Your job:
1. keep_ranges: choose which words survive the edit so the final video sounds like one clean, \
confident, fast take.
   - When a line is attempted more than once, keep only the LAST complete, fluent attempt.
   - Drop false starts, stumbles, "wait let me redo that", off-script chatter, counting in, \
filler (um, uh, like-as-filler), and anything said before/after the actual script.
   - Never cut in the middle of a sentence that you keep. Keep the order of the script.
   - Ranges are inclusive word indexes from the transcript.
2. hook_title: the on-screen headline shown for the first 3 seconds, like \
"What NOT to do if you have MCAS 🚨📢⚠️". Under 9 words, curiosity-driven, 1-3 emoji at the end, \
CAPITALISE one key word for emphasis.
3. hook_subtitle: a small line under the headline that adds credibility, like \
"from a person with MCAS". Under 7 words, no emoji. Empty string if nothing fits.
4. post_caption: the text posted with the video. Match the creator's caption examples if any are \
given. Default style: one punchy hook line, 1-3 short lines expanding on it, a call to action \
(comment / follow / save, or the brand CTA if it's a brand video). Natural, not salesy, no hashtags \
in this field.
5. hashtags: 5-8 topical hashtags (with #) relevant to this video's content. Brand hashtags are \
added separately, don't repeat them.
6. music_id: only when a music library is listed, pick the track whose mood fits this video best \
(empty string if none fit). Otherwise empty string.

Always follow the video type and the creator's notes for this video; they override the defaults above."""

VIDEO_TYPES = {
    "promo": "Brand promo / UGC ad: hook on the viewer's problem, the product appears as the creator's "
             "personal discovery, end with the brand's CTA. Caption mentions the brand naturally.",
    "tips": "Educational tips / list: hook promises a number of tips or a mistake to avoid "
            "(\"3 things...\", \"Stop doing...\"). Caption invites people to save it and comment.",
    "story": "Storytime: hook teases the ending (\"I can't believe...\"). Keep the build-up, cut only true "
             "dead weight. Caption is personal and asks for their story.",
    "motivation": "Motivation / hustle: bold, punchy hook, a strong statement or contrarian take. "
                  "Caption is short and confident, asks people to follow for more.",
    "dayinlife": "Day in the life / vlog: casual hook about what's happening today. Caption is relaxed.",
}


def _transcript_lines(words):
    lines = []
    for i, w in enumerate(words):
        lines.append(f"{i}\t{w['start']:.2f}\t{w['word']}")
    return "\n".join(lines)


def plan_with_claude(words, brand, opts):
    client = anthropic.Anthropic()
    brand_block = ""
    if brand:
        brand_block = (
            f"Brand / company: {brand.get('name', '')}\n"
            f"Brand notes: {brand.get('notes', '')}\n"
            f"Brand hashtags (added automatically): {' '.join(brand.get('hashtags', []))}\n"
            f"Creator's caption examples:\n{brand.get('caption_examples', '') or '(none)'}\n\n"
        )
    vt = opts.get("video_type", "")
    if vt:
        brand_block += f"Video type: {VIDEO_TYPES.get(vt, vt)}\n"
    if opts.get("notes"):
        brand_block += f"Creator's notes for this video: {opts['notes']}\n"
    if opts.get("music_library"):
        brand_block += "Music library:\n" + "\n".join(
            f"- id={m['id']} name={m['name']} mood={m.get('mood', '')}" for m in opts["music_library"]) + "\n"
    user = (
        f"{brand_block}\nTranscript (index, start seconds, word):\n{_transcript_lines(words)}"
    )
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude declined to plan this video")
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text)


def _norm(word):
    return re.sub(r"[^a-z0-9']", "", word.lower())


def plan_heuristic(words, segments, brand, opts):
    """Drop filler words and restarted sentences (same opening words as the next one)."""
    keep = [True] * len(words)
    for i, w in enumerate(words):
        if _norm(w["word"]) in FILLERS:
            keep[i] = False
    # A restart = a sentence whose first 4 words are said again at the start of a
    # later sentence soon after; keep the later take.
    toks = [_norm(w["word"]) for w in words]
    n = 4

    def starts_sentence(k):
        return k == 0 or re.search(r"[.!?]$", words[k - 1]["word"]) or words[k]["start"] - words[k - 1]["end"] > 0.6

    i = 0
    while i < len(toks) - n:
        nxt = i + 1
        if starts_sentence(i):
            gram = toks[i:i + n]
            for j in range(i + 1, min(i + 40, len(toks) - n + 1)):
                if toks[j:j + n] == gram and starts_sentence(j):
                    for k in range(i, j):
                        keep[k] = False
                    nxt = j  # the retake starts here; don't re-scan the dropped take
                    break
        i = nxt
    ranges, start = [], None
    for i, k in enumerate(keep + [False]):
        if k and start is None:
            start = i
        elif not k and start is not None:
            ranges.append([start, i - 1])
            start = None
    kept = [words[i] for a, b in ranges for i in range(a, b + 1)]
    text = writer.write(kept, brand, opts.get("video_type", ""))
    library = opts.get("music_library") or []
    mood_words = {"motivation": "motiv hype energ upbeat", "story": "emotion chill calm",
                  "tips": "upbeat chill", "promo": "upbeat happy", "dayinlife": "chill lofi"}
    wanted = mood_words.get(opts.get("video_type", ""), "").split()
    fits = [m for m in library if any(w in m.get("mood", "").lower() for w in wanted)]
    return {
        "keep_ranges": ranges,
        **text,
        "music_id": random.choice(fits or library)["id"] if library else "",
    }


def plan(words, segments, brand, opts=None):
    opts = opts or {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            p = plan_with_claude(words, brand, opts)
            p["planner"] = "claude"
        except Exception as e:  # keep the job alive; note why in the result
            p = plan_heuristic(words, segments, brand, opts)
            p["planner"] = f"free (Claude failed: {e})"
    else:
        p = plan_heuristic(words, segments, brand, opts)
        p["planner"] = "free"
    # whatever the creator typed wins over anything generated
    if opts.get("hook"):
        if p["planner"].startswith("free") and p["post_caption"].startswith(p["hook_title"]):
            p["post_caption"] = opts["hook"] + p["post_caption"][len(p["hook_title"]):]
        p["hook_title"] = opts["hook"]
        p["hook_subtitle"] = opts.get("hook_subtitle", "")
    if opts.get("caption"):
        p["post_caption"] = opts["caption"]
    return p


def merge_hashtags(topical, brand, extra=()):
    seen, out = set(), []
    for tag in list(extra) + list((brand or {}).get("hashtags", [])) + list(topical):
        tag = tag.strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag
        if tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out
