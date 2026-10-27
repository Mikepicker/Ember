# ember

Fire-and-forget notes. Write, snap or speak on the phone; a Raspberry Pi tidies each note into Markdown, files it, and puts its dated tasks into the iPhone's Reminders and Calendar.

- `web/` — the app: plain HTML, CSS and JavaScript, works offline, no build step.
- `server/` — Python standard library only: serves the app, stores notes as Markdown files, tidies them in the background.
- Notes live in `data/notes/` as plain `.md` files. They are the only source of truth.

The AI and calendar pieces are separate servers that Ember talks to over HTTP:

| Server | Does | Run locally |
|---|---|---|
| llama.cpp | cleans up notes, names folders, reads photos | `llama-server -hf unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M --port 8091 --jinja -c 4096` |
| whisper.cpp | turns recordings into text | `whisper-server -m models/ggml-base.en.bin --port 8092` |
| Radicale | CalDAV server the iPhone's Reminders and Calendar sync with | `.venv/bin/radicale --server-hosts 127.0.0.1:5232 --auth-type none --storage-filesystem-folder data/calendar` |

Then start Ember with `python3 server/app.py` and the settings below, and open http://127.0.0.1:8787.

| Variable | Default | |
|---|---|---|
| `EMBER_NOTES` | `data/notes` | where notes are stored |
| `EMBER_LLM` | `http://127.0.0.1:8080` | llama.cpp server |
| `EMBER_WHISPER` | `http://127.0.0.1:8081` | whisper.cpp server |
| `EMBER_CALDAV` | empty (reminders off) | the calendar, e.g. `http://127.0.0.1:5232/ember/notes/` |
| `EMBER_CALDAV_LOGIN` | empty | `user:password` for the calendar |
| `EMBER_URL` | `http://127.0.0.1:8787` | address used in links from reminders back to notes |
| `EMBER_HOST`, `EMBER_PORT` | `127.0.0.1`, `8787` | where the app is served |

Shorthand expansions live in `server/shorthand.txt`. The font is Courier Prime (SIL Open Font License).

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

Models live in `~/ember/models`: `Qwen3.5-0.8B-Q4_K_M.gguf` and `mmproj-F16.gguf` from `unsloth/Qwen3.5-0.8B-GGUF`, `ggml-base.en.bin` from `ggerganov/whisper.cpp`.
