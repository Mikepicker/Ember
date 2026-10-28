"""Ember server: serves the app, keeps notes as Markdown files, tidies new ones in the background."""
import io
import json
import os
import queue
import re
import secrets
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import ask
import pipeline
import reminders

ROOT = Path(__file__).resolve().parent.parent
NOTES = Path(os.environ.get("EMBER_NOTES", ROOT / "data" / "notes"))
HOST = os.environ.get("EMBER_HOST", "127.0.0.1")
PORT = int(os.environ.get("EMBER_PORT", "8787"))
SUBFOLDER_AT = 3  # notes sharing a topic before the topic gets its own subfolder

lock = threading.Lock()
jobs = queue.Queue()
paths = {}  # note id -> file


def parse(text):
    meta, body = {}, text
    if text.startswith("---\n"):
        head, _, body = text[4:].partition("\n---\n")
        meta = dict(line.split(": ", 1) for line in head.splitlines() if ": " in line)
    return meta, body.strip()


def dump(meta, body):
    head = "".join(f"{k}: {v}\n" for k, v in meta.items() if v)
    return f"---\n{head}---\n\n{body.strip()}\n"


def read(path):
    meta, body = parse(path.read_text())
    note = {**meta, "body": body, "path": str(path.relative_to(NOTES)), "mtime": path.stat().st_mtime}
    if meta.get("reminders") and not hidden(path):  # what went to Reminders and Calendar, for the app to show
        tasks = reminders.dated(body, meta["created"], meta.get("anchors", ""))
        note["due"] = [[i, f"{at:%Y-%m-%dT%H:%M}", reminders.component(text), timed] for i, text, _, at, timed in tasks]
    return note


def write(meta, body, path):
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(dump(meta, body))
        tmp.replace(path)
        old = paths.get(meta["id"])
        if old and old != path:
            old.unlink(missing_ok=True)
        paths[meta["id"]] = path


def hidden(path):
    """Notes under _raw, _trash and other _ folders aren't shown in the app."""
    return path.relative_to(NOTES).parts[0].startswith("_")


def filename(folder, created, title, nid):
    name = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:60] or "note"
    path = NOTES / folder / f"{created[:10]} {name}.md"
    return path if not path.exists() or paths.get(nid) == path else path.with_stem(f"{path.stem} {nid}")


def attachment(url):
    return f"[voice]({url})" if Path(url).suffix.lower() in pipeline.AUDIO else f"![photo]({url})"


def capture(nid, created, text, files):
    """A new note waits in unsorted/ until it has been tidied and filed. A note sent twice is kept once."""
    if nid not in paths:
        write({"id": nid, "created": created, "status": "raw", "files": " ".join(files)}, text, NOTES / "unsorted" / f"{created[:10]} {nid}.md")
        jobs.put((tidy, nid))


def tidy(nid):
    note = read(paths[nid])
    urls = note.get("files", "").split()
    files = [NOTES / "_files" / url.removeprefix("/files/") for url in urls]
    recordings = [f for f in files if f.suffix.lower() in pipeline.AUDIO]
    for f in recordings:
        pipeline.remux(f)
    heard = "\n\n".join(pipeline.transcribe(f) for f in recordings)
    seen = "\n\n".join(pipeline.read(f) for f in files if f.suffix.lower() not in pipeline.AUDIO)  # kept exactly as read
    created, raw = note["created"], "\n\n".join(t for t in (note["body"], heard) if t)
    original = f"_raw/{created[:7].replace('-', '/')}/{nid}.md"
    write({"id": f"{nid}.raw", "created": created, "title": "original"}, f"{raw}\n\n{seen}", NOTES / original)
    out = pipeline.tidy(raw) if raw else {**pipeline.layout(seen[:600]), "body": ""}  # a photo alone is named from what it shows
    body = "\n\n".join(t for t in (out["body"], seen, "\n".join(attachment(url) for url in urls)) if t)
    meta = {"id": nid, "created": created, "title": out["title"], "tags": ", ".join(out["tags"]), "original": original}
    write(meta, body, filename("unsorted", created, out["title"], nid))
    place(nid)
    remind(nid)


def known_area(nid, text):
    """The area where the people and projects a note mentions already live, if it's a single one.
    A word counts as a name once any note wrote it as one, so "Henrik's site" and "kova" count too."""
    words = lambda t: set(re.findall(r"[a-z]+", t.lower()))
    others = [(p, p.read_text()) for other, p in list(paths.items())
              if other != nid and p.exists() and not hidden(p) and p.parent != NOTES / "unsorted"]
    known = set().union(*(pipeline.names(t) for _, t in others))
    wanted = pipeline.names(text) | (words(text) & known)
    areas = {p.relative_to(NOTES).parts[0] for p, t in others if wanted & words(t)}
    return areas.pop() if len(areas) == 1 else None


def place(nid):
    """Files a note under its area, and under area/topic once enough notes share that topic."""
    path = paths[nid]
    meta, body = parse(path.read_text())
    if not re.sub(r"!?\[[^\]]*\]\(/files/[^)]*\)", "", body).strip():
        return  # only attachments and nothing to go on yet, e.g. an untranscribed recording
    if not meta.get("folder"):
        area, topic = pipeline.folder(meta.get("title", ""), body).split("/")
        raw = (NOTES / meta["original"]).read_text() if meta.get("original") else ""
        known = known_area(nid, f"{meta.get('title', '')}\n{body}\n{raw}")
        if known and known != area:  # a note about Henrik goes where Henrik's notes are
            area, topic = known, known if topic == area else topic
        meta["folder"] = f"{area}/{topic}"
    area, topic = meta["folder"].split("/")
    peers = [p for p in (NOTES / area).glob("*.md") if p != path and parse(p.read_text())[0].get("folder") == meta["folder"]]
    dest = NOTES / area
    if topic != area and ((dest / topic).is_dir() or len(peers) + 1 >= SUBFOLDER_AT):
        dest = dest / topic
        for p in peers:
            write(*parse(p.read_text()), dest / p.name)
    write(meta, body, dest / path.name)


def remind(nid, always=True):
    """Two-way sync of the note's dated tasks with Reminders and Calendar.
    `synced` holds each task's ticked state at the last sync, so whichever side changed since then wins."""
    path = paths[nid]
    meta, body = parse(path.read_text())
    lines, was, there = body.split("\n"), meta.get("synced", ""), reminders.ticked(meta)
    for n, (i, _, done, *_) in enumerate(reminders.dated(body, meta["created"], meta.get("anchors", ""))):
        if n in there and n < len(was) and there[n] != (was[n] == "1") and there[n] != done:  # changed on the phone
            lines[i] = lines[i].replace(*(("- [ ]", "- [x]") if there[n] else ("- [x]", "- [ ]")), 1)
    new = "\n".join(lines)
    active = "" if hidden(path) else new  # a note in the trash keeps no reminders
    synced = "".join("1" if t[2] else "0" for t in reminders.dated(active, meta["created"], meta.get("anchors", "")))
    if always or new != body or synced != was:
        count = reminders.push(meta, active)
        updated = {**meta, "reminders": str(count or ""), "synced": synced if count else ""}
        if updated != meta or new != body:
            write(updated, new, path)


def check(nid):
    remind(nid, always=False)


def sweep(_):
    """Every few minutes: pick up what was ticked on the phone, and retry anything that failed to sync."""
    reminders.setup()
    for nid, path in list(paths.items()):
        if path.exists() and not hidden(path):  # a note deleted by hand is skipped
            check(nid)


def every(seconds, job):
    while True:
        time.sleep(seconds)
        jobs.put((job, None))


def worker():
    while True:
        job, nid = jobs.get()
        try:
            job(nid)
        except Exception as e:
            print(f"{job.__name__} {nid} failed: {e!r}", flush=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/changes"):  # the 10-second sync would drown everything else
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")  # browsers always check for a newer app
        super().end_headers()

    def send_head(self):
        """Serves byte ranges: iPhone Safari won't play audio without them, and they make jumping work."""
        wanted = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
        path = Path(self.translate_path(self.path))
        if not wanted or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        start = int(wanted[1]) if wanted[1] else size - int(wanted[2])
        end = min(int(wanted[2]) if wanted[1] and wanted[2] else size - 1, size - 1)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        return io.BytesIO(path.read_bytes()[start : end + 1])

    def reply(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def payload(self):
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/changes":
            since = float(parse_qs(url.query).get("since", ["0"])[0])
            with lock:
                now = time.time()
                notes = [read(p) for p in NOTES.rglob("*.md") if p.stat().st_mtime >= since]
            return self.reply({"now": now, "notes": notes})
        if url.path.startswith("/files/"):
            self.directory, self.path = str(NOTES / "_files"), self.path[len("/files"):]
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/files/"):
            dest = NOTES / "_files" / time.strftime("%Y/%m") / Path(unquote(self.path[11:])).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.payload())
            return self.reply({"url": f"/files/{dest.relative_to(NOTES / '_files')}"})
        if self.path == "/api/notes":
            n = json.loads(self.payload())
            capture(n["id"], n["created"], n["text"], n.get("files", []))
            return self.reply({"ok": True})
        if self.path == "/api/quick":  # for iPhone Shortcuts: Siri, the Action Button, the share sheet
            kind, data, nid = self.headers.get("Content-Type", "").split(";")[0], self.payload(), secrets.token_hex(4)
            if kind.startswith("image/") and kind not in ("image/jpeg", "image/png"):
                return self.send_error(415, "Send photos as JPEG or PNG (iPhone HEIC photos would be read only in part)")
            files, text = [], ""
            if kind.startswith("image/"):
                dest = NOTES / "_files" / time.strftime("%Y/%m") / f"{nid}.{'jpg' if kind == 'image/jpeg' else 'png'}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                files = [f"/files/{dest.relative_to(NOTES / '_files')}"]
            else:
                text = str(json.loads(data).get("text", "")) if kind == "application/json" else data.decode()
            if not text.strip() and not files:
                return self.send_error(400, "Nothing to save")
            capture(nid, time.strftime("%Y-%m-%dT%H:%M"), text.strip(), files)
            return self.reply({"ok": True})
        if self.path == "/api/ask":  # the answer is sent as it's written, so it types itself out on the phone
            chat = json.loads(self.payload())["chat"]
            notes = [read(p) for p in list(paths.values()) if p.exists() and not hidden(p)]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            for piece in ask.answer(chat, notes):
                self.wfile.write(piece.encode())
                self.wfile.flush()
            return
        self.send_error(404)

    def do_PUT(self):
        nid, n = self.path.rsplit("/", 1)[-1], json.loads(self.payload())
        path = paths.get(nid)
        if not path:
            return self.reply({"ok": False})  # deleted meanwhile: drop the edit rather than retry it forever
        meta, old = parse(path.read_text())
        body = reminders.promote(old, n["body"])
        meta["anchors"] = reminders.anchor(old, body, meta.get("anchors", ""), n.get("edited"))
        if path.stat().st_mtime > n["base"] + 0.001:  # changed since the phone last saw it: keep both
            meta = {**meta, "id": f"{nid}-{int(time.time())}", "title": f"{meta.get('title', '')} (conflict)"}
            path = path.with_stem(f"{path.stem} (conflict)")
        write(meta, body, path)
        jobs.put((remind, meta["id"]))
        self.reply({"ok": True})

    def do_DELETE(self):
        """Moves a note to _trash, where it can be put back by hand, and removes its reminders."""
        path = paths.get(self.path.rsplit("/", 1)[-1])
        if path and not hidden(path):
            meta, body = parse(path.read_text())
            write(meta, body, NOTES / "_trash" / f"{path.stem} {meta['id']}.md")
            jobs.put((remind, meta["id"]))
        self.reply({"ok": True})


if __name__ == "__main__":
    NOTES.mkdir(parents=True, exist_ok=True)
    jobs.put((lambda _: reminders.setup(), None))  # first, so the calendar exists before anything is written to it
    for p in NOTES.rglob("*.md"):
        meta, _ = parse(p.read_text())
        if "id" in meta:
            paths[meta["id"]] = p
            if meta.get("status") == "raw":
                jobs.put((tidy, meta["id"]))
            elif not hidden(p):
                if p.parent == NOTES / "unsorted":
                    jobs.put((place, meta["id"]))
                jobs.put((check, meta["id"]))
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=every, args=(300, sweep), daemon=True).start()
    print(f"ember on http://{HOST}:{PORT}, notes in {NOTES}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
