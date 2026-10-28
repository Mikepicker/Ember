"""Turns a raw note into a tidy one: rules fix the typing, a small model lays it out."""
import base64
import html
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

LLM = os.environ.get("EMBER_LLM", "http://127.0.0.1:8080")
VISION = os.environ.get("EMBER_VISION", LLM)  # a smaller model reads photos better and faster than the text model
WHISPER = os.environ.get("EMBER_WHISPER", "http://127.0.0.1:8081")
AUDIO = {".webm", ".m4a", ".mp4", ".ogg", ".wav", ".mp3", ".aac"}
LONGEST = 10 * 60  # seconds; longer recordings are kept but not transcribed
SHORTHAND = dict(
    line.split(maxsplit=1)
    for line in Path(__file__).with_name("shorthand.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
)

PROMPT = """You tidy quick personal notes into clean Markdown. Rules:
1. Keep every detail: names, days, times, dates, amounts, places. Never drop anything, never add anything.
2. Fix spelling, grammar, punctuation, and capitalise names.
3. Each action the writer has to do becomes a "- [ ] " line, with its day or time kept in it.
4. Details that belong to an action go on indented "  - " lines under it. Other separate points are "- " lines. Keep lists the writer already made as lists.
5. A single thought stays a plain sentence. No headings.
Give a title of 2 to 6 words, and up to 3 lowercase one-word tags."""

EXAMPLES = [
    (
        "Pick up kids at 4. Buy milk eggs and bread. Dentist moved to Thursday",
        {"title": "Errands and dentist", "body": "- [ ] Pick up the kids at 4\n- [ ] Buy milk, eggs and bread\n- Dentist moved to Thursday", "tags": ["errands", "dentist"]},
    ),
    (
        "Call the bank Monday at 10 about the mortgage. Rate is 3.1 now. sara said ask for the fixed option",
        {"title": "Mortgage call", "body": "- [ ] Call the bank on Monday at 10 about the mortgage\n  - The rate is 3.1 now\n  - Ask for the fixed option, as Sara said", "tags": ["mortgage", "bank"]},
    ),
    (
        "A bench under the cherry tree would be nice for summer evenings",
        {"title": "Bench under the cherry tree", "body": "A bench under the cherry tree would be nice for summer evenings.", "tags": ["garden", "idea"]},
    ),
]

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["title", "body", "tags"],
}


AREAS = ["work", "home", "money", "health", "family", "friends", "travel", "food", "shopping", "learning", "hobbies", "ideas"]

FOLDER_PROMPT = """You file personal notes. Pick the area of life the note belongs to,
and name its topic with one lowercase plural noun, the label you would write on a drawer."""

AREA_HINTS = """Areas:
- work: the job and the company: clients, colleagues, products, projects, orders, deliveries, invoices
- home: the house and what is in it: repairs, appliances, cleaning, garden
- money: personal finances: bills, bank, mortgage, savings, insurance, taxes
- health: body and mind: doctors, appointments, exercise, sleep
- family: parents, children, partner, relatives
- friends: friends and social life
- travel: trips and getting around: flights, trains, hotels, documents
- food: recipes, cooking, restaurants
- shopping: things to buy and gifts
- learning: books, courses, talks, studying
- hobbies: music, games, crafts, sport for fun
- ideas: ideas and plans with no date"""

FOLDER_SCHEMA = {
    "type": "object",
    "properties": {"area": {"enum": AREAS}, "topic": {"type": "string", "pattern": "^[a-z]{3,15}$"}},
    "required": ["area", "topic"],
}


def expand(match):
    if match[0].lower() in SHORTHAND:  # entries like "w." keep their dot
        return SHORTHAND[match[0].lower()]
    word, tail = re.match(r"(.*?)([.,;:!?]*)$", match[0]).groups()
    return SHORTHAND.get(word.lower(), word) + tail


def correct(text):
    text = re.sub(r"\S+", expand, text)
    # "remind me to call Henrik" is the task "call Henrik"; left in, small models sometimes turn it around
    text = re.sub(r"(?i)(^|[.!?]\s+|\n\s*)(remind me to|don't forget to)\s+", r"\1", text.strip())
    return re.sub(r"(^|[.!?]\s+|\n\s*)([a-z])", lambda m: m[1] + m[2].upper(), text)


def ask(messages, schema=None, server=None):
    request = {"messages": messages, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}
    if schema:
        request["response_format"] = {"type": "json_schema", "json_schema": {"schema": schema}}
    req = urllib.request.Request(f"{server or LLM}/v1/chat/completions", json.dumps(request).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        answer = json.load(r)["choices"][0]["message"]["content"]
    return json.loads(answer) if schema else answer.strip()


def ffmpeg(path, *args):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), *args, "-"], capture_output=True, check=True).stdout


def remux(path):
    """Rewrites a recording with its length and seek points, which browser recorders leave out."""
    tmp = path.with_name(f"remux-{path.name}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-c", "copy", str(tmp)], check=True)
    tmp.replace(path)


def transcribe(path):
    wav = ffmpeg(path, "-ar", "16000", "-ac", "1", "-f", "wav")  # 32,000 bytes per second
    if len(wav) / 32000 > LONGEST:
        return f"(Recording of {len(wav) // 32000 // 60} minutes, not transcribed.)"
    form = b'--ember\r\nContent-Disposition: form-data; name="file"; filename="memo.wav"\r\n\r\n' + wav + b"\r\n--ember--\r\n"
    req = urllib.request.Request(f"{WHISPER}/inference", form, {"Content-Type": "multipart/form-data; boundary=ember"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return " ".join(re.sub(r"\[[A-Z_ ]+\]", "", json.load(r)["text"]).split())  # drops markers like [BLANK_AUDIO]


def read(path):
    # 896 px wide is about 1,000 image tokens: as accurate as 1280 px on receipts, whiteboards and printed pages, 2-4x faster
    jpeg = ffmpeg(path, "-vf", "scale='min(896,iw)':-2", "-f", "image2", "-c:v", "mjpeg")
    image = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}}
    ask_for = "Write out all the text in this photo exactly, line by line. If there is no text, describe the photo in one short sentence."
    return ask([{"role": "user", "content": [image, {"type": "text", "text": ask_for}]}], server=VISION)


def layout(text):
    messages = [{"role": "system", "content": PROMPT}]
    for note, tidy_note in EXAMPLES:
        messages += [{"role": "user", "content": note}, {"role": "assistant", "content": json.dumps(tidy_note)}]
    return ask(messages + [{"role": "user", "content": text}], SCHEMA)


FOLDER_EXAMPLES = [
    ("Gym plan\nLegs on Monday, run on Wednesday", {"area": "health", "topic": "fitness"}),
    ("Electricity bill\nDue on the 5th, 82 EUR", {"area": "money", "topic": "bills"}),
    ("Risotto for Saturday\nArborio rice, saffron, parmesan", {"area": "food", "topic": "recipes"}),
]


def folder(title, body, hints=True):
    """Picks "area/topic" for a note: the area from a fixed set, the topic named freely."""
    messages = [{"role": "system", "content": FOLDER_PROMPT + ("\n" + AREA_HINTS if hints else "")}]
    for note, answer in FOLDER_EXAMPLES:
        messages += [{"role": "user", "content": note}, {"role": "assistant", "content": json.dumps(answer)}]
    out = ask(messages + [{"role": "user", "content": f"{title}\n{body}"}], FOLDER_SCHEMA)
    return f"{out['area']}/{out['topic']}"


NAME = re.compile(r"\b[A-Za-z]*[A-Z][A-Za-z]*[A-Z][A-Za-z]*\b|(?<=[a-z,] )[A-Z][a-z]+\b")  # NovaX, DeltaWorks; Henrik mid-sentence
NOT_NAMES = {*"monday tuesday wednesday thursday friday saturday sunday january february march april may june july".split(),
             *"august september october november december eur usd am pm ok asap todo".split()}


def names(text):
    """People, places and projects a note mentions, lowercased."""
    return {w.lower() for w in NAME.findall(text)} - NOT_NAMES


def faithful(src, title, body):
    """Names and numbers may move into the title; the body alone must stay about as long as the original."""
    letters = lambda s: len(re.sub(r"[^a-z]", "", s.lower()))
    kept = all(w in f"{title}\n{body}" for w in re.findall(r"\d+", src) + NAME.findall(src))
    return kept and 0.6 < letters(body) / max(letters(src), 1) < 1.5


def link(url):
    """A shared web page becomes a note with its title, a link and its own description. No model touches the URL."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ember)"}), timeout=15) as r:
            page = r.read(3_000_000).decode(r.headers.get_content_charset() or "utf-8", "replace")  # YouTube names its videos 0.8 MB in
    except Exception:
        page = ""
    find = lambda pattern: " ".join(html.unescape(m[1]).split()) if (m := re.search(pattern, page, re.I | re.S)) else ""
    meta = lambda name: find(rf'<meta[^>]+(?:name|property)="(?:og:)?{name}"[^>]+content="([^"]*)"')
    parts = urllib.parse.urlsplit(url)
    words = " ".join(re.findall(r"[A-Za-z0-9]+", parts.path))  # some sites refuse to be read: name the note after the address
    title = (meta("title") or find(r"<title[^>]*>(.*?)</title>") or f"{parts.netloc.removeprefix('www.')}: {words}".rstrip(": "))[:100]
    about = meta("description")
    return {"title": title, "body": f"[{re.sub(r'[][]', '', title)}]({url})\n\n{about}".strip(), "tags": ["link"]}


def tidy(raw):
    if re.fullmatch(r"https?://\S+", raw.strip()):
        return link(raw.strip())
    text = correct(raw)
    head, _, rest = text.partition("\n")
    heading = head.endswith(":") and len(head.split()) <= 6 and rest.strip()  # "NovaX:" on its own line names the note
    text = rest.strip() if heading else text
    title = head[:-1].strip() if heading else " ".join(head.split()[:6]).rstrip(".,;:")
    try:
        out = layout(text)
        out["title"] = title if heading else out["title"]
        out["body"] = re.sub(r"(?m)^\s+(- \[[ x]\] )", r"\1", out["body"])  # a task is never nested under another task
        if faithful(text, out["title"], out["body"]):
            return {**out, "tags": [re.sub(r"\s+", "-", t.strip().lower()) for t in out["tags"]]}
    except Exception as e:
        print(f"layout failed: {e!r}", flush=True)
    return {"title": title, "body": text, "tags": ["needs-review"]}
