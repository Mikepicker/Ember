"""Tasks in a note, lines like "- [ ] call Henrik tomorrow", and when each is due. A task's moment is worked out once,
when it's written, and kept with the note as `due`: "key=2026-10-31" for a day, "key=2026-10-31T15:00" with a time.
Words like "tomorrow" count from the writer's day, which starts at 4 am: written at 00:30, "tomorrow" is the coming day."""
import hashlib
import re
from datetime import datetime, timedelta

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
PARTS = {"morning": 9, "noon": 12, "afternoon": 14, "evening": 19, "tonight": 20}
EVENING = re.compile(r"\b(dinner|drinks|party|evening|tonight)\b")  # "dinner at 8" is at 20:00
MEETING = re.compile(r"\b(meet|meeting|appointment|interview|dinner|lunch)\b", re.I)
WHEN_WORDS = {*DAYS, *MONTHS, *PARTS, *"""january february march april june july august september october november december today
    tomorrow day days week weeks weekend am pm st nd rd th remind reminder reminders me set all these them do due for on at by
    before in a this next the""".split()}


def date_in(t, today):
    if re.search(r"\b(today|tonight)\b", t):
        return today
    if "tomorrow" in t:
        return today + timedelta(days=1)
    if m := re.search(r"\bin (\d+|a|one|two|three) (day|week)s?\b", t):
        n = {"a": 1, "one": 1, "two": 2, "three": 3}.get(m[1]) or int(m[1])
        return today + timedelta(days=n * (7 if m[2] == "week" else 1))
    if m := re.search(r"\b(" + "|".join(DAYS) + r"|weekend)\b", t):
        weekday = 5 if m[1] == "weekend" else DAYS.index(m[1])
        return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)
    if m := re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*-\s*\d{{1,2}})? {MONTH}\b|\b{MONTH} (\d{{1,2}})\b", t):  # "12-16 dec" means the 12th
        day, month = (int(m[1]), m[2]) if m[1] else (int(m[4]), m[3])
        return upcoming(today, MONTHS.index(month) + 1, day)
    if m := re.search(r"\b(\d{1,2})/(\d{1,2})\b", t):  # day/month
        return upcoming(today, int(m[2]), int(m[1]))
    if m := re.search(r"\b(?:before|by) (january|february|march|april|june|july|august|september|october|november|december)\b", t):
        return upcoming(today, MONTHS.index(m[1][:3]) + 1, 1)  # a month alone is a deadline: "for august" isn't


def upcoming(today, month, day):
    try:
        d = today.replace(month=month, day=day)
        return d if d >= today else d.replace(year=d.year + 1)
    except ValueError:
        return None


def time_in(t):
    """(hour, minute), or None. Without am or pm, "at 4" is in the afternoon, and so is dinner at 8."""
    if m := re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t):
        hour, minute, half = int(m[1]), int(m[2] or 0), m[3]
    elif m := re.search(r"\b(\d{1,2}):(\d{2})\b", t) or re.search(r"\bat (\d{1,2})()\b", t):
        hour, minute = int(m[1]), int(m[2] or 0)
        half = "pm" if hour < 7 or EVENING.search(t) else None
    elif m := re.search(r"\b(" + "|".join(PARTS) + r")\b", t):
        return PARTS[m[1]], 0
    else:
        return None
    hour = hour % 12 + 12 if half == "pm" else hour % 12 if half == "am" else hour
    return (hour, minute) if hour < 24 and minute < 60 else None


def when(text, now, under=""):
    """When a task written at `now` is due, or None if it names no day or time; what it doesn't name comes from the heading
    it was written `under`. "Before Friday" is Thursday. A reminder for today written after 9 goes off two hours later,
    but never at night."""
    t, h = (s.lower().replace("a.m.", "am").replace("p.m.", "pm") for s in (text, under))
    today = (now - timedelta(hours=4)).date()
    day, time = date_in(t, today) or date_in(h, today), time_in(t) or time_in(h)
    if not day and (not time or not re.search(r"\d", t)):  # "in the morning" alone isn't a reminder; "at 4" is
        return None
    if not day:  # the next one: "at 4" written at 5 is tomorrow
        day = now.date() if time >= (now.hour, now.minute) else now.date() + timedelta(days=1)
    if time:
        return f"{day}T{time[0]:02}:{time[1]:02}"
    if re.search(r"\b(before|by)\b", t):
        day -= timedelta(days=1)
    if datetime(day.year, day.month, day.day, 9) < now and not MEETING.search(t):
        at = (now + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
        at = at if 9 <= at.hour < 22 else at.replace(hour=9) + timedelta(days=at.hour >= 22)
        return f"{at:%Y-%m-%dT%H:%M}"
    return str(day)


def only_when(line):
    """Whether a line says nothing but when, like "reminders for today at 2pm"; "good day today" says more."""
    return all(w.isdigit() or w in WHEN_WORDS for w in re.findall(r"[a-z]+|\d+", line.lower()))


def kind(text):
    """Meetings go to Calendar as events; everything else to Reminders."""
    return "VEVENT" if MEETING.search(text) else "VTODO"


def key(text):
    return hashlib.sha1(text.strip().encode()).hexdigest()[:6]


def found(body):
    """The note's tasks: (line number, text, done)."""
    return [(i, m[2], m[1] == "x") for i, line in enumerate(body.split("\n")) if (m := re.match(r"\s*- \[([ x])\] (.+)", line))]


def dated(body, due):
    """The note's tasks with a moment: (line number, text, done, moment, has a time). A day alone is at 9."""
    moments = [(i, t, done, due.get(key(t))) for i, t, done in found(body)]
    return [(i, t, done, datetime.fromisoformat(at if "T" in at else f"{at}T09:00"), "T" in at) for i, t, done, at in moments if at]


def promote(old, new):
    """Only new notes meet the model, which is what makes "finish the roadmap at 10" a task. So a line typed in later
    that names a day or time becomes a task too; one whose box was taken off by hand stays as it is."""
    text = lambda line: re.sub(r"^\s*(- )?(\[[ x]\] )?", "", line)
    before = {text(line) for line in old.split("\n")}
    new_task = lambda m: m[2] not in before and "://" not in m[2] and when(m[2], datetime.now())
    return re.sub(r"(?m)^([ \t]*)(?:- (?!\[[ x]\] ))?(\w.*)$", lambda m: f"{m[1]}- [ ] {m[2]}" if new_task(m) else m[0], new)


def redate(old, new, due, now):
    """The moments of the tasks after an edit at `now`: a task kept keeps its own, one added or reworded counts from now."""
    before, out = {key(t) for _, t, _ in found(old)}, {}
    for _, t, _ in found(new):
        if key(t) in due:
            out[key(t)] = due[key(t)]
        elif key(t) not in before and (at := when(t, now)):
            out[key(t)] = at
    return out


def unpack(text):
    return dict(pair.split("=", 1) for pair in text.split())


def pack(pairs):
    return " ".join(f"{k}={v}" for k, v in pairs.items())
