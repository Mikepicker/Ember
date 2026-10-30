"""What's close in meaning: the notes a question goes with, the notes shown under a note, and the stories for you
under read. Each finds nothing while the meaning server is off or down."""
import functools
import re

import ask
import meaning
import store

RELATED = 0.45  # how close another note must be to show under a note: a client's notes are 0.55-0.62 to each other,
# a dog photo to a cat photo 0.49, notes on different things under 0.43
FOR_YOU = 0.27  # how close a story must be to one saved to show first: Genie 4 and Gemma 5 are 0.28-0.33 to Gemini 4 Carbon,
# nine stories in ten under 0.23
vectors = meaning.Vectors(store.NOTES / "_meaning.json")  # the notes' meanings, kept so a restart doesn't read them all again
told = meaning.Vectors()  # the stories' meanings, and those of the ones saved


def quietly(job):
    @functools.wraps(job)
    def run(*args):
        try:
            return job(*args) if meaning.SERVER else []
        except OSError as e:
            print(f"{job.__name__} failed: {e!r}", flush=True)
            return []
    return run


@quietly
def meanings():
    """Every note shown, with its meaning."""
    notes = store.shown()
    return list(zip(notes, vectors.of([meaning.TEXT + ask.gist(n) for n in notes])))


@quietly
def near(nid, most=3):
    """The notes closest in meaning to a note, if close enough."""
    notes = meanings()
    mine = next((v for n, v in notes if n["id"] == nid), None)
    close = sorted(((meaning.similar(mine, v), n["id"]) for n, v in notes if n["id"] != nid), reverse=True) if mine else []
    return [other for score, other in close[:most] if score >= RELATED]


@quietly
def for_you(stories, most=5):
    """The links of the stories closest in meaning to those saved, best first, leaving out the saved ones.
    A saved story is read with its description, which tells its subject better than its title: "Gemini 4 Carbon" is
    as close to "CNC Stone Carving" as to "Genie 4" by title alone."""
    saved = [n for n in store.shown() if n["path"].startswith("saved/")]
    if not saved:
        return []
    about = lambda n: re.sub(r"!?\[[^\]]*\]\([^)]*\)", "", n["body"]).strip() or "none"  # the description, without link and picture
    found = told.of([f"title: {s['title']} | text: none" for s in stories] + [f"title: {n.get('title')} | text: {about(n)}" for n in saved])
    close = [(max(meaning.similar(v, m) for m in found[len(stories):]), s["link"]) for s, v in zip(stories, found)
             if not any(f"]({s['link']})" in n["body"] for n in saved)]
    return [link for score, link in sorted(close, reverse=True)[:most] if score >= FOR_YOU]
