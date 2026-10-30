"""A new note made tidy. Rules expand the shorthand, the 2B lays it out as Markdown with its tasks as "- [ ] " lines,
and each task gets the moment it's due. A shared link becomes a note of its page instead, without the 2B."""
import html
import json
import re
import textwrap
import urllib.parse
import urllib.request
from pathlib import Path

import filing
import model
import tasks

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
    "properties": {"title": {"type": "string"}, "body": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 3}},
    "required": ["title", "body", "tags"],
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


def layout(text):
    """The 2B's version: {title, body, tags}."""
    messages = [{"role": "system", "content": PROMPT}]
    for note, answer in EXAMPLES:
        messages += [{"role": "user", "content": note}, {"role": "assistant", "content": json.dumps(answer)}]
    return model.ask(messages + [{"role": "user", "content": text}], SCHEMA)


def faithful(src, title, body):
    """Names and numbers may move into the title; the body alone must stay about as long as the original."""
    letters = lambda s: len(re.sub(r"[^a-z]", "", s.lower()))
    kept = all(w in f"{title}\n{body}" for w in re.findall(r"\d+", src) + filing.NAME.findall(src))
    return kept and 0.6 < letters(body) / max(letters(src), 1) < 1.5


def link(url, title=""):
    """A shared web page becomes a note with its title, a link and its own description. No model touches the URL.
    A story saved under read keeps the title its feed gave it: Reddit and OpenAI won't give their pages to a script."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ember)"}), timeout=15) as r:
            page = r.read(3_000_000).decode(r.headers.get_content_charset() or "utf-8", "replace")  # YouTube names its videos 0.8 MB in
    except Exception:
        page = ""
    find = lambda pattern: " ".join(html.unescape(m[1]).split()) if (m := re.search(pattern, page, re.I | re.S)) else ""
    meta = lambda name: find(rf'<meta[^>]+(?:name|property)="(?:og:)?{name}"[^>]+content="([^"]*)"')
    parts = urllib.parse.urlsplit(url)
    words = " ".join(re.findall(r"[A-Za-z0-9]+", parts.path))  # some sites refuse to be read: name the note after the address
    title = (title or meta("title") or find(r"<title[^>]*>(.*?)</title>") or f"{parts.netloc.removeprefix('www.')}: {words}".rstrip(": "))[:100]
    body = f"[{re.sub(r'[][]', '', title)}]({url})\n\n{meta('description')}".strip()
    return {"title": title, "body": body, "tags": ["link"], "due": {}, "link": url}


def tidy(raw, now):
    """A new note written at `now`: {title, body, tags, due}. If the 2B's version loses a name or a number, or the 2B
    fails, the note is kept as it was written, tagged needs-review."""
    shared = re.fullmatch(r"https?://\S+|\[(.+)\]\((https?://\S+)\)", raw.strip())  # a link, or a story saved under read
    if shared:
        return link(shared[2] or shared[0], shared[1] or "")
    text = correct(raw)
    head, _, rest = text.partition("\n")
    # "NovaX:" on its own line names the note, and so does a short line with a blank one after it
    heading = (head.endswith(":") or rest.startswith("\n")) and len(head.split()) <= 6 and rest.strip()
    title, rest = (head.rstrip(":").strip(), rest.strip()) if heading else (" ".join(head.split()[:6]).rstrip(".,;:"), text)
    note = {"title": title, "body": rest, "tags": ["needs-review"]}
    shape = lambda s: [len(line) - len(line.lstrip()) if line.strip() else -1 for line in s.strip().split("\n")]
    try:
        out = layout(text)  # with the heading, so "Tomorrow:" makes the lines under it tasks
        body = textwrap.dedent(re.sub(rf"^(- )?{re.escape(title)}:?\n+", "", out["body"])) if heading else out["body"]  # the heading is the title
        body = re.sub(r"(?m)^\s+(- \[[ x]\] )", r"\1", body)  # a task is never nested under another task
        if re.search(r"(?m)^\s*- ", rest) and shape(body) != shape(rest):
            body = rest  # the 2B nests a list the writer laid out themselves, even when told not to; they keep theirs
        title = title if heading else out["title"]
        if faithful(rest, title, body):
            note = {"title": title, "body": body, "tags": [re.sub(r"\s+", "-", t.strip().lower()) for t in out["tags"]]}
    except Exception as e:
        print(f"layout failed: {e!r}", flush=True)
    dating = [title] if heading else []  # a list is what to do on the day its heading names, as in "Tomorrow:"
    last = note["body"].strip().split("\n")[-1]
    if re.search(r"(?m)^- ", note["body"]) and re.match(r"\w", last) and tasks.only_when(last):
        dating.append(last)  # or on the day a line after it names, if it says only that: "reminders for today at 2pm"
    under = next((line for line in dating if tasks.when(line, now)), "")
    if under:  # every other line is a task then, unless it names its own day
        note["body"] = re.sub(r"(?m)^(?:- (?!\[[ x]\] ))?(\w.*)$", lambda m: m[0] if m[0] == under else f"- [ ] {m[1]}", note["body"])
    note["due"] = {tasks.key(t): at for _, t, _ in tasks.found(note["body"]) if (at := tasks.when(t, now, under))}
    return note
