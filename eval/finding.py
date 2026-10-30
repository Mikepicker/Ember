"""How well a question finds the notes that answer it: the rank of the first right note among the 80 eval notes,
by shared rarer words (ask.pick), by an embedding model, and by both.

    EVAL_EMBED="gemma=http://127.0.0.1:8095" python3 eval/finding.py

Each EVAL_EMBED entry, separated by ";", is name=server[=query prefix[=note prefix]], a llama.cpp server started with --embedding.
"""
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "server"))
import ask  # noqa: E402

texts = json.loads((HERE / "notes.json").read_text()) + json.loads((HERE / "holdout.json").read_text())
notes = [{"id": str(i), "created": "2026-10-01T09:00", "path": f"{n['area']}/{i}.md", "title": "", "body": n["text"]} for i, n in enumerate(texts)]
questions = json.loads((HERE / "questions.json").read_text())


def embed(server, inputs):
    req = urllib.request.Request(f"{server}/v1/embeddings", json.dumps({"input": inputs}).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        vectors = [d["embedding"] for d in sorted(json.load(r)["data"], key=lambda d: d["index"])]
    return [[x / (math.sqrt(sum(x * x for x in v)) or 1) for x in v] for v in vectors]


def by_words(q):
    picked = ask.pick(q, notes)  # what ask sent before meaning, best first, within its budget
    return [n["id"] for n in picked]


def fuse(*rankings):
    """Reciprocal rank fusion: a note high in either ranking comes high."""
    score = {}
    for ranking in rankings:
        for r, nid in enumerate(ranking):
            score[nid] = score.get(nid, 0) + 1 / (10 + r)
    return sorted(score, key=score.get, reverse=True)


def report(name, rankings):
    firsts = [next((r for r, nid in enumerate(ranking) if int(nid) in q["notes"]), None) for ranking, q in zip(rankings, questions)]
    at = lambda k: sum(1 for f in firsts if f is not None and f < k)
    mrr = sum(1 / (f + 1) for f in firsts if f is not None) / len(questions)
    print(f"{name:22} {at(1):>3} {at(3):>3} {at(5):>3} {mrr:6.2f}   missed: {[q['q'][:28] for f, q in zip(firsts, questions) if f is None or f >= 5][:6]}")


print(f"{'':22} {'@1':>3} {'@3':>3} {'@5':>3} {'MRR':>6}   (of {len(questions)} questions)")
words = [by_words(q["q"]) for q in questions]
report("shared words", words)
for spec in filter(None, os.environ.get("EVAL_EMBED", "").split(";")):
    name, server, query, note = (spec.split("=", 3) + ["", ""])[:4]
    vectors = embed(server, [note + ask.gist(n) for n in notes])
    asked = embed(server, [query + q["q"] for q in questions])
    meaning = [[notes[i]["id"] for i in sorted(range(len(notes)), key=lambda i: -sum(a * b for a, b in zip(v, vectors[i])))] for v in asked]
    report(name, meaning)
    report(f"{name} + words", [fuse(m, w) for m, w in zip(meaning, words)])
