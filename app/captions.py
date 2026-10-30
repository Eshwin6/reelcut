"""On-screen text: word-by-word captions (ASS) and the hook headline (PNG overlay)."""
import os
import re

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FONT_DIR = os.environ.get("REELCUT_FONTS", os.path.join(os.path.dirname(__file__), "..", "fonts"))
EMOJI_FONT = os.environ.get("REELCUT_EMOJI_FONT", "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")

# Caption look from the reference: condensed bold caps, white with a dark edge,
# the word being spoken sits on a pink box. Colours are ASS &HAABBGGRR.
CAPTION_FONT = "Anton"
CAPTION_SIZE = 86
CAPTION_Y = int(H * 0.80)
HIGHLIGHT = "&H006B33E8&"  # #E8336B
MAX_WORDS, MAX_CHARS = 3, 18


def _ts(t):
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(word):
    return re.sub(r"[^\w'&%$+-]", "", word.strip()).upper()


def chunk_words(words):
    """Group words into 1-3 word caption cards, breaking at punctuation and long pauses."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        text = " ".join(_clean(x["word"]) for x in cur)
        nxt = words[i + 1] if i + 1 < len(words) else None
        brk = (
            nxt is None
            or len(cur) >= MAX_WORDS
            or len(text) + 1 + len(_clean(nxt["word"])) > MAX_CHARS
            or re.search(r"[.,!?;:]$", w["word"].strip())
            or nxt["start"] - w["end"] > 0.45
        )
        if brk:
            chunks.append(cur)
            cur = []
    return chunks


def build_ass(words, path):
    """words: [{'word','start','end'}] on the OUTPUT timeline."""
    words = [w for w in words if _clean(w["word"])]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{CAPTION_FONT},{CAPTION_SIZE},&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,0,0,0,0,100,100,1,0,1,4,2,2,60,60,{H - CAPTION_Y},1
Style: Box,{CAPTION_FONT},{CAPTION_SIZE},&HFF000000,&HFF000000,{HIGHLIGHT},&HFF000000,0,0,0,0,100,100,1,0,3,5,0,2,60,60,{H - CAPTION_Y},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    chunks = chunk_words(words)
    for ci, chunk in enumerate(chunks):
        chunk_end = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else chunk[-1]["end"] + 0.3
        chunk_end = min(chunk_end, chunk[-1]["end"] + 0.6)
        tokens = [_clean(w["word"]) for w in chunk]
        for wi, w in enumerate(chunk):
            start = chunk[0]["start"] if wi == 0 else w["start"]
            end = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else chunk_end
            if end <= start:
                continue
            # Box layer: only the active word is visible (as its pink box).
            box = " ".join(
                (t if j == wi else "{\\alpha&HFF&\\3a&HFF&}" + t + "{\\alpha&HFF&\\3a&H00&}")
                for j, t in enumerate(tokens)
            )
            box = "{\\alpha&HFF&\\3a&H00&}" + box
            pop = "{\\fscx108\\fscy108\\t(0,90,\\fscx100\\fscy100)}" if wi == 0 else ""
            events.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Box,,0,0,0,,{pop}{box}")
            events.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{pop}{' '.join(tokens)}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")


_EMOJI_RE = re.compile(
    "([\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]+)"
)


def _draw_runs(img, draw, x, y, runs, font, emoji_font, size):
    for kind, text in runs:
        if kind == "emoji":
            for ch in re.findall(r"[^️‍]", text):
                em = Image.new("RGBA", (136, 128), (0, 0, 0, 0))
                ImageDraw.Draw(em).text((0, 0), ch, font=emoji_font, embedded_color=True)
                em = em.crop(em.getbbox() or (0, 0, 1, 1))
                em = em.resize((int(size * em.width / max(em.height, 1)), size), Image.LANCZOS)
                img.alpha_composite(em, (int(x), int(y + size * 0.1)))
                x += em.width + 4
        else:
            draw.text((x, y), text, font=font, fill="white", stroke_width=3, stroke_fill=(0, 0, 0, 200))
            x += draw.textlength(text, font=font)
    return x


def _measure(draw, runs, font, size):
    w = 0
    for kind, text in runs:
        if kind == "emoji":
            w += len(re.findall(r"[^️‍]", text)) * (size + 4)
        else:
            w += draw.textlength(text, font=font)
    return w


def _split_runs(text):
    out = []
    for part in _EMOJI_RE.split(text):
        if not part:
            continue
        out.append(("emoji" if _EMOJI_RE.fullmatch(part) else "text", part))
    return out


def _wrap(draw, text, font, size, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if cur and _measure(draw, _split_runs(trial), font, size) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def build_hook_png(title, subtitle, path):
    """Headline in the top area like the reference: white, centred, emoji in colour."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    title_size, sub_size = 74, 40
    font = ImageFont.truetype(os.path.join(FONT_DIR, "Inter-Bold.otf"), title_size)
    sub_font = ImageFont.truetype(os.path.join(FONT_DIR, "Inter-Bold.otf"), sub_size)
    try:
        emoji_font = ImageFont.truetype(EMOJI_FONT, 109)
    except OSError:
        emoji_font = None
    if emoji_font is None:
        title = _EMOJI_RE.sub("", title).strip()
    y = int(H * 0.12)
    for line in _wrap(draw, title, font, title_size, W - 140):
        runs = _split_runs(line)
        lw = _measure(draw, runs, font, title_size)
        _draw_runs(img, draw, (W - lw) / 2, y, runs, font, emoji_font, title_size)
        y += int(title_size * 1.2)
    if subtitle:
        sw = draw.textlength(subtitle, font=sub_font)
        draw.text(((W - sw) / 2, y + 2), subtitle, font=sub_font, fill="white",
                  stroke_width=2, stroke_fill=(0, 0, 0, 200))
    img.save(path)
