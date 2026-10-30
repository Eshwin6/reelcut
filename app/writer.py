"""Free (no AI) hook, caption and hashtag writer built from the transcript.

Used when no ANTHROPIC_API_KEY is set. It picks the strongest lines you said and
wraps them in templates for the chosen video type.
"""
import re
from collections import Counter

NUMBERS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
           "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
OPENERS = [
    "hey guys", "hi guys", "okay so", "ok so", "alright so", "so", "okay", "ok", "alright", "um",
    "here are", "here's", "today i'm going to", "today i'm gonna", "i'm going to", "i'm gonna",
    "let me tell you", "let's talk about",
]
WEAK_END = {"the", "a", "an", "to", "and", "of", "if", "i", "my", "for", "in", "on", "with", "is", "but", "or", "that"}
EMPHASIS = {"not", "never", "stop", "don't", "dont", "worst", "best", "only", "nobody", "everyone", "free"}
STOP = set("""a about after again all also am an and any are as at back be because been before being
but by can could did do does doing don't down even every for from get gets go going gonna got had has
have having he her here him his how i i'm if in into is it it's its just know let like make me more most
much my need no not now of off on one only or other our out over really right said say see she so some
something still stop take than that that's the their them then there these they thing things think this
those three through to too two up us very want was way we well were what when where which while who why
will with would yeah you you're your yours actually literally number attention people time times
day days year years lot lots kind sort guys okay always never maybe everything anything nothing
someone everybody somebody first last next start started tell told feel feeling put going doing""".split())

TYPE_STYLE = {
    "promo": {"emoji": "😳👇", "cta": "Link in bio 🔗", "tags": ["#tiktokmademebuyit", "#musthave"]},
    "tips": {"emoji": "🚨⚠️", "cta": "Save this so you don't forget 📌\nWhich one surprised you? 👇",
             "tags": ["#tips", "#lifehacks", "#learnontiktok"]},
    "story": {"emoji": "😭", "cta": "Has this ever happened to you? 👇", "tags": ["#storytime"]},
    "motivation": {"emoji": "🔥💯", "cta": "Follow for more 🔥", "tags": ["#motivation", "#mindset", "#hustle"]},
    "dayinlife": {"emoji": "☀️", "cta": "Follow along 🫶", "tags": ["#dayinmylife", "#vlog"]},
    "": {"emoji": "👀", "cta": "Follow for more 👀", "tags": []},
}


def _sentences(words):
    out, cur = [], []
    for w in words:
        cur.append(w["word"])
        if re.search(r"[.!?]$", w["word"]):
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return [s.strip() for s in out if s.strip()]


def _strip_openers(s):
    low = s.lower()
    changed = True
    while changed:
        changed = False
        for o in OPENERS:
            if low.startswith(o + " ") or low.startswith(o + ","):
                s = s[len(o):].lstrip(" ,")
                low = s.lower()
                changed = True
    return s


def _hook_from(sentence):
    s = _strip_openers(re.sub(r"[.!?]+$", "", sentence))
    toks = [NUMBERS.get(t.lower(), t) for t in s.split()]
    if len(toks) > 9:
        toks = toks[:9]
        while len(toks) > 4 and toks[-1].lower().strip(",") in WEAK_END:
            toks.pop()
    toks = [t.rstrip(",") for t in toks]
    for i, t in enumerate(toks):  # one emphasised word, like "What NOT to do"
        if t.lower() in EMPHASIS:
            toks[i] = t.upper()
            break
    text = " ".join(toks)
    return text[:1].upper() + text[1:]


def _tidy(s):
    s = re.sub(r"^(because|and|but|so|or|like|then)\b[ ,]*", "", s.strip(), flags=re.I)
    return s[:1].upper() + s[1:]


def _value_line(sentences, skip):
    best, score = "", -1
    for s in sentences[1:]:
        n = len(s.split())
        if s == skip or n < 5 or n > 22:
            continue
        sc = (3 if re.search(r"\byou(r)?\b", s, re.I) else 0) + (2 if re.search(r"\d|one|two|three", s, re.I) else 0) - abs(n - 12) / 6
        if sc > score:
            best, score = s, sc
    return _tidy(best) if best else ""


def _keywords(words, limit=4):
    counts, proper = Counter(), Counter()
    for i, w in enumerate(words):
        t = re.sub(r"[^A-Za-z0-9']", "", w["word"])
        low = t.lower()
        if len(low) < 4 or low in STOP or low.isdigit():
            continue
        counts[low] += 1
        prev = words[i - 1]["word"] if i else "."
        if t[:1].isupper() and not re.search(r"[.!?]$", prev):  # names / brands mid-sentence
            proper[low] += 2
    good = [k for k in counts if not k.endswith("ly") and (counts[k] >= 2 or proper[k])]
    ranked = sorted(good, key=lambda k: -(counts[k] + proper[k]))
    return ["#" + k.replace("'", "") for k in ranked[:limit]]


def write(words, brand, video_type=""):
    style = TYPE_STYLE.get(video_type, TYPE_STYLE[""])
    sents = _sentences(words)
    first = sents[0] if sents else ""
    hook = _hook_from(first)
    value = _value_line(sents, first)
    cta = style["cta"]
    if video_type == "promo" and brand and brand.get("name"):
        m = re.search(r"cta:\s*(.+)", brand.get("notes", ""), re.I)
        cta = (m.group(1).strip() if m else f"Try {brand['name']}, link in bio") + " 🔗"
    caption = "\n\n".join(x for x in [hook + " " + style["emoji"], value, cta] if x)
    return {
        "hook_title": f"{hook} {style['emoji']}".strip(),
        "hook_subtitle": "",
        "post_caption": caption,
        "hashtags": _keywords(words) + style["tags"] + ["#fyp", "#foryou"],
    }
