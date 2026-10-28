"""Answers questions from the notes. The Pi's model reads about 24 words a second,
so each question goes with the few notes that share its rarer words, not with all of them.
Questions about the diary ("what's on tomorrow?") are answered from the reminders' dates, without the model."""
import json
import math
import re
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta

import pipeline

PROMPT = """You answer the writer's questions from their own notes, using only the notes given with the question.
Answer in one to three short sentences. Use a "- " list only when there are three or more things to name.
Keep names, times and amounts as the notes have them. Give dates as the notes have them, not as "tomorrow".
Put the number of the note each fact comes from in brackets right after it, like [2]. Never put a number on a line of its own.
If the notes don't answer the question, just say so, with no number."""
BUDGET = 2400  # characters of notes per question, about 25 seconds of reading on the Pi
COMMON = set("""a about after all also am an and any are as at be been before but by can could did do does done for from get
got had has have how i if in into is it its just me more my need needs no not of on or our out so some still than that the
their them then there these they this to up us was we were what when where which who why will with would you your""".split())


def words(text):
    """The first five letters are enough to match meeting with meetings, and remind with reminder."""
    return {w[:5] for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in COMMON}


DIARY = words("today tonight tomorrow week weekend monday tuesday wednesday thursday friday saturday sunday "
              "anything due coming planned plans schedule agenda task tasks happening")


def entry(n, number):
    """A note as the model reads it. "Tomorrow" in yesterday's note is today, so it becomes the date it meant."""
    created = datetime.fromisoformat(n["created"])
    body = re.sub(r"(?i)\b(today|tonight)\b", f"{created:%A %d %B}", n["body"])
    body = re.sub(r"(?i)\btomorrow\b", f"{created + timedelta(days=1):%A %d %B}", body)
    lines = re.sub(r"!?\[[^\]]*\]\(/files/[^)]*\)", "", body).split("\n")  # attachments mean nothing to the model
    for line, at, _, timed in n.get("due", []):  # "on Friday at 10" is spelled out too, so questions about dates work
        lines[line] += f" (due {datetime.fromisoformat(at):{'%A %d %B %H:%M' if timed else '%A %d %B'}})"
    return f"[{number}] {n['created'][:10]}, {n['path'].rsplit('/', 1)[0]}: {n.get('title', '')}\n" + "\n".join(lines).strip()[:1200]


def pick(question, notes):
    """The notes sharing the question's rarer words, best first; if none do, the five with the nearest dates."""
    asked = words(question)
    stems = {n["id"]: words(entry(n, 0)) for n in notes}  # due dates included, so "Thursday" finds what's due then
    df = Counter(w for s in stems.values() for w in s)
    score = {n["id"]: sum(math.log(len(notes) / df[w]) for w in asked & stems[n["id"]]) for n in notes}
    today = time.strftime("%Y-%m-%d")
    nearest = sorted(sorted(notes, key=lambda n: n["created"], reverse=True),
                     key=lambda n: min((at for _, at, *_ in n.get("due", []) if at >= today), default="~"))
    ranked = [n for n in sorted(nearest, key=lambda n: score[n["id"]], reverse=True) if score[n["id"]] > 0] or nearest[:5]
    picked, size = [], 0
    for n in ranked:
        if size + len(entry(n, 0)) <= BUDGET:
            picked.append(n)
            size += len(entry(n, 0))
    return picked


def days(question):
    """The days a diary question asks about: "what do I have today?", "anything due this week?".
    None for other questions, even ones naming a day, like "when do I meet Henrik tomorrow?"."""
    q, week = question.lower(), [datetime.now().date() + timedelta(days=i) for i in range(7)]
    if not words(q) or not words(q) <= DIARY:
        return []
    if "weekend" in q:
        return [d for d in week if d.weekday() >= 5]
    if "tomorrow" in q:
        return week[1:2]
    named = [d for d in week if f"{d:%A}".lower() in q]
    return named or (week[:1] if re.search(r"\b(today|tonight)\b", q) else week)


def diary(dates, notes):
    """The open tasks due on those days, from the dates Ember worked out for the reminders, all-day ones first.
    Asked to list them, the small model left some out."""
    tasks = sorted(((at, timed, n["id"], n["body"].split("\n")[line]) for n in notes for line, at, _, timed in n.get("due", [])
                    if datetime.fromisoformat(at).date() in dates and n["body"].split("\n")[line].lstrip().startswith("- [ ]")),
                   key=lambda t: (t[0][:10], t[1], t[0]))
    ids, out = list(dict.fromkeys(t[2] for t in tasks)), []
    for at, timed, nid, line in tasks:
        day = f"**{datetime.fromisoformat(at):%A %d %B}**"
        out += [] if day in out else [day]
        task = re.sub(r"(?i)\s*\b(today|tonight|tomorrow)\b", "", line.split("]", 1)[1]).strip()
        out.append(f"- {at[11:] + ' ' if timed else ''}{task} [{ids.index(nid) + 1}]")
    return ids, "\n".join(out) or (f"Nothing is due on {dates[0]:%A %d %B}." if len(dates) == 1 else "Nothing is due in those days.")


def answer(chat, notes):
    """chat holds the questions and answers so far and ends with the new question. The model sees the question before,
    enough for "and what do I ask him?", but not its own earlier answers, which a small model would only repeat.
    Yields the ids of the numbered notes as a JSON line, then the answer as it's written."""
    question, before = chat[-1], chat[-3] if len(chat) > 2 else ""
    if dates := days(question):
        ids, text = diary(dates, notes)
        yield json.dumps(ids) + "\n" + text
        return
    picked = pick(f"{question}\n{before}", notes)
    asked = (f"The question before was: {before}\n" if before else "") + f"Question: {question}"
    notes_text = "\n\n".join(entry(n, k + 1) for k, n in enumerate(picked))
    messages = [{"role": "system", "content": f"{PROMPT}\nToday is {time.strftime('%A %d %B %Y')}."},
                {"role": "user", "content": f"Notes:\n{notes_text}\n\n{asked}"}]
    yield json.dumps([n["id"] for n in picked]) + "\n"
    request = {"messages": messages, "temperature": 0, "max_tokens": 250, "stream": True, "chat_template_kwargs": {"enable_thinking": False},
               "dry_multiplier": 0.8}  # without it, a long list can get stuck repeating one line
    req = urllib.request.Request(f"{pipeline.LLM}/v1/chat/completions", json.dumps(request).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        for line in r:
            if line.startswith(b"data: {"):
                for choice in json.loads(line[6:]).get("choices", []):
                    yield choice["delta"].get("content") or ""
