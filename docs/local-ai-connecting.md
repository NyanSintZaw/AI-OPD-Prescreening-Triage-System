# Connecting the app node to a remote AI node

How to run the AI engines (local LLM + local STT/TTS) on the GPU machine and
the backend + kiosk on a **different** machine.

Nothing in the backend needs a code change — the LLM, STT and TTS backends are
all config seams (`model_adapter.py`, `speech_adapter.py`). Moving them across
the network is three URLs in one `.env`.

```
┌── AI NODE (GPU machine) ───────────────┐     ┌── APP NODE ───────────────┐
│  local-speech :8090  ← only open port  │◀────│  backend  :8100           │
│    ├─ /v1/audio/transcriptions  STT    │HTTP │  kiosk    :5173           │
│    ├─ /v1/audio/speech          TTS    │ /v1 │  postgres :5432           │
│    └─ /v1/chat/completions ──┐  LLM    │     │  HIS mock :8001           │
│  ollama 127.0.0.1:11434  ◀───┘ private │     └───────────────────────────┘
└────────────────────────────────────────┘
```

**One port leaves the machine.** The sidecar proxies chat completions to Ollama,
which stays bound to `127.0.0.1`. That means no unauthenticated LLM endpoint on
the network, and no root access needed to set it up.

The kiosk browser only ever talks to the backend. It never reaches the AI ports
directly — mic audio goes up the WebSocket, the backend fans out to the AI
node, and 24 kHz PCM comes back down the same socket.

---

## 1. AI node — make the services reachable

### local-speech

Already binds `0.0.0.0`, so nothing to change:

```bash
cd local-speech
./venv/bin/uvicorn server:app --host 0.0.0.0 --port 8090
```

### Ollama — leave it on localhost

```bash
ollama serve        # or leave the systemd service running
```

Do **not** expose `:11434`. The sidecar reaches it over the loopback interface
and re-serves it at `/v1/chat/completions`, so the remote backend gets the LLM
through `:8090` like everything else.

This also sidesteps a trap: Ollama binds `127.0.0.1` by default, and on a
systemd install the bind address can only be changed with a root-owned unit
drop-in (`sudo systemctl edit ollama` + `OLLAMA_HOST=0.0.0.0:11434`). Running
`OLLAMA_HOST=… ollama serve` by hand does not stick — systemd undoes it on the
next restart. Proxying avoids needing root at all.

Confirm the sidecar can see it:

```bash
curl -s http://localhost:8090/health | grep -o '"reachable":[a-z]*'
# "reachable":true
```

### Start both at once

```bash
./run-local.sh ai
```

Brings up only the AI node, verifies the Ollama bind, and prints the exact
`.env` lines to paste on the app node.

### Firewall

If the host has one active, open the two ports:

```bash
sudo ufw allow 8090/tcp      # the only port that needs to be open
```

---

## 2. Pick the right address

A GPU box usually has several. Use whichever network the app node shares:

```bash
hostname -I
```

| Kind | Example | Use when |
|---|---|---|
| LAN | `10.1.82.61` | both machines on the same wired/Wi-Fi network |
| Tailscale / VPN | `100.124.80.25` | machines on different networks |
| Docker bridge | `172.17.0.1` | never — internal to Docker |

Prefer a DNS name or a static lease over a DHCP address; a reboot that changes
the IP silently breaks every turn.

---

## 3. App node — three URLs

In `hospital-hotline-assistant-api/.env`, swap `localhost` for the AI node's
address:

All three point at the **same host and port** — the gateway fans them out.

```ini
SCREENING_MODEL_PROVIDER=openai_compatible
SCREENING_OPENAI_BASE_URL=http://10.1.82.61:8090/v1
SCREENING_MODEL_NAME=scb10x/llama3.1-typhoon2-8b-instruct
SCREENING_OPENAI_API_KEY=ollama

STT_PROVIDER=openai_compatible
STT_BASE_URL=http://10.1.82.61:8090/v1

TTS_PROVIDER=openai_compatible
TTS_BASE_URL=http://10.1.82.61:8090/v1
# The TTS request carries no language field — the voice name selects it.
TTS_LOCAL_VOICE_TH=th
TTS_LOCAL_VOICE_EN=en

# Local engines are slower than the cloud ones; the 30 s defaults are tight.
SCREENING_MODEL_TIMEOUT_S=60
SPEECH_HTTP_TIMEOUT_S=60
```

That is the whole backend-side change.

---

## 4. What stays on the app node

**Postgres and the HIS mock travel with the backend**, not the AI node — the
backend is the only thing that talks to them. On the app node:

```bash
docker compose up -d
cd hospital-hotline-assistant-api
uv sync
uv run python scripts/init_db.py        # migrations + criteria v1, run once
uv run uvicorn app.main:app --port 8100
```

Leave `DATABASE_URL` and `HIS_BASE_URL` pointing at `localhost` there.

The Python venv belongs on the machine that runs the backend. Don't sync it on
the GPU box.

**The frontend never touches the AI ports.** In
`hospital-hotline-assistant-web/.env`:

```ini
VITE_API_BASE_URL=http://localhost:8100
```

If the kiosk browser runs on a *third* device, that becomes the app node's IP —
and that exact origin must appear in the backend's `CORS_ORIGINS`, or every
browser call fails CORS:

```ini
CORS_ORIGINS=["http://localhost:5173","http://10.1.82.90:5173"]
```

---

## 5. Security

Ollama has **no authentication**. Publishing `:11434` on a hospital LAN would
let anyone on that network send prompts, read model names, and pull or delete
models. That is why it stays on `127.0.0.1` and the sidecar proxies to it —
only `:8090` is reachable, and it serves nothing but the five routes above.

The gateway itself is still unauthenticated. On a shared network, restrict it
to the app node rather than the whole subnet:

```bash
sudo ufw allow from 10.1.82.90 to any port 8090 proto tcp
```

Before this goes near real patients, `:8090` should also carry a bearer token —
`STT_API_KEY` / `TTS_API_KEY` / `SCREENING_OPENAI_API_KEY` already exist on the
backend side and are sent as `Authorization: Bearer …`; the sidecar just needs
to check them.

---

## 6. Verify the link

Run these **from the app node** — reaching the services from the GPU box itself
proves nothing about remote access.

```bash
AI=10.1.82.61

# sidecar alive, and it can see the LLM behind it
curl -s http://$AI:8090/health

# every model the gateway serves — speech and LLM together
curl -s http://$AI:8090/v1/models

# LLM through the proxy
curl -s -X POST http://$AI:8090/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"scb10x/llama3.1-typhoon2-8b-instruct","messages":[{"role":"user","content":"Say OK"}],"stream":false}'

# TTS end to end — must come back as 24 kHz WAV
curl -s -X POST http://$AI:8090/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"สวัสดีค่ะ","voice":"th","response_format":"wav","sample_rate":24000}' \
  -o /tmp/t.wav && python3 -c "import wave;w=wave.open('/tmp/t.wav');print(w.getframerate(),'Hz')"

# STT end to end — send that file back
curl -s -X POST http://$AI:8090/v1/audio/transcriptions \
  -F "file=@/tmp/t.wav;type=audio/wav" -F "language=th"
```

Warm the models before a demo — the first STT request loads whisper (~2.5 min)
and the first Thai TTS loads MMS (~20 s). After that they stay resident.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `"reachable": false` in `/health` | Ollama not running | `ollama serve` on the AI node |
| `502 LLM upstream error` | Ollama died mid-request | check `ollama ps`; restart it |
| Works on the GPU box, fails from the app node | firewall, or wrong interface IP | §1 firewall, §2 address |
| `Local TTS returned 16000 Hz, expected 24000 Hz` | sidecar not resampling | the backend raises deliberately; check the sidecar's output rate |
| Every browser call fails CORS | kiosk origin missing | add it to `CORS_ORIGINS`, restart the API |
| Turn times out after 30 s | local engines slower than cloud | raise `SCREENING_MODEL_TIMEOUT_S` / `SPEECH_HTTP_TIMEOUT_S` |
| First turn of the day is very slow | models cold | warm-up requests in §6 |
| Replies are fine but slow mid-call | Ollama unloaded the model | set a keep-alive so it stays resident during clinic hours |

---

## Related

- [`local-stack-design.md`](local-stack-design.md) — the system design, GPU and
  latency budgets, and the single-port gateway this document refers to
- [`../local-speech/README.md`](../local-speech/README.md) — the sidecar itself:
  models, tuning, why MMS-TTS instead of piper
