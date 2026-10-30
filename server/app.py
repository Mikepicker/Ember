"""Ember's server: the app, and the API it syncs with. Notes are kept by `store`; `notes` says what happens to them."""
import io
import json
import os
import re
import secrets
import subprocess
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import ask
import feeds
import filing
import notes
import related
import speech
import store

WEB = Path(__file__).resolve().parent.parent / "web"
HOST = os.environ.get("EMBER_HOST", "127.0.0.1")
PORT = int(os.environ.get("EMBER_PORT", "8787"))
THUMBS = store.FILES / "thumbs"  # the stories' pictures, small


def upload(name, data):
    """Keeps a file from the phone, and returns its address."""
    dest = store.FILES / time.strftime("%Y/%m") / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return f"/files/{dest.relative_to(store.FILES)}"


def changes(since):
    """Every note written since then, and when that was asked."""
    with store.lock:
        return {"now": time.time(), "notes": [store.read(p) for p in store.NOTES.rglob("*.md") if p.stat().st_mtime >= since]}


def news(fresh):
    """The stories to read; pulled down in the app, the feeds are fetched again unless they were a minute ago."""
    stories, failed = feeds.latest(store.listed(store.FEEDS), THUMBS, 60 if fresh else feeds.FRESH)
    return {"stories": stories, "failed": failed, "for_you": related.for_you(stories)}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

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
        query, last = parse_qs(url.query), url.path.rsplit("/", 1)[-1]
        if url.path == "/api/changes":
            return self.reply(changes(float(query.get("since", ["0"])[0])))
        if url.path == "/api/news":
            return self.reply(news("fresh" in query))
        if url.path.startswith("/api/listen/"):
            return self.listen(last)
        if url.path.startswith("/api/related/"):  # shown under a note
            return self.reply({"ids": related.near(last)})
        if url.path.startswith("/files/"):
            self.directory, self.path = str(store.FILES), self.path[len("/files"):]
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/files/"):
            return self.reply({"url": upload(Path(unquote(self.path[11:])).name, self.payload())})
        if self.path == "/api/notes":
            n = json.loads(self.payload())
            notes.capture(n["id"], n["created"], n["text"], n.get("files", []), notes.SAVED if n.get("saved") else notes.UNSORTED)
            return self.reply({"ok": True})
        if self.path == "/api/quick":
            return self.quick()
        if self.path == "/api/ask":
            return self.answer()
        self.send_error(404)

    def do_PUT(self):
        nid, n = self.path.rsplit("/", 1)[-1], json.loads(self.payload())
        if "folder" in n:  # moved in the app
            notes.move(nid, n["folder"])
        else:
            notes.edit(nid, n["body"], n.get("base", 0), n.get("edited") or time.strftime("%Y-%m-%dT%H:%M"))
        self.reply({"ok": True})

    def do_DELETE(self):
        notes.trash(self.path.rsplit("/", 1)[-1])
        self.reply({"ok": True})

    def listen(self, nid):
        """A note read aloud, sent as a file so the iPhone can jump through it."""
        path = store.paths.get(nid)
        if not speech.SERVER or not path or not path.exists():
            return self.send_error(404)
        meta, body = store.parse(path.read_text())
        try:
            heard = speech.say(speech.spoken(meta.get("title", ""), body), store.FILES / "speech")
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"listen failed: {e!r}", flush=True)
            return self.send_error(503)
        self.send_response(302)
        self.send_header("Location", f"/files/speech/{heard.name}")
        self.end_headers()

    def quick(self):
        """For iPhone Shortcuts (Siri, the Action Button, the share sheet): JSON {"text": …}, plain text, or a photo."""
        kind, data, nid = self.headers.get("Content-Type", "").split(";")[0], self.payload(), secrets.token_hex(4)
        photo = kind.startswith("image/")
        if photo and kind not in ("image/jpeg", "image/png"):
            return self.send_error(415, "Send photos as JPEG or PNG (iPhone HEIC photos would be read only in part)")
        text = "" if photo else str(json.loads(data).get("text", "")) if kind == "application/json" else data.decode()
        if not photo and not text.strip():
            return self.send_error(400, "Nothing to save")
        files = [upload(f"{nid}.{'jpg' if kind == 'image/jpeg' else 'png'}", data)] if photo else []
        notes.capture(nid, time.strftime("%Y-%m-%dT%H:%M"), text.strip(), files)
        self.reply({"ok": True})

    def answer(self):
        """The answer is sent as it's written, so it types itself out on the phone."""
        chat = json.loads(self.payload())["chat"]
        known = related.meanings()  # the notes with their meanings, or none while the meaning server is down
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        for piece in ask.answer(chat, [n for n, _ in known] or store.shown(), [v for _, v in known]):
            self.wfile.write(piece.encode())
            self.wfile.flush()


if __name__ == "__main__":
    store.NOTES.mkdir(parents=True, exist_ok=True)
    store.index()
    for path, name, text in ((store.FOLDERS, "folders", filing.FOLDERS), (store.FEEDS, "feeds", feeds.FEEDS)):
        if not path.exists():
            store.write({"id": name, "created": time.strftime("%Y-%m-%dT%H:%M"), "title": name}, text, path)
    notes.start()
    print(f"ember on http://{HOST}:{PORT}, notes in {store.NOTES}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
