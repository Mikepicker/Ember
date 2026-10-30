"""How well new notes become tasks with the right dates: each note in tidying.json is tidied as if written at its "at",
or else on Tuesday 27 Oct 2026 at 18:00, and the reminders it makes are checked against the ones it should make.

    EMBER_LLM=http://127.0.0.1:8091 python3 eval/tidying.py

"due" names a word of each task that must get a reminder, and when it's due; "maybe" a task that may get one or not.
Any other reminder is wrong.
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "server"))
import tasks  # noqa: E402
import tidy  # noqa: E402


def reminders(text, at):
    """The note as tidied, and its reminders: (task, when it's due)."""
    note = tidy.tidy(text, at)
    return note, [(t, note["due"][tasks.key(t)]) for _, t, _ in tasks.found(note["body"]) if tasks.key(t) in note["due"]]


def check(case, made):
    """What's wrong with the reminders made: one missed or on the wrong day, or one not wanted."""
    wrong = []
    for word, at in case.get("due", {}).items():
        got = [m for t, m in made if word in t.lower()]
        if at not in got:
            wrong.append(f"{word}: {got[0] if got else 'missed'}, not {at}")
    wanted = [*case.get("due", {}), *case.get("maybe", [])]
    return wrong + [f"not wanted: {t} {m}" for t, m in made if not any(w in t.lower() for w in wanted)]


def run(remind=reminders):
    cases, right, kept, start = json.loads((HERE / "tidying.json").read_text()), 0, 0, time.time()
    for case in cases:
        note, made = remind(case["text"], datetime.fromisoformat(case.get("at", "2026-10-27T18:00")))
        wrong = check(case, made)
        right, kept = right + (not wrong), kept + ("needs-review" not in note["tags"])
        if wrong:
            print(f"✗ {case['text'][:70]!r}\n  {note['title']!r} {note['body'][:200]!r}\n  {'; '.join(wrong)}")
    n = len(cases)
    print(f"\nreminders right in {right}/{n} notes, clean-ups kept {kept}/{n}, {(time.time() - start) / n:.1f} s a note")


if __name__ == "__main__":
    run()
