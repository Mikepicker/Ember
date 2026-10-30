"""The notes on disk: Markdown files under data/notes, each with a few "key: value" lines on top. `paths` finds a note's
file by its id, and every write goes through `write`. Folders starting with "_" hold what the app doesn't list:
the originals, the trash, files, and the lists of folders and feeds."""
import os
import re
import threading
from pathlib import Path

import filing
import reminders
import tasks

NOTES = Path(os.environ.get("EMBER_NOTES", Path(__file__).resolve().parent.parent / "data" / "notes"))
FILES = NOTES / "_files"  # photos, recordings and pictures, served at /files/
FOLDERS = NOTES / "_folders.md"  # the folders new notes are filed into, edited in the app like a note
FEEDS = NOTES / "_feeds.md"  # the feeds whose stories show under read, edited the same way
lock = threading.Lock()
paths = {}  # note id -> file


def parse(text):
    meta, body = {}, text
    if text.startswith("---\n"):
        head, _, body = text[4:].partition("\n---\n")
        meta = dict(line.split(": ", 1) for line in head.splitlines() if ": " in line)
    return meta, body.strip()


def load(nid):
    return parse(paths[nid].read_text())


def write(meta, body, path):
    """Writes a note to `path`, and removes its old file if it moved."""
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text("---\n" + "".join(f"{k}: {v}\n" for k, v in meta.items() if v) + f"---\n\n{body.strip()}\n")
        tmp.replace(path)
        old = paths.get(meta["id"])
        if old and old != path:
            old.unlink(missing_ok=True)
        paths[meta["id"]] = path


def index():
    """Finds every note, at start."""
    for p in NOTES.rglob("*.md"):
        meta = parse(p.read_text())[0]
        if "id" in meta:
            paths[meta["id"]] = p


def hidden(path):
    return path.relative_to(NOTES).parts[0].startswith("_")


def folder(path):
    return path.parent.relative_to(NOTES).as_posix()


def filename(folder, created, title, nid):
    """"2026-10-30 call henrik.md" in the folder, with the note's id added if another note has that name."""
    name = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:60] or "note"
    path = NOTES / folder / f"{created[:10]} {name}.md"
    return path if not path.exists() or paths.get(nid) == path else path.with_stem(f"{path.stem} {nid}")


def read(path):
    """A note as the app gets it: front matter and body, where it is, and the moments of its tasks that went to the phone."""
    meta, body = parse(path.read_text())
    note = {**meta, "body": body, "path": str(path.relative_to(NOTES)), "mtime": path.stat().st_mtime}
    dated = tasks.dated(body, tasks.unpack(meta.get("due", ""))) if reminders.CALDAV and not hidden(path) else []
    note["due"] = [[i, f"{at:%Y-%m-%dT%H:%M}", tasks.kind(t), timed] for i, t, _, at, timed in dated]  # [line, "2026-10-28T17:00", "VTODO" or "VEVENT", has a time]
    if path == FOLDERS:
        note["folders"] = list(filing.folders(body))
    return note


def shown():
    """The notes the app lists."""
    return [read(p) for p in list(paths.values()) if p.exists() and not hidden(p)]


def listed(path):
    """The list of folders or of feeds."""
    return parse(path.read_text())[1] if path.exists() else ""
