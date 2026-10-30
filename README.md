# ember

Fire-and-forget notes. Write, snap or speak on the phone; a Raspberry Pi tidies each note into Markdown, files it, and puts its dated tasks into the iPhone's Reminders and Calendar. It answers questions from the notes, reads them aloud, and keeps a list of news to read.

- `web/` — the app: plain HTML, CSS and JavaScript, works offline, no build step.
- `server/` — Python standard library only: serves the app, stores notes as Markdown files, tidies them in the background, fetches the feeds to read.
- Notes live in `data/notes/` as plain `.md` files. They are the only source of truth.

Each file does one thing:

| `server/` | |
|---|---|
| `app.py` | the HTTP routes, and start-up |
| `store.py` | the notes as Markdown files, found by id |
| `notes.py` | what happens to a note: captured, tidied and filed in the background, edited, moved, put in the trash, its reminders kept in sync |
| `tidy.py` | a new note made tidy: shorthand, the 2B's layout, the moment each task is due; a shared link becomes its page |
| `tasks.py` | task lines, and when each is due |
| `reminders.py` | the calendar the iPhone's Reminders and Calendar read |
| `filing.py` | which folder a new note goes into |
| `media.py` | recordings heard and photos read |
| `model.py` | the local models |
| `ask.py` | answers from the notes |
| `related.py` | what's close in meaning: the notes a question goes with, related notes, stories for you |
| `meaning.py` | EmbeddingGemma's vectors, kept |
| `feeds.py` | the stories under read |
| `speech.py` | notes read aloud |

| `web/` | |
|---|---|
| `app.js` | picks the page and starts everything |
| `core.js` | the state, kept offline in IndexedDB and synced with the Pi |
| `text.js` | notes shown as HTML |
| `write.js`, `ask.js`, `list.js`, `note.js`, `read.js` | one per page |
| `sound.js` | key clicks and the bell |
| `sw.js` | the offline copy of the app |

The AI and calendar pieces are separate servers that Ember talks to over HTTP:

| Server | Does | Run locally |
|---|---|---|
| llama.cpp, Qwen3.5-2B | cleans up notes, picks folders | `llama-server -m models/Qwen3.5-2B-Q4_K_M.gguf --jinja -c 4096 -np 1 --port 8091` |
| llama.cpp, Qwen3.5-0.8B | reads photos | `llama-server -hf unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M --jinja -c 4096 -np 1 --port 8100` |
| whisper.cpp | turns recordings into text | `whisper-server -m models/ggml-base.en.bin --port 8092` |
| llama.cpp, EmbeddingGemma-300M | what notes and stories mean: for ask, related notes, stories for you | `llama-server -hf ggml-org/embeddinggemma-300M-GGUF:Q8_0 --embedding -c 2048 -b 2048 -ub 2048 --port 8095` |
| Piper | reads notes aloud | `.venv-tts/bin/python -m piper.http_server -m models/piper/en_US-lessac-medium.onnx --port 8098` |
| Radicale | CalDAV server the iPhone's Reminders and Calendar sync with | `.venv/bin/radicale --server-hosts 127.0.0.1:5232 --auth-type none --storage-filesystem-folder data/calendar` |

`.venv-tts` is a Python 3.13 venv with `piper-tts[http]`, as onnxruntime has no build for 3.15 yet; `python -m piper.download_voices en_US-lessac-medium --download-dir models/piper` fetches the voice.
Then start Ember with `python3 server/app.py` and the settings below, and open http://127.0.0.1:8787.

| Variable | Default | |
|---|---|---|
| `EMBER_NOTES` | `data/notes` | where notes are stored |
| `EMBER_LLM` | `http://127.0.0.1:8080` | llama.cpp server for text |
| `EMBER_VISION` | same as `EMBER_LLM` | llama.cpp server for photos |
| `EMBER_WHISPER` | `http://127.0.0.1:8081` | whisper.cpp server |
| `EMBER_EMBED` | empty (ask goes by shared words) | llama.cpp server for meaning, started with `--embedding` |
| `EMBER_TTS` | empty (listen off) | Piper's server |
| `EMBER_CALDAV` | empty (reminders off) | the calendar, e.g. `http://127.0.0.1:5232/ember/notes/` |
| `EMBER_CALDAV_LOGIN` | empty | `user:password` for the calendar |
| `EMBER_URL` | `http://127.0.0.1:8787` | address used in links from reminders back to notes |
| `EMBER_HOST`, `EMBER_PORT` | `127.0.0.1`, `8787` | where the app is served |

Shorthand expansions live in `server/shorthand.txt`. The font is Courier Prime (SIL Open Font License).

## Folders

New notes are filed into the folders in a list you edit in the app (notes › folders › edit), kept in `data/notes/_folders.md`: one per line, `name: what goes in it`. A line `work/novax: …` makes a folder inside work. The list starts with twelve areas of life.
The 2B picks one folder from the list, guided by each line, so name the people and projects that belong there. A note naming people or projects whose notes are all in one folder goes there instead. Any note can be moved to another folder in the list with **move**.

## Tasks and reminders

The 2B writes each thing to do as a `- [ ] ` line. A task that names a day or a time gets a moment, worked out once by rules rather than the model and kept with the note by a short hash of its text: `due: 3fa2c1=2026-10-31 8b11e0=2026-10-31T15:00`. Meetings, dinners and appointments go to Calendar as events, everything else to Reminders, one file per task, `<note id>-<task key>.ics`. A task ticked on either side is ticked on the other.

- Words like "tomorrow" or "Friday" count from the writer's day, which starts at 4 am: "tomorrow" written at 00:30 is the coming day.
- A heading that names a day, "Tomorrow:" or "Friday" over a list, makes every line under it a task for that day, unless the line names its own. So does a last line after a list that says only when, like "Reminders for today at 2pm"; "Good day today" says more, and dates nothing.
- "At 4" with no am or pm is in the afternoon, and so is "dinner at 8". A day without a time is due at 9; a task for today written after 9 is due two hours later, never at night. "Before Friday" is Thursday.
- A month alone is a deadline only after "before" or "by": "renew the passport before March" is due on 28 February, "rent a car for August" isn't due at all.
- A line typed into a note later that names a day becomes a task too, counting from when it was typed.

## Read

The read tab lists the newest stories of the feeds in another list edited in the app (read › feeds › edit), kept in `data/notes/_feeds.md`: one per line, `name: link to its feed`; a line with only a link is named by its feed. It starts with thirteen feeds on AI, local models and open source.
The Pi fetches them at most every half hour, the five newest of each, and drops a story told twice, like "Gemini 4 Carbon" on Hacker News and on DeepMind's blog. A tap opens the story in Safari. A feed that can't be read keeps its last stories; one never read is named under the list.
Pulling the list down from the top fetches the feeds again, unless the last fetch was under a minute ago, as Reddit allows one a minute; the ember glows meanwhile.
Thumbnails come from the feed's own picture (37 of 65 stories), or else the page's og:image (16 more); LWN, Reddit's text posts and OpenAI, which won't give its pages to a script, have none. The Pi crops them to 168 px squares with ffmpeg, 2-10 KB each, in `data/notes/_files/thumbs/`, so the phone loads them from the Pi, not from each site; they're made in the background after a fetch, about two minutes for the first 50, and deleted when their story drops off the list.
**☆ save** turns a story into a note in `saved/`, made like a shared link without the 2B: the feed's title, the link, the page's own description, and its picture 800 px wide. Search and ask find it by those words, not the article's text. `saved` isn't in the folders list, so the 2B never files notes there; tapping **★ saved** moves the note to the trash.
A flame marks a trending story, one with 500 points or more on Hacker News, the day's biggest stories there, with its points: **🔥 1.2k**. After each fetch the Pi looks every story up on Hacker News's search (hn.algolia.com), by its link, or else by a story in the last week with the same title, as "Gemini 4 Carbon" was shared from Google's blog rather than DeepMind's. A story on no other site, like Reddit's, has no points, so it shows no flame.
Reddit answers about one feed request a minute from an address, so testing feeds from a Mac on the same connection can leave the Pi without r/LocalLLaMA until its next fetch.
Once a story is saved, the stories closest to the saved ones in meaning come first, under **for you**: up to five, at 0.27 or more, where a typical story scores 0.17 and the Google stories next to a saved "Gemini 4 Carbon" 0.28-0.33. A saved story is compared by its title and description, each new story by its title: by titles alone, "Gemini 4 Carbon" is as close to "CNC Stone Carving" as to "Genie 4".

## Related notes and listening

Under each note, up to three notes close to it in meaning, at 0.45 or more: a client's notes are 0.55-0.62 to each other, a dog photo to a cat photo 0.49, notes on different things under 0.43. The meanings of the notes are kept in `data/notes/_meaning.json`, so a restart doesn't read them all again.
**listen** under a note's title has the Pi read it aloud: tasks, links and lines become sentences, pictures and recordings are left out. Piper's `en_US-lessac-medium` voice speaks it, ffmpeg makes it AAC, a seventh of the size, and the last 50 are kept in `data/notes/_files/speech/`, so a note heard again plays at once. Whisper transcribed a Piper recording back word for word.

## iPhone shortcuts

Capture without opening the app: Shortcuts post to `https://<pi>.<tailnet>.ts.net/api/quick` (needs Tailscale on).
It takes JSON `{"text": "…"}`, plain text, or a JPEG/PNG photo; a bare link becomes a note with the page's title and picture.

| Shortcut | Actions | Use it from |
|---|---|---|
| **Ember** | Dictate Text (language English, stop after pause) → Get Contents of URL (POST, JSON, `text` = Dictated Text) → Show Notification | "Hey Siri, Ember", the Action Button, Control Center, Back Tap |
| **Send to Ember** | receives Text and URLs, shown in the share sheet → Get Contents of URL (POST, JSON, `text` = Shortcut Input) → Show Notification | the share sheet of any app |
| **Photo to Ember** | receives Images, shown in the share sheet → Convert Image to JPEG → Get Contents of URL (POST, File = Converted Image) → Show Notification | the share sheet of Photos, Camera, screenshots |

HEIC photos are refused, because this ffmpeg reads only the first tile of them; the photo shortcut converts to JPEG first.

## On the Pi

`compose.yml` runs the servers in `~/ember`, on cores 2-3 at low priority, listening on 127.0.0.1 only.
Tailscale Serve adds HTTPS for the tailnet: the app on `https://<pi>.<tailnet>.ts.net`, the calendar on port 5232.
`~/ember/.env` holds `EMBER_URL` and `CALDAV_PASSWORD`; `data/radicale.users` holds the bcrypt hash of that password.

Update the code (server and app are mounted into the container):

```sh
rsync -a compose.yml server web pi@raspberrypi.local:ember/
ssh pi@raspberrypi.local 'cd ember && docker compose restart ember'
```

Rebuild the images on the Mac (same ARM architecture) and load them on the Pi:

```sh
docker buildx build --platform linux/arm64 -t ember --load .
docker buildx build --platform linux/arm64 -f deploy/whisper.Dockerfile -t ember-whisper --load .
docker save ember ember-whisper | gzip -1 | ssh pi@raspberrypi.local 'gunzip | docker load'
```

Piper's image is only Python and prebuilt packages, so the Pi builds it itself:

```sh
rsync -a deploy pi@raspberrypi.local:ember/
ssh pi@raspberrypi.local 'cd ember && docker build -t ember-piper - < deploy/piper.Dockerfile'
```

Models live in `~/ember/models`: `Qwen3.5-2B-Q4_K_M.gguf` from `unsloth/Qwen3.5-2B-GGUF`; `Qwen3.5-0.8B-Q4_K_M.gguf` and `mmproj-F16.gguf` from `unsloth/Qwen3.5-0.8B-GGUF`; `ggml-base.en.bin` from `ggerganov/whisper.cpp`; `embeddinggemma-300M-Q8_0.gguf` from `ggml-org/embeddinggemma-300M-GGUF`; `piper/en_US-lessac-medium.onnx` and its `.onnx.json` from `rhasspy/piper-voices`.
Never use BF16 model files on the Pi: its CPU has no fast path for them.

## How well does it work?

`eval/` holds 80 labelled notes (50 for tuning, 30 written before any results) and a script where each model tidies and files every note, replayed in arrival order:

```sh
EVAL_MODELS="2B=http://127.0.0.1:8091" python3 eval/folders.py eval/notes.json eval/holdout.json
```

Measured 28 Oct 2026, areas right out of 80 (with area descriptions and the names rule), and seconds per typed note on the Pi once warm:

| Model | Areas right | Clean-ups kept | Pi |
|---|---|---|---|
| Phi-4 Mini (3.8B) | 74 | 75 | 21.0 s, 5.2 GB |
| Qwen3.5-2B | 73 | 77 | 12.5 s, 2.9 GB |
| Gemma 4 E2B | 71 | 75 | 19.0 s, 4.6 GB |
| MiniCPM5-2B | 66 | 71 | 12.8 s |
| Gemma 4 E4B | 63 | 77 | 182 s, 6.0 GB (too big to run beside the other services) |
| LFM2.5-1.2B | 55 | 73 | 14.6 s (its prompt can't be cached) |
| MiniCPM5-1B | 54 | 63 | 5.6 s |
| K2-Horizon-0.9B (Q8_0) | 52 | 70 | 9.4 s, 2.3 GB |
| Qwen3.5-0.8B | 50 | 75 | 6.5 s |
| Spark-X2.5-1.7B | 47 | 73 | 10.4 s, 2.5 GB |

Photos: Qwen3.5-0.8B at 896 px read a receipt, a whiteboard and an invoice completely, in 31-59 s on the Pi; Qwen3.5-2B took 154 s for the receipt and missed figures on the invoice. Xiaomi-OCR-0 did worst with this prompt. Gemma 4 E2B read every word but listed prices apart from their items, and took 53-98 s.
A photo is first asked what it shows, in a sentence, and whether it has any words; only then is its text copied out, cut off at 1,000 tokens. Asked to copy out a photo with no words, the 0.8B makes text up, on and on: a dog photo ran for 5 minutes. A photo sent on its own is named from that sentence.
A photo with no words also gets the plain word for what it shows as a tag: the 2B won't take "a yellow Labrador" as an answer to "what did I write about the dog?", even after writing that a Labrador is a dog. The word is a third field in the same answer, named `subject_in_one_plain_everyday_word`; asked as a second question, it cost another minute on the Pi, where the photo is read again each time.
A note that fails to be tidied is tried again every 5 minutes.
A note already written as a list keeps its layout, unless the 2B's version has the same indentation and blank lines: it nested a whole list under the first line, more so when told not to. A short first line with a blank line after it becomes the title.

`eval/tidying.json` holds 100 notes, the 80 above and 20 with headings, lists, a line saying when and late-night times, each with the reminders it should make, written on a Tuesday at 18:00 unless it says otherwise:

```sh
EMBER_LLM=http://127.0.0.1:8091 python3 eval/tidying.py
```

Measured 30 Oct 2026, reminders right in 95 of 100 notes and clean-ups kept in 96, against 87 and 95 of the first 98 before the heading rule, the writer's day and the evening hours. The 2B now sees the heading too: it used to be cut off as the title first. Asked for the note as a JSON list of points rather than Markdown, the 2B kept the thing to do and moved its context into the title, "Bring a bottle" without "Paolo's birthday party on Saturday", so only 89 clean-ups were kept; shown an example of a heading over a list of tasks, it shortened other notes as well, and once wrote release notes of its own. So the heading rule is code. Still missed: a second task nested as a detail of the first, and a second heading partway down a note.
Filing by embedding similarity (bge-small) was tried and dropped: a note's nearest neighbour was in the right area only half the time.
The 2B is still asked for a topic after the folder, though it isn't used: without it, 70 of 80 areas were right, and asked for a "folder" rather than an "area of life", 66. Words in capitals, like AI or TV, don't count as names: a note saying "AI" was sent to the only other note saying it, a course.

Asking: the 2B reads only about 24 tokens a second on the Pi, so a question goes with the few notes closest to it in meaning, never all of them: those within 0.1 of the closest, 2.8 on average in the eval. None go when even the closest scores under 0.3: in the eval every question's closest scores 0.34 or more, and the closest to "what day is it today?" or "who won the match?" 0.11-0.29. Sent a note anyway, the 2B cited it for an answer it took from the date in its prompt, which now has the time too; a number with no note behind it isn't shown. Until 29 Oct 2026 it went with the notes sharing the question's rarer words, which missed "what do I need for the hike?" for a note saying "pack list for the mountains"; it still does while the meaning server is off. First words come after 4-12 s, whole answers in 7-19 s.
`eval/questions.json` asks 32 questions of the 80 eval notes, most in words the notes don't use; the rank of the first right note, by each way of finding them, measured 29 Oct 2026:

```sh
EVAL_EMBED="gemma=http://127.0.0.1:8095=task: search result | query: =title: none | text: " python3 eval/finding.py
```

| Finding notes by | 1st | in the top 3 | in the top 5 |
|---|---|---|---|
| shared rarer words | 8 | 14 | 15 |
| bge-small-en-v1.5 (33M) | 24 | 28 | 29 |
| nomic-embed-text-v1.5 (137M) | 26 | 30 | 30 |
| Qwen3-Embedding-0.6B | 29 | 32 | 32 |
| EmbeddingGemma-300M (300M, used) | 30 | 31 | 31 |

Adding the shared words to the meaning made every model worse: notes sharing one word tie, in no useful order.
Questions about the diary ("what do I have today?", "anything due this week?") skip the model: asked to list a day's tasks, it left some out, so Ember lists them itself from the reminders' dates, instantly.
