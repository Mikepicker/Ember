"""Recordings and photos made into text: whisper.cpp hears recordings, the 0.8B reads photos."""
import base64
import json
import os
import re
import subprocess
import urllib.request

import model

WHISPER = os.environ.get("EMBER_WHISPER", "http://127.0.0.1:8081")
AUDIO = {".webm", ".m4a", ".mp4", ".ogg", ".wav", ".mp3", ".aac"}
LONGEST = 10 * 60  # seconds; longer recordings are kept but not transcribed
# the last field's name is its question: answered after the sentence, it leaves the sentence as it was, and asking it
# on its own would cost a minute on the Pi, as the photo is read again
WORD = "subject_in_one_plain_everyday_word"
LOOK = {"type": "object", "properties": {"shows": {"type": "string"}, "text": {"type": "boolean"}, WORD: {"type": "string", "pattern": "^[a-z]{1,20}$"}},
        "required": ["shows", "text", WORD]}


def ffmpeg(path, *args):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), *args, "-"], capture_output=True, check=True).stdout


def remux(path):
    """Rewrites a recording with its length and seek points, which browser recorders leave out."""
    tmp = path.with_name(f"remux-{path.name}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-c", "copy", str(tmp)], check=True)
    tmp.replace(path)


def transcribe(path):
    wav = ffmpeg(path, "-ar", "16000", "-ac", "1", "-f", "wav")  # 32,000 bytes per second
    if len(wav) / 32000 > LONGEST:
        return f"(Recording of {len(wav) // 32000 // 60} minutes, not transcribed.)"
    form = b'--ember\r\nContent-Disposition: form-data; name="file"; filename="memo.wav"\r\n\r\n' + wav + b"\r\n--ember--\r\n"
    req = urllib.request.Request(f"{WHISPER}/inference", form, {"Content-Type": "multipart/form-data; boundary=ember"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return " ".join(re.sub(r"\[[A-Z_ ]+\]", "", json.load(r)["text"]).split())  # drops markers like [BLANK_AUDIO]


def read(path):
    """What a photo shows and any text in it; and for a photo without words, the plain word for it, as a tag:
    the 2B won't take "a yellow Labrador" as an answer to "what did I write about the dog?"."""
    # 896 px wide is about 1,000 image tokens: as accurate as 1280 px on receipts, whiteboards and printed pages, 2-4x faster
    jpeg = ffmpeg(path, "-vf", "scale='min(896,iw)':-2", "-f", "image2", "-c:v", "mjpeg")
    image = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}}
    look = lambda question, **kw: model.ask([{"role": "user", "content": [image, {"type": "text", "text": question}]}], server=model.VISION, **kw)
    # asked to copy out a photo with no words in it, the 0.8B makes some up, on and on; so it's asked first whether there are any
    seen = look("Say what this photo shows in one short sentence, and whether it has any written or printed words in it.", schema=LOOK)
    if not seen["text"]:
        return seen["shows"], seen[WORD]
    try:
        return f"{seen['shows']}\n\n{look('Write out all the text in this photo exactly, line by line.', limit=1000)}", ""
    except ValueError:  # cut off: it was making text up, or there's more than it can copy
        return seen["shows"], ""
