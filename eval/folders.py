"""How well does each model tidy and file notes with nobody's help?

Each model tidies every note and picks its area. Notes are replayed in the order they arrive, and the
names rule only sees the notes before each one, so an early mistake can mislead later ones.
usage: EVAL_MODELS="2B=http://127.0.0.1:8091,1.2B=http://127.0.0.1:8095" python3 eval/folders.py eval/notes.json eval/holdout.json
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import filing  # noqa: E402
import model  # noqa: E402
import tidy  # noqa: E402

CACHE = Path(__file__).resolve().parent / ".cache.json"
MODELS = dict(m.split("=", 1) for m in os.environ.get("EVAL_MODELS", f"model={model.LLM}").split(","))


def prepare(name, files):
    """Tidies each note and asks for its area, from the starting folders and their descriptions; cached per model."""
    model.LLM, cache, notes = MODELS[name], json.loads(CACHE.read_text()) if CACHE.exists() else {}, []
    mine = cache.setdefault(name, {})
    for n in (n for f in files for n in json.loads(Path(f).read_text())):
        if n["text"] not in mine:
            start = time.time()
            out = tidy.tidy(n["text"], datetime(2026, 10, 27, 18))
            c = {"title": out["title"], "body": out["body"], "kept": "needs-review" not in out["tags"]}
            c["hints"] = filing.pick(f"{out['title']}\n{out['body']}", filing.folders(filing.FOLDERS))
            mine[n["text"]] = {**c, "seconds": time.time() - start}
            CACHE.write_text(json.dumps(cache))
        c, text = mine[n["text"]], f"{n['text']}\n{mine[n['text']]['title']}\n{mine[n['text']]['body']}"
        notes.append({**n, **c, "names": filing.names(text), "words": set(re.findall(r"[a-z]+", text.lower()))})
    return notes


def by_names(note, filed):
    """The single area holding earlier notes that share this note's names; a word counts as a name once any note wrote it as one."""
    known = set().union(*(f["names"] for f in filed))
    areas = {f["guess"] for f in filed if (note["names"] | (note["words"] & known)) & f["words"]}
    return areas.pop() if len(areas) == 1 else None


def replay(notes, key):
    filed = []
    for note in notes:
        filed.append({**note, "guess": by_names(note, filed) or note[key]})
    return sum(f["guess"] == f["area"] for f in filed)


if __name__ == "__main__":
    files = sys.argv[1:] or [Path(__file__).resolve().parent / "notes.json"]
    print(f"{'model':10}{'clean-up kept':>15}{'area right':>13}{'s/note (Mac)':>15}")
    for name in MODELS:
        notes = prepare(name, files)
        n = len(notes)
        kept = sum(x["kept"] for x in notes)
        print(f"{name:10}{kept:>11}/{n}{replay(notes, 'hints'):>9}/{n}{sum(x['seconds'] for x in notes) / n:>15.1f}")
