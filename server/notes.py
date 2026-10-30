"""What happens to a note: captured from the phone, tidied and filed in the background, edited, moved and put in the
trash, with its dated tasks kept in sync with Reminders and Calendar. Background jobs run one at a time."""
import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import feeds
import filing
import media
import related
import reminders
import store
import tasks
import tidy

UNSORTED = store.NOTES / "unsorted"  # new notes, until they're tidied and filed
SAVED = store.NOTES / "saved"  # stories saved under read, filed there as they are, never by the 2B
jobs = queue.Queue()


def later(job, *args):
    jobs.put((job, args))


def capture(nid, created, text, files, folder=UNSORTED):
    """A new note waits in unsorted/ until it has been tidied and filed. A note sent twice is kept once."""
    if nid not in store.paths:
        store.write({"id": nid, "created": created, "status": "raw", "files": " ".join(files)}, text, folder / f"{created[:10]} {nid}.md")
        later(tidy_up, nid)


def attachment(url):
    return f"[voice]({url})" if Path(url).suffix.lower() in media.AUDIO else f"![photo]({url})"


def tidy_up(nid):
    """Hears the note's recordings, reads its photos, keeps the original under _raw, and tidies it."""
    meta, body = store.load(nid)
    if meta.get("status") != "raw":  # tidied already: the sweep can queue a note twice
        return
    created, urls = meta["created"], meta.get("files", "").split()
    files = [store.FILES / url.removeprefix("/files/") for url in urls]
    recordings = [f for f in files if f.suffix.lower() in media.AUDIO]
    for f in recordings:
        media.remux(f)
    heard = "\n\n".join(media.transcribe(f) for f in recordings)
    looked = [media.read(f) for f in files if f not in recordings]
    seen = "\n\n".join(text for text, _ in looked)  # kept exactly as read
    raw = "\n\n".join(t for t in (body, heard) if t)
    original = f"_raw/{created[:7].replace('-', '/')}/{nid}.md"
    store.write({"id": f"{nid}.raw", "created": created, "title": "original"}, f"{raw}\n\n{seen}", store.NOTES / original)
    note = tidy.tidy(raw, datetime.fromisoformat(created)) if raw else {**tidy.layout(seen[:600]), "body": "", "due": {}}  # a photo alone is named from what it shows
    if note.get("link"):  # a web page: the picture it had under read, or else the page's own
        picture = store.FILES / time.strftime("%Y/%m") / f"{nid}.jpg"
        try:
            feeds.shrink(feeds.picture_of(note["link"]), picture, "scale='min(800,iw)':-2")
            urls.append(f"/files/{picture.relative_to(store.FILES)}")
        except Exception:
            pass  # a page without a picture
    body = "\n\n".join(t for t in (note["body"], seen, "\n".join(map(attachment, urls))) if t)
    tags = dict.fromkeys([*note["tags"], *(kind for _, kind in looked if kind)])  # "dog" for a photo of a Labrador
    meta = {"id": nid, "created": created, "title": note["title"], "tags": ", ".join(tags), "original": original, "due": tasks.pack(note["due"])}
    here = store.folder(store.paths[nid])  # "unsorted", or "saved" for a story saved under read
    store.write(meta, body, store.filename(here, created, note["title"], nid))
    if here == "unsorted":
        place(nid)
    remind(nid)


def place(nid):
    """Files a new note into one of the folders in the list."""
    path, choices = store.paths[nid], filing.folders(store.listed(store.FOLDERS))
    meta, body = store.parse(path.read_text())
    if not choices or not re.sub(r"!?\[[^\]]*\]\(/files/[^)]*\)", "", body).strip():
        return  # nowhere to go, or nothing to go on yet, e.g. an untranscribed recording
    raw = (store.NOTES / meta["original"]).read_text() if meta.get("original") else ""
    others = [(store.folder(p), p.read_text()) for other, p in list(store.paths.items())
              if other != nid and p.exists() and not store.hidden(p) and p.parent not in (UNSORTED, SAVED)]
    to = filing.place({"title": meta.get("title", ""), "body": body}, raw, others, choices)
    store.write(meta, body, store.filename(to, meta["created"], meta.get("title", ""), nid))


def remind(nid, always=True):
    """Two-way sync of the note's dated tasks with Reminders and Calendar. `synced` holds each one's tick at the last
    sync, so whichever side changed since then wins. A note in the trash keeps no reminders."""
    if not reminders.CALDAV:
        return
    path = store.paths[nid]
    meta, body = store.parse(path.read_text())
    was, lines = tasks.unpack(meta.get("synced", "")), body.split("\n")
    there = reminders.ticked(nid, was)
    for i, text, done in tasks.found(body):
        k = tasks.key(text)
        if k in there and there[k] != (was[k] == "done") and there[k] != done:  # ticked or unticked on the phone
            lines[i] = re.sub(r"\[[ x]\]", "[x]" if there[k] else "[ ]", lines[i], count=1)
    new = "\n".join(lines)
    dated = [] if store.hidden(path) else tasks.dated(new, tasks.unpack(meta.get("due", "")))
    synced = {tasks.key(t): "done" if done else "open" for _, t, done, *_ in dated}
    if always or new != body or synced != was:
        reminders.push(meta, dated, set(was) - set(synced))
        if new != body or synced != was:
            store.write({**meta, "synced": tasks.pack(synced)}, new, path)


def edit(nid, body, base, edited):
    """An edit from the phone, made at `edited`. A note changed here since the phone last saw it is kept as a copy too."""
    path = store.paths.get(nid)
    if not path:
        return  # deleted meanwhile: the edit is dropped rather than tried again forever
    meta, old = store.parse(path.read_text())
    if path in (store.FOLDERS, store.FEEDS):  # lists, not notes: a line naming a month mustn't become a task
        return store.write(meta, body, path)
    body = tasks.promote(old, body)
    meta["due"] = tasks.pack(tasks.redate(old, body, tasks.unpack(meta.get("due", "")), datetime.fromisoformat(edited)))
    if path.stat().st_mtime > base + 0.001:  # changed since the phone last saw it: keep both
        meta = {**meta, "id": f"{nid}-{int(time.time())}", "title": f"{meta.get('title', '')} (conflict)", "synced": ""}
        path = path.with_stem(f"{path.stem} (conflict)")
    store.write(meta, body, path)
    later(remind, meta["id"])


def move(nid, to):
    """Moves a note into one of the folders in the list."""
    if to in filing.folders(store.listed(store.FOLDERS)):
        meta, body = store.load(nid)
        store.write(meta, body, store.filename(to, meta["created"], meta.get("title", ""), nid))


def trash(nid):
    """Moves a note to _trash, where it can be put back by hand, and removes its reminders."""
    path = store.paths.get(nid)
    if path and not store.hidden(path):
        meta, body = store.parse(path.read_text())
        store.write(meta, body, store.NOTES / "_trash" / f"{path.stem} {nid}.md")
        later(remind, nid)


def sweep():
    """Picks up what was ticked on the phone, tries again what failed to be tidied or synced, and reads the meaning
    of new notes, so a question doesn't wait for them; at start the meaning server may still be loading."""
    reminders.setup()
    related.meanings()
    for nid, path in list(store.paths.items()):
        if path.exists() and not store.hidden(path):  # a note deleted by hand is skipped
            later(tidy_up, nid) if store.parse(path.read_text())[0].get("status") == "raw" else later(remind, nid, False)


def work():
    while True:
        job, args = jobs.get()
        try:
            job(*args)
        except Exception as e:
            print(f"{job.__name__}{args} failed: {e!r}", flush=True)


def every(seconds, job):
    while True:
        time.sleep(seconds)
        later(job)


def start():
    """The calendar first, so it exists before anything is written to it; then what was left undone; then a sweep
    every five minutes."""
    later(reminders.setup)
    for nid, path in list(store.paths.items()):
        if store.parse(path.read_text())[0].get("status") == "raw":
            later(tidy_up, nid)
        elif not store.hidden(path):
            if path.parent == UNSORTED:
                later(place, nid)
            later(remind, nid, False)
    later(related.meanings)  # every note's meaning, read once, so the first question doesn't wait for them
    threading.Thread(target=work, daemon=True).start()
    threading.Thread(target=every, args=(300, sweep), daemon=True).start()
