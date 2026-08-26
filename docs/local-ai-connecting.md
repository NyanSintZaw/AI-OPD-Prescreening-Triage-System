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

Already binds `0.0.0.0`, so nothing to change.

Windows (the current AI node):

```powershell
cd local-speech
.\venv\Scripts\uvicorn server:app --host 0.0.0.0 --port 8090
```

Linux:

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

On Windows the mechanism differs (Ollama runs as a per-user background app and
reads `OLLAMA_HOST` from the user environment, so `setx` would make it stick)
but the conclusion is the same: leave it on loopback and proxy.

Confirm the sidecar can see it:

```bash
curl -s http://localhost:8090/health | grep -o '"reachable":[a-z]*'
# "reachable":true
```

### Start both at once

```powershell
.\run-local.ps1 ai        # Windows
```

```bash
./run-local.sh ai         # Linux
```

Brings up only the AI node, verifies the Ollama bind, warns if
`SCREENING_MODEL_NAME` is not actually in `ollama list`, and prints the exact
`.env` lines to paste on the app node.

### Firewall

If the host has one active, open the one port:

```powershell
# Windows — run elevated
New-NetFirewallRule -DisplayName "local-ai gateway" -Direction Inbound `
  -Protocol TCP -LocalPort 8090 -Action Allow
```

```bash
sudo ufw allow 8090/tcp      # Linux — the only port that needs to be open
```

---

## 2. Pick the right address

**Use the Tailscale MagicDNS name, not an IP.** On the campus Wi-Fi the booth's
DHCP lease moves often — it changed three times in one afternoon
(`172.27.138.104` → `.141.144` → `.132.246`), and every change silently breaks
every turn until someone edits `.env` on the app node. A name does not move:

```
AI_MODE=local
LOCAL_AI_BASE_URL=http://desktop-hh9005e.tail310b75.ts.net:8090/v1
```

MagicDNS is enabled tailnet-wide, so any device on the tailnet resolves that
name. Two requirements on the **app node** (not the booth):

- Tailscale running and logged into the same tailnet.
- `tailscale set --accept-dns=true` — on by default on macOS. Without it the
  name will not resolve and you are back to IPs. Check with
  `tailscale dns status`.

The booth itself does not need `--accept-dns`; it is the server, and never has
to resolve anything. `tailscale status --json` reports the booth's own name
under `Self.DNSName`.

Tailscale also encrypts the hop, which the LAN address does not — worth having
for audio and clinical text even inside the hospital.

> The tailnet is shared and large (~55 devices). The gateway has **no
> authentication**, so every device on it can reach the booth once the port is
> bound beyond loopback. Restrict with Tailscale ACLs, or keep the LAN
> firewall rule from §5, before leaving it running unattended.

### Falling back to an IP

If the app node is not on the tailnet, a GPU box usually has several addresses.
Use whichever network the app node shares:

```powershell
# Windows
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' } |
  Select-Object IPAddress, InterfaceAlias
```

```bash
hostname -I      # Linux
```

| Kind | Example | Use when |
|---|---|---|
| Tailscale | `100.90.155.63` | stable; prefer the MagicDNS name above |
| LAN | `172.27.132.246` | same wired/Wi-Fi network — **moves with DHCP** |
| Hyper-V / WSL vEthernet | `192.168.64.1` | never — no other machine can reach it |
| Docker bridge | `172.17.0.1` | never — internal to Docker |

A DHCP address is the last resort. If you must use one, ask IT for a static
lease on the booth's MAC — otherwise a reboot silently breaks every turn, and
the failure looks like a timeout rather than a name that stopped resolving.

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

```powershell
# Windows — run elevated. RemoteAddress is what scopes it to the app node.
New-NetFirewallRule -DisplayName "local-ai gateway (app node only)" `
  -Direction Inbound -Protocol TCP -LocalPort 8090 `
  -RemoteAddress 10.1.82.90 -Action Allow
```

```bash
sudo ufw allow from 10.1.82.90 to any port 8090 proto tcp   # Linux
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
