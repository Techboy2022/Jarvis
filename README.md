# JARVIS

A private, local chat assistant: FastAPI + Ollama, no cloud, no CDN, no build
step. Tuned to be usable on a CPU-only laptop such as a ThinkPad T490.

## What it does

- **Real conversations** — every chat is stored in SQLite, and the last N turns
  are replayed to the model, so JARVIS remembers what you said.
- **Multiple chats** — sidebar with search, pinning, rename, delete, export to
  markdown.
- **Token streaming over SSE** with **Stop** and **Regenerate**. Stopping keeps
  the partial answer instead of throwing it away.
- **Reasoning handled properly** — `<think>` blocks from qwen3/deepseek-r1 are
  split out of the answer and shown in a collapsible "Reasoning" panel (or
  hidden entirely), including when they arrive split across token boundaries.
- **Markdown rendering** with fenced code blocks, copy buttons, tables and
  lists. The renderer escapes everything first, so model output cannot inject
  HTML into the page.
- **Model picker** populated from `/api/tags`, with background warm-up so the
  first question doesn't pay the cold-load cost.
- **Live settings** — model, system prompt, temperature, top-p, `num_ctx`,
  `num_predict`, CPU threads, keep-alive, history depth. Persisted in SQLite.
- **Voice input** via the browser's speech recognition, mobile-friendly layout,
  light/dark following the OS, `Ctrl+K` for a new chat, `Esc` to stop.
- **Health indicator** — tells you when Ollama is down, when a model isn't
  installed (with the `ollama pull` command to fix it), instead of a silent
  hang.
- **Speed readout** — tokens/s and time-to-first-token under each answer, which
  is how you'll tell whether a model is worth keeping on this hardware.

## Install on the T490

```bash
# 1. Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:4b          # or llama3.2:3b for speed

# 2. JARVIS
cd ~/jarvis
cp .env.example .env          # optional, edit to taste
chmod +x run.sh
./run.sh                      # creates .venv, installs deps, starts server
```

Open <http://127.0.0.1:8080>.

## Run as a service

```bash
sudo useradd --system --home /opt/jarvis jarvis   # if the user doesn't exist
sudo cp -r ~/jarvis /opt/jarvis
sudo chown -R jarvis:jarvis /opt/jarvis
sudo -u jarvis python3 -m venv /opt/jarvis/.venv
sudo -u jarvis /opt/jarvis/.venv/bin/pip install -r /opt/jarvis/requirements.txt
sudo cp /opt/jarvis/deploy/jarvis.service /etc/systemd/system/
sudo systemctl enable --now jarvis
```

Set `JARVIS_HOST=0.0.0.0` in `.env` to reach it from your phone on the same
network. There is no authentication — only do that on a network you trust, or
put it behind a reverse proxy / Tailscale.

## Getting the most out of a T490

The T490 has a 4-core / 8-thread U-series CPU and no usable GPU for inference,
so generation is memory-bandwidth bound. What actually matters:

| Setting | Recommendation | Why |
| --- | --- | --- |
| Model size | 3B–4B, Q4_K_M | ~3 GB RAM, ~8–14 tok/s. A 7B/8B model runs at 3–5 tok/s and only feels worth it for hard questions. |
| `num_thread` | 4 (physical cores) | Hyperthreads add contention, not throughput. |
| `num_ctx` | 4096 | Every extra token of context costs RAM and prompt-eval time. Raise only if you paste long documents. |
| `keep_alive` | `30m` | Prevents Ollama unloading the model between questions (a ~15 s reload each time). |
| History depth | 20 messages | Longer history means re-reading more tokens every turn. |
| Power | plug in, `powerprofilesctl set performance` | On battery the CPU clocks down and tokens/s roughly halves. |
| Thermals | keep vents clear | The U-series chip throttles hard under sustained load. |

Ollama-side environment variables worth setting in
`/etc/systemd/system/ollama.service.d/override.conf`:

```ini
[Service]
Environment="OLLAMA_KEEP_ALIVE=30m"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_FLASH_ATTENTION=1"
```

`OLLAMA_NUM_PARALLEL=1` matters most: parallel slots split the context window
and slow single-user chat down.

## Layout

```
jarvis/
├── jarvis/
│   ├── config.py      env-driven settings, CPU-thread defaults
│   ├── store.py       SQLite chats/messages/prefs (async wrappers)
│   ├── ollama.py      pooled httpx client, streaming, error mapping
│   ├── thinking.py    incremental <think> splitter
│   ├── main.py        FastAPI app, REST + SSE endpoints
│   └── static/        index.html, app.css, app.js, markdown.js
├── tests/             pytest suite (runs against a stub Ollama)
├── deploy/            systemd unit
├── requirements.txt
└── run.sh
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Ollama reachability, loaded models |
| GET | `/api/models` | installed models |
| GET/PUT | `/api/settings` | read/update persisted generation settings |
| GET/POST | `/api/chats` | list / create chats |
| GET/PATCH/DELETE | `/api/chats/{id}` | fetch with messages / rename, pin, set model / delete |
| POST | `/api/chats/{id}/messages` | send a message, stream the reply (SSE) |
| POST | `/api/chats/{id}/regenerate` | redo the last answer (SSE) |
| GET | `/api/chats/{id}/export` | markdown transcript |
| GET | `/api/search?q=` | search titles and message bodies |
| POST | `/api/warmup` | preload a model |

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

The suite spins up a fake Ollama, so it never needs a model or a GPU.
