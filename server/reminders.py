"""Mirrors dated tasks into a CalDAV server, which the iPhone's Reminders and Calendar apps read."""
import base64
import hashlib
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

CALDAV = os.environ.get("EMBER_CALDAV", "")  # a calendar collection, e.g. http://127.0.0.1:5232/ember/notes/
LOGIN = os.environ.get("EMBER_CALDAV_LOGIN", "")  # user:password
URL = os.environ.get("EMBER_URL", "http://127.0.0.1:8787")

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
PARTS = {"morning": 9, "noon": 12, "afternoon": 14, "evening": 19, "tonight": 20}
MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
MEETING = re.compile(r"\b(meet|meeting|appointment|interview|dinner|lunch)\b", re.I)


def date_in(t, now):
    if re.search(r"\b(today|tonight)\b", t):
        return now.date()
    if "tomorrow" in t:
        return now.date() + timedelta(days=1)
    if m := re.search(r"\bin (\d+|a|one|two|three) (day|week)s?\b", t):
        n = {"a": 1, "one": 1, "two": 2, "three": 3}.get(m[1]) or int(m[1])
        return now.date() + timedelta(days=n * (7 if m[2] == "week" else 1))
    if m := re.search(r"\b(" + "|".join(DAYS) + r"|weekend)\b", t):
        weekday = 5 if m[1] == "weekend" else DAYS.index(m[1])
        return now.date() + timedelta(days=(weekday - now.weekday()) % 7 or 7)
    if m := re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*-\s*\d{{1,2}})? {MONTH}\b|\b{MONTH} (\d{{1,2}})\b", t):  # "12-16 dec" means the 12th
        day, month = (int(m[1]), m[2]) if m[1] else (int(m[4]), m[3])
        return upcoming(now, MONTHS.index(month) + 1, day)
    if m := re.search(r"\b(\d{1,2})/(\d{1,2})\b", t):  # day/month
        return upcoming(now, int(m[2]), int(m[1]))
    if m := re.search(r"\b(january|february|march|april|june|july|august|september|october|november|december)\b", t):
        return upcoming(now, MONTHS.index(m[1][:3]) + 1, 1)


def upcoming(now, month, day):
    try:
        d = now.date().replace(month=month, day=day)
        return d if d >= now.date() else d.replace(year=d.year + 1)
    except ValueError:
        return None


def time_in(t):
    if m := re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", t):
        hour, minute, half = int(m[1]), int(m[2]), m[3]
    elif m := re.search(r"\b(\d{1,2})\s*(am|pm)\b", t):
        hour, minute, half = int(m[1]), 0, m[2]
    elif m := re.search(r"\bat (\d{1,2})\b", t):
        hour, minute, half = int(m[1]), 0, "pm" if int(m[1]) < 7 else None  # "at 4" means the afternoon
    elif m := re.search(r"\b(" + "|".join(PARTS) + r")\b", t):
        return PARTS[m[1]], 0
    else:
        return None
    hour = hour % 12 + 12 if half == "pm" else hour % 12 if half == "am" else hour
    return (hour, minute) if hour < 24 and minute < 60 else None


def when(text, now):
    """The moment a task mentions, as (datetime, has a time), or None. Words like "friday" count from `now`."""
    t = text.lower().replace("a.m.", "am").replace("p.m.", "pm")
    day, time = date_in(t, now), time_in(t)
    if not day and (not time or not re.search(r"\d", t)):  # "in the morning" alone isn't a reminder; "at 4" is
        return None
    if not day:
        day = now.date() if time >= (now.hour, now.minute) else now.date() + timedelta(days=1)
    if day and re.search(r"\b(before|by)\b", t) and not time:
        day -= timedelta(days=1)
    hour, minute = time or (9, 0)
    return datetime(day.year, day.month, day.day, hour, minute), bool(time)


def key(task):
    return hashlib.sha1(task.strip().encode()).hexdigest()[:6]


def tasks(body):
    return re.findall(r"(?m)^\s*- \[[ x]\] (.+)$", body)


def anchor(old, new, anchors, edited):
    """Tasks added or reworded in an edit count words like "tomorrow" from `edited`; the others keep their anchor.
    Anchors are stored as "key@time key@time"; a task without one counts from when the note was written."""
    kept, before, out = dict(a.split("@") for a in anchors.split()), {key(t) for t in tasks(old)}, {}
    for k in map(key, tasks(new)):
        if k in kept:
            out[k] = kept[k]
        elif k not in before and edited:
            out[k] = edited
    return " ".join(f"{k}@{v}" for k, v in out.items())


def dated(body, created, anchors=""):
    """The note's tasks that mention a date or time: (line number, text, done, moment, has a time)."""
    kept, found = dict(a.split("@") for a in anchors.split()), []
    for i, line in enumerate(body.split("\n")):
        m = re.match(r"\s*- \[([ x])\] (.+)", line)
        if m and (at := when(m[2], datetime.fromisoformat(kept.get(key(m[2]), created)))):
            found.append((i, m[2], m[1] == "x", *at))
    return found


def component(text):
    """Meetings go to Calendar as events; everything else to Reminders."""
    return "VEVENT" if MEETING.search(text) else "VTODO"


def utc(d):
    return d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def item(uid, note, text, done, at, timed):
    esc = lambda s: re.sub(r"([\\;,])", r"\\\1", s).replace("\n", "\\n")
    alarm = lambda trigger: ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(text)}", trigger, "END:VALARM"]
    kind = component(text)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ember//EN", f"BEGIN:{kind}",
        f"UID:{uid}", f"DTSTAMP:{utc(datetime.fromisoformat(note['created']))}", f"SUMMARY:{esc(text)}",
        f"DESCRIPTION:{esc('From the note ' + note.get('title', ''))}", f"URL:{URL}/#n/{note['id']}",
    ]
    if kind == "VTODO":
        lines += [f"DUE:{utc(at)}", f"STATUS:{'COMPLETED' if done else 'NEEDS-ACTION'}", *alarm(f"TRIGGER;VALUE=DATE-TIME:{utc(at)}")]
    elif timed:
        lines += [f"DTSTART:{utc(at)}", f"DTEND:{utc(at + timedelta(hours=1))}", *alarm("TRIGGER:-PT15M")]
    else:
        lines += [f"DTSTART;VALUE=DATE:{at:%Y%m%d}", f"DTEND;VALUE=DATE:{at + timedelta(days=1):%Y%m%d}"]
    return "\r\n".join([*lines, f"END:{kind}", "END:VCALENDAR", ""])


def dav(method, name="", body=None):
    headers = {"Content-Type": "application/xml" if method == "MKCALENDAR" else "text/calendar; charset=utf-8"}
    if LOGIN:
        headers["Authorization"] = "Basic " + base64.b64encode(LOGIN.encode()).decode()
    req = urllib.request.Request(CALDAV + name, body and body.encode(), headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404 or (e.code == 409 and method == "MKCALENDAR"):  # already gone, or the calendar exists already
            return None
        raise


def setup():
    """Creates the calendar once. It holds reminders and events, so it shows in both apps."""
    if CALDAV:
        dav("MKCALENDAR", body='<?xml version="1.0"?><C:mkcalendar xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:set><D:prop><D:displayname>ember</D:displayname><C:supported-calendar-component-set>"
            '<C:comp name="VTODO"/><C:comp name="VEVENT"/></C:supported-calendar-component-set></D:prop></D:set></C:mkcalendar>')


def push(note, body):
    """Writes the note's dated tasks to the calendar and removes ones that are gone. Returns how many there are."""
    found = dated(body, note["created"], note.get("anchors", "")) if CALDAV else []
    for n, (_, text, done, at, timed) in enumerate(found):
        dav("PUT", f"{note['id']}-{n}.ics", item(f"{note['id']}-{n}", note, text, done, at, timed))
    for n in range(len(found), int(note.get("reminders") or 0)):
        dav("DELETE", f"{note['id']}-{n}.ics")
    return len(found)


def ticked(note):
    """For each of the note's reminders (events have no ticks): whether it is ticked off in the Reminders app."""
    out = {}
    for n in range(int(note.get("reminders") or 0) if CALDAV else 0):
        if "BEGIN:VTODO" in (text := dav("GET", f"{note['id']}-{n}.ics") or ""):
            out[n] = "STATUS:COMPLETED" in text
    return out
