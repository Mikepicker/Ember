# ember

Fire-and-forget notes. Write, snap or speak on the phone; a Raspberry Pi tidies each note into Markdown, files it, and puts its dated tasks into the iPhone's Reminders and Calendar.

- `web/` — the app: plain HTML, CSS and JavaScript, works offline, no build step.
- `server/` — Python standard library only: serves the app, stores notes as Markdown files, tidies them in the background.
- Notes live in `data/notes/` as plain `.md` files. They are the only source of truth.

The AI and calendar pieces are separate servers that Ember talks to over HTTP:

| Server | Does | Run locally |
|---|---|---|
| llama.cpp, Qwen3.5-2B | cleans up notes, picks folders | `llama-server -m models/Qwen3.5-2B-Q4_K_M.gguf --jinja -c 4096 -np 1 --port 8091` |
| llama.cpp, Qwen3.5-0.8B | reads photos | `llama-server -hf unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M --jinja -c 4096 -np 1 --port 8100` |
| whisper.cpp | turns recordings into text | `whisper-server -m models/ggml-base.en.bin --port 8092` |
| Radicale | CalDAV server the iPhone's Reminders and Calendar sync with | `.venv/bin/radicale --server-hosts 127.0.0.1:5232 --auth-type none --storage-filesystem-folder data/calendar` |

Then start Ember with `python3 server/app.py` and the settings below, and open http://127.0.0.1:8787.

| Variable | Default | |
|---|---|---|
| `EMBER_NOTES` | `data/notes` | where notes are stored |
| `EMBER_LLM` | `http://127.0.0.1:8080` | llama.cpp server for text |
| `EMBER_VISION` | same as `EMBER_LLM` | llama.cpp server for photos |
| `EMBER_WHISPER` | `http://127.0.0.1:8081` | whisper.cpp server |
| `EMBER_CALDAV` | empty (reminders off) | the calendar, e.g. `http://127.0.0.1:5232/ember/notes/` |
| `EMBER_CALDAV_LOGIN` | empty | `user:password` for the calendar |
| `EMBER_URL` | `http://127.0.0.1:8787` | address used in links from reminders back to notes |
| `EMBER_HOST`, `EMBER_PORT` | `127.0.0.1`, `8787` | where the app is served |

Shorthand expansions live in `server/shorthand.txt`. The font is Courier Prime (SIL Open Font License).

## iPhone shortcuts

Capture without opening the app: Shortcuts post to `https://<pi>.<tailnet>.ts.net/api/quick` (needs Tailscale on).
It takes JSON `{"text": "…"}`, plain text, or a JPEG/PNG photo; a bare link becomes a note with the page's title.

| Shortcut | Actions | Use it from |
|---|---|---|
| **Ember** | Dictate Text (language English, stop after pause) → Get Contents of URL (POST, JSON, `text` = Dictated Text) → Show Notification | "Hey Siri, Ember", the Action Button, Control Center, Back Tap |
| **Send to Ember** | receives Text and URLs, shown in the share sheet → Get Contents of URL (POST, JSON, `text` = Shortcut Input) → Show Notification | the share sheet of any app |
| **Photo to Ember** | receives Images, shown in the share sheet → Convert Image to JPEG → Get Contents of URL (POST, File = Converted Image) → Show Notification | the share sheet of Photos, Camera, screenshots |

HEIC photos are refused, because this ffmpeg reads only the first tile of them; the photo shortcut converts to JPEG first.

## On the Pi

`compose.yml` runs the four servers in `~/ember`, on cores 2-3 at low priority, listening on 127.0.0.1 only.
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

Models live in `~/ember/models`: `Qwen3.5-2B-Q4_K_M.gguf` from `unsloth/Qwen3.5-2B-GGUF`; `Qwen3.5-0.8B-Q4_K_M.gguf` and `mmproj-F16.gguf` from `unsloth/Qwen3.5-0.8B-GGUF`; `ggml-base.en.bin` from `ggerganov/whisper.cpp`.
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
Filing by embedding similarity (bge-small) was tried and dropped: a note's nearest neighbour was in the right area only half the time.

Asking: the 2B reads only about 24 tokens a second on the Pi, so a question goes with the few notes that share its rarer words (or the five with the nearest dates), never all of them. First words come after 4-12 s, whole answers in 7-19 s.
Questions about the diary ("what do I have today?", "anything due this week?") skip the model: asked to list a day's tasks, it left some out, so Ember lists them itself from the reminders' dates, instantly.
