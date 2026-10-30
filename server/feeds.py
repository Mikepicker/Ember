"""News to read: the newest stories of the feeds in the list. The Pi fetches them, since the phone can't read other sites' feeds,
and makes their thumbnails, so the phone loads 10 KB from the Pi rather than a large picture from each site."""

import email.utils
import gzip
import hashlib
import html
import json
import re
import subprocess
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlencode, urljoin

# the feeds to read, until the list is changed in the app: one per line, "name: link to its feed"
FEEDS = """simon willison: https://simonwillison.net/atom/entries/
hugging face: https://huggingface.co/blog/feed.xml
openai: https://openai.com/news/rss.xml
deepmind: https://deepmind.google/blog/rss.xml
interconnects: https://www.interconnects.ai/feed
import ai: https://importai.substack.com/feed
localllama: https://www.reddit.com/r/LocalLLaMA/top/.rss?t=week
hacker news: https://hnrss.org/frontpage?points=300
lwn: https://lwn.net/headlines/rss
github: https://github.blog/open-source/feed/
it's foss: https://itsfoss.com/rss/
selfh.st: https://selfh.st/rss/
raspberry pi: https://www.raspberrypi.com/news/feed/"""

UA = {"User-Agent": "Mozilla/5.0 (ember)"}
SQUARE = "scale=168:168:force_original_aspect_ratio=increase,crop=168:168"  # a 56-point square on the iPhone's screen
EACH = 5  # the newest stories of each feed, so a busy one doesn't drown the rest
FRESH = 1800  # seconds before the feeds are fetched again; Reddit refuses a second fetch within minutes
lock = threading.Lock()
fetched = {}  # the list -> when its feeds were last fetched
known = {}  # a feed's link -> its stories when it was last read, kept while it can't be read
tried = set()  # stories whose thumbnail was tried, so a page without a picture isn't fetched every half hour
heat = {}  # a story's link -> its points on Hacker News, looked up after each fetch


def sources(text):
    """The feeds in the list, {link: name}; a line without a name is named by its feed."""
    return {m[2]: m[1].strip(" -:") for m in re.finditer(r"(?m)^(.*?)(https?://\S+)", text)}


def epoch(text):
    try:
        return email.utils.parsedate_to_datetime(text).timestamp()  # RSS: "Tue, 28 Oct 2026 10:00:00 GMT"
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(text.strip()).timestamp()  # Atom: "2026-10-28T10:00:00Z"
        except (AttributeError, ValueError):
            return 0


def picture(item, link):
    """The story's own picture, if its feed gives one: a thumbnail, an attached image, or the first one in the post."""
    for el in item.iter():
        url = el.get("url", "")
        image = el.get("medium") == "image" or el.get("type", "").startswith("image/") or re.search(r"\.(jpe?g|png|webp|gif)\b", url, re.I)
        if url and (el.tag == "thumbnail" or el.tag in ("content", "enclosure") and image):
            return urljoin(link, url)
    found = re.search(r"<img[^>]+src=[\"']([^\"']+)", " ".join(el.text or "" for el in item.iter()))
    return urljoin(link, html.unescape(found[1])) if found else ""


def fetch(link, most):
    """A feed, page or picture; a site may gzip it unasked, as DeepMind's feed does every other time."""
    with urllib.request.urlopen(urllib.request.Request(link, headers=UA), timeout=15) as r:
        data = r.read(most)
        return gzip.decompress(data) if r.headers.get("Content-Encoding") == "gzip" else data


def stories(link, name):
    root = ET.fromstring(fetch(link, 5_000_000))
    for el in root.iter():
        el.tag = el.tag.rsplit("}", 1)[-1]  # RSS and Atom alike, without their namespaces
    name = name or root.findtext(".//title", "").strip()
    found = []
    for item in [*root.iter("item"), *root.iter("entry")]:
        title = html.unescape(re.sub(r"<[^>]+>", "", item.findtext("title", ""))).strip()
        href = item.findtext("link", "").strip() or next((l.get("href") for l in item.iter("link") if l.get("rel", "alternate") == "alternate"), "")
        dates = [item.findtext(tag) for tag in ("pubDate", "published", "updated", "date")]
        if href.startswith(("http://", "https://")):  # never a "javascript:" link
            found.append({"title": title, "link": href, "source": name, "at": epoch(next(filter(None, dates), "")), "image": picture(item, href)})
    return sorted(found, key=lambda s: -s["at"])[:EACH]


def page_picture(link):
    """The picture a page shows when it's shared, its og:image."""
    page = fetch(link, 500_000).decode("utf-8", "replace")
    tag = re.search(r"<meta[^>]+(?:property|name)=[\"'](?:og|twitter):image[\"'][^>]*>", page, re.I)
    found = tag and re.search(r"content=[\"']([^\"']+)", tag[0])
    return urljoin(link, html.unescape(found[1])) if found else ""


def shrink(image, path, scale=SQUARE):
    """A small copy of a picture: a square for the list, or wider for a saved story."""
    jpeg = subprocess.run(["ffmpeg", "-v", "error", "-i", "-", "-vf", scale, "-frames:v", "1", "-pix_fmt", "yuvj420p", "-q:v", "5", "-f", "image2", "-c:v", "mjpeg", "-"],
                          input=fetch(image, 10_000_000), capture_output=True, check=True).stdout
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(jpeg)


def picture_of(link):
    """The picture a story had under read, or else its page's own."""
    return next((s["image"] for got in known.values() for s in got or [] if s["link"] == link and s["image"]), "") or page_picture(link)


def thumb(link):
    return hashlib.sha1(link.encode()).hexdigest()[:16] + ".jpg"


def thumbnails(found, folder):
    """Makes the missing thumbnails, from the feed's picture or else the page's, and drops those no longer listed."""
    def make(s):
        tried.add(s["link"])
        try:
            shrink(s["image"] or page_picture(s["link"]), folder / thumb(s["link"]))
        except Exception:
            pass  # LWN and Reddit's text posts have no picture; OpenAI won't give its pages to a script
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(make, [s for s in found if s["link"] not in tried and not (folder / thumb(s["link"])).exists()]))
    listed = {thumb(s["link"]) for s in found}
    for f in folder.glob("*.jpg"):
        if f.name not in listed:
            f.unlink()


def same(a, b):
    """One story told twice: "Gemini 4 Carbon" on Hacker News is "Gemini 4 Carbon: Our next frontier model" on DeepMind's blog."""
    a, b = (re.findall(r"\w+", t.lower()) for t in (a, b))
    return min(len(a), len(b)) >= 3 and a[: len(b)] == b[: len(a)]


def search(**query):
    with urllib.request.urlopen("https://hn.algolia.com/api/v1/search?" + urlencode({"tags": "story", **query}), timeout=15) as r:
        return json.load(r)["hits"]


def points(story):
    """The story's points on Hacker News, the crowd's say on how big it is: shared by its link, or else in the last week
    under the same title, as "Gemini 4 Carbon" was shared from Google's blog rather than DeepMind's. A title is looked
    up by its first three words, as "same" asks for: Hacker News's is often the shorter one."""
    bare = lambda link: re.sub(r"^https?://(www\.)?|/$", "", (link or "").split("#")[0])
    found = [h["points"] or 0 for h in search(query=story["link"], restrictSearchableAttributes="url") if bare(h["url"]) == bare(story["link"])]
    if not found:
        week = f"created_at_i>{int(time.time()) - 7 * 86400}"
        start = " ".join(re.findall(r"\w+", story["title"])[:3])
        found = [h["points"] or 0 for h in search(query=start, numericFilters=week) if same(h["title"], story["title"])]
    return max(found, default=0)


def heats(every):
    """Looks up how hot each story is, for the next look: its points grow while it's being talked about."""
    def get(s):
        try:
            return points(s)
        except Exception:
            return heat.get(s["link"], 0)
    with ThreadPoolExecutor(8) as pool:
        got = dict(zip((s["link"] for s in every), pool.map(get, every)))
    heat.update(got)
    for link in set(heat) - set(got):
        del heat[link]


def latest(text, folder, wait=FRESH):
    """The newest stories first, and the feeds that have never been read. The feeds are fetched again once the last
    fetch is `wait` seconds old: half an hour, or a minute when the list is pulled down, as Reddit allows one a minute.
    Thumbnails are made in `folder` after each fetch, and points looked up, and show from the next look on."""
    feeds = sources(text)
    fresh = False
    with lock:  # one fetch at a time: a second phone waits for the first one's stories
        if time.time() - fetched.get(text, 0) > wait:
            def get(feed):
                try:
                    return stories(*feed)
                except Exception as e:
                    print(f"feed {feed[0]} failed: {e!r}", flush=True)
            with ThreadPoolExecutor(8) as pool:
                for link, got in zip(feeds, pool.map(get, feeds.items())):
                    known[link] = got if got is not None else known.get(link)
            fetched.clear()
            fetched[text] = time.time()
            fresh = True
    every = sorted((s for link in feeds for s in known.get(link) or []), key=lambda s: -s["at"])
    found = []
    for s in every:  # a story told twice shows once, as hot as its hottest telling
        twin = next((t for t in found if same(s["title"], t["title"])), None)
        if twin:
            twin["heat"] = max(twin["heat"], heat.get(s["link"], 0))
        else:
            found.append({**s, "heat": heat.get(s["link"], 0)})
    if fresh:
        threading.Thread(target=thumbnails, args=(found, folder), daemon=True).start()
        threading.Thread(target=heats, args=(every,), daemon=True).start()
    shown = [{**s, "thumb": (folder / thumb(s["link"])).exists() and thumb(s["link"])} for s in found]
    return shown, [name or link for link, name in feeds.items() if known.get(link) is None]
