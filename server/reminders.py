"""Dated tasks mirrored into a CalDAV server, which the iPhone's Reminders and Calendar apps read: meetings as events,
everything else as reminders. Each is a file named after its note and its task, "<note id>-<task key>.ics"."""
import base64
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import tasks

CALDAV = os.environ.get("EMBER_CALDAV", "")  # a calendar collection, e.g. http://127.0.0.1:5232/ember/notes/; empty: off
LOGIN = os.environ.get("EMBER_CALDAV_LOGIN", "")  # user:password
URL = os.environ.get("EMBER_URL", "http://127.0.0.1:8787")


def utc(d):
    return d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics(uid, note, text, done, at, timed):
    esc = lambda s: re.sub(r"([\\;,])", r"\\\1", s).replace("\n", "\\n")
    alarm = lambda trigger: ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(text)}", trigger, "END:VALARM"]
    kind = tasks.kind(text)
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


def push(note, dated, gone):
    """Writes the note's dated tasks to the calendar, and removes those of the tasks in `gone`, by key."""
    for _, text, done, at, timed in dated:
        uid = f"{note['id']}-{tasks.key(text)}"
        dav("PUT", f"{uid}.ics", ics(uid, note, text, done, at, timed))
    for k in gone:
        dav("DELETE", f"{note['id']}-{k}.ics")


def ticked(nid, keys):
    """For each of the note's reminders still there: whether it's ticked off in the Reminders app. Events have no ticks."""
    there = {k: dav("GET", f"{nid}-{k}.ics") or "" for k in keys}
    return {k: "STATUS:COMPLETED" in text for k, text in there.items() if "BEGIN:VTODO" in text}
