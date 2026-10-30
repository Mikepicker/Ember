"""Notes read aloud: Piper speaks on its own server, and ffmpeg shrinks it to AAC, a seventh of the size."""
import hashlib
import json
import os
import re
import subprocess
import threading
import urllib.request

SERVER = os.environ.get("EMBER_TTS", "")  # empty: off
LONGEST = 4000  # characters read aloud, about four minutes
KEPT = 50  # recordings kept; an older one is spoken again if asked for
lock = threading.Lock()


def spoken(title, body):
    """The note as it's read: links by their words, no pictures or recordings, each line a sentence of its own,
    and a line said once: a saved story's title is its link's words too."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)|\[voice\]\([^)]*\)", "", body)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    lines = [re.sub(r"^\s*- (\[[ x]\] )?|\*\*", "", line).strip() for line in f"{title}\n{text}".split("\n")]
    return "\n".join(line if line[-1] in ".!?:;" else f"{line}." for line in dict.fromkeys(lines) if line)[:LONGEST]


def say(text, folder):
    """The recording of a text, made once: the same note asked for again is played straight away."""
    path = folder / f"{hashlib.sha1(text.encode()).hexdigest()[:16]}.m4a"
    with lock:  # one at a time: the iPhone asks twice for the same recording
        if not path.exists():
            request = urllib.request.Request(f"{SERVER}/synthesize", json.dumps({"text": text}).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=300) as r:
                wav = r.read()
            folder.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", "-", "-c:a", "aac", "-b:a", "48k", str(path)], input=wav, check=True)
            for old in sorted(folder.glob("*.m4a"), key=lambda p: p.stat().st_mtime)[:-KEPT]:
                old.unlink()
    return path
