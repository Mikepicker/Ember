"""What a text means, as a vector, so a question finds the notes that answer it in other words: "what do I need for the hike?"
finds "pack list for the mountains". EmbeddingGemma-300M, on its own llama.cpp server, put the right note first for 30
of the eval's 32 questions; going by shared words, for 8."""
import array
import base64
import hashlib
import json
import os
import threading
import urllib.request
from operator import mul

SERVER = os.environ.get("EMBER_EMBED", "")  # empty: off, and ask goes by shared words
QUERY, TEXT = "task: search result | query: ", "title: none | text: "  # the prompts EmbeddingGemma was trained with:
# a text to be found starts "title: … | text: ", a question "task: search result | query: "
LONGEST = 2000  # characters of a text that are read, about 500 tokens


def embed(texts):
    req = urllib.request.Request(f"{SERVER}/v1/embeddings", json.dumps({"input": texts}).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        found = [array.array("f", d["embedding"]) for d in sorted(json.load(r)["data"], key=lambda d: d["index"])]
    return [array.array("f", (x / (sum(map(mul, v, v)) ** 0.5 or 1) for x in v)) for v in found]


def similar(a, b):
    return sum(map(mul, a, b))


def query(text):
    return embed([QUERY + text[:LONGEST]])[0]


class Vectors:
    """The vectors of the texts last asked about, by a hash of each text; with a file, kept across restarts,
    so the notes aren't all read again."""

    def __init__(self, path=None):
        self.path, self.lock = path, threading.Lock()
        saved = json.loads(path.read_text()) if path and path.exists() else {}
        self.known = {k: array.array("f", base64.b64decode(v)) for k, v in saved.items()}

    def of(self, texts):
        keys = [hashlib.sha1(t[:LONGEST].encode()).hexdigest()[:16] for t in texts]
        with self.lock:
            new = {k: t[:LONGEST] for k, t in zip(keys, texts) if k not in self.known}
            for start in range(0, len(new), 16):
                batch = list(new)[start : start + 16]
                self.known.update(zip(batch, embed([new[k] for k in batch])))
            gone = set(self.known) - set(keys)
            for k in gone:
                del self.known[k]
            if self.path and (new or gone):
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps({k: base64.b64encode(v.tobytes()).decode() for k, v in self.known.items()}))
                tmp.replace(self.path)
            return [self.known[k] for k in keys]
