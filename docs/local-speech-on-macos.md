# Running the speech gateway on the macOS full-stack machine

Moving `local-speech/` off the Windows GPU box and onto the Mac that already
runs the backend and kiosk. Everything then talks over `localhost`, which
removes the devtunnel, the 100 s tunnel cap, the port-8090 Traefik clash and
the insecure-origin microphone block in one go.

The trade is real and worth stating up front: **the Mac has no CUDA**. STT
gets slower, and F5-TTS stops being viable.

---

## 1. What actually runs, and on what

| Stage | Model | Windows (RTX 4000 Ada) | macOS (Apple Silicon) |
|---|---|---|---|
| **STT** | `faster-whisper large-v3-turbo` | cuda / float16 — 20× realtime | **cpu / int8** — expect 1–3× realtime |
| **TTS th** | `facebook/mms-tts-tha` (VITS) | cuda — 57× realtime | cpu or mps — ~2× realtime |
| **TTS en** | `facebook/mms-tts-eng` (VITS) | cuda | cpu or mps |
| **TTS (alt)** | `VIZINTZOR/F5-TTS-THAI` via `f5-tts-th` | cuda — ~0.8 s/utterance | **not recommended** — see §5 |
| **LLM** | `scb10x/llama3.1-typhoon2-8b-instruct` (Q4, 4.9 GB) | proxied to Ollama, 50 tok/s | Ollama on the Mac, **or stays on the GPU box — §6b** |

Sizes on disk: whisper `large-v3-turbo` ≈ 1.6 GB, each MMS voice ≈ 145 MB,
F5-TTS ≈ 1.3 GB plus a Vocos vocoder, typhoon2 ≈ 4.9 GB.

**faster-whisper cannot use Apple's GPU.** It runs on ctranslate2, which has
no Metal backend — CPU only, whatever `STT_DEVICE` says. Torch (so MMS/VITS)
*can* use `mps`.

---

## 2. Prerequisites

```bash
brew install ffmpeg          # only needed if you try F5; harmless otherwise
python3 --version            # 3.11+ ; 3.12 is what the backend venv uses
```

## 3. Install

```bash
cd local-speech
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

`requirements.txt` is platform-aware — the `+cu124` torch pin and every
`nvidia-*` wheel carry `sys_platform != "darwin"` markers, so pip skips them
and installs plain PyPI torch instead. **If you see pip trying to resolve
`torch==2.6.0+cu124` on the Mac, you are on an older copy of this file.**

## 4. Configure

`local-speech/.env` (copy from `.env.example`):

```
# Whisper cannot use Metal — ctranslate2 has no MPS backend. int8 is the
# right compute type on CPU; float16 is a CUDA thing.
STT_MODEL_SIZE=large-v3-turbo
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
# Drop to 1 if turns feel slow; 5 costs little on CUDA but more on CPU.
STT_BEAM_SIZE=1

# MMS, not F5 — see below.
TTS_ENGINE_TH=mms
TTS_ENGINE_EN=mms
TTS_DEVICE=cpu        # try mps once it works on cpu; VITS is small either way
TTS_SPEED_TH=0.95
TTS_SPEED_EN=1.0

# ONLY if Ollama also runs on the Mac. Leave both unset when the LLM stays on
# the GPU box (§6b) — prewarm would otherwise try to pin a model that is not
# there, and health.llm.reachable=false is the correct reading in that split.
# LLM_PIN_MODEL=scb10x/llama3.1-typhoon2-8b-instruct
```

If `large-v3-turbo` on CPU is too slow, `STT_MODEL_SIZE=medium` is roughly 2×
faster and clearly worse at Thai. Measure before choosing — `GET /metrics`
reports `realtime_factor` per call.

## 5. Why not F5 on the Mac

F5-TTS is flow matching: ~32 denoising passes through a 336M-parameter model
per utterance. On the RTX 4000 that is ~0.8 s. On CPU it is many seconds, and
`f5_tts_th` has no Metal path. MMS is one forward pass through a small VITS
and stays around 2× realtime on CPU.

The cost of choosing MMS is real and you already know it: **`mms-tts-tha` is a
male voice**, and th/en are different speakers, so the nurse persona changes
with language. That was the whole reason for moving to F5. If the female voice
matters more than latency, keep TTS on the Windows box and move only STT.

## 6. Run

```bash
cd local-speech
./venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8091
```

`127.0.0.1` is correct here — the backend is on the same machine now, so
nothing needs to reach it from outside. That also removes the unauthenticated
gateway from the network entirely.

Prewarm loads the models on a background thread; the port answers in ~2 s and
`GET /health` reports `loaded` when they are actually ready.

## 6b. Keeping Ollama on the Windows box

The LLM does not have to move with speech. Ollama binds `127.0.0.1` on the
Windows machine and stays there; the gateway already running beside it keeps
re-serving it at `/v1/chat/completions`, and the Mac reaches that through the
tunnel. Speech runs locally on the Mac.

Two gateway instances then, each doing part of the job:

| | Host | Serves | Reached at |
|---|---|---|---|
| Windows gateway | GPU box | `/v1/chat/completions` (proxy to Ollama) | the devtunnel URL |
| Mac gateway | full-stack box | `/v1/audio/transcriptions`, `/v1/audio/speech` | `http://localhost:8091/v1` |

The Mac's gateway needs **no Ollama at all**. Leave `LLM_PIN_MODEL` unset in
its `.env` — otherwise prewarm tries to pin a model that is not there — and
expect `GET /health` to report `llm.reachable: false`. That is correct here,
not a fault: nothing on the Mac calls its LLM proxy.

Do **not** try to point the Mac directly at `http://<windows-host>:11434`.
Ollama is bound to loopback, so it is not reachable, and exposing it would put
an unauthenticated LLM endpoint on the hospital LAN — the thing
`local-stack-design.md` exists to prevent. The proxy is the supported route.

## 7. Point the backend at it

`hospital-hotline-assistant-api/.env`:

Everything on the Mac:

```
AI_MODE=local
LOCAL_AI_BASE_URL=http://localhost:8091/v1
LOCAL_SCREENING_MODEL_NAME=scb10x/llama3.1-typhoon2-8b-instruct
TTS_LOCAL_VOICE_TH=th
TTS_LOCAL_VOICE_EN=en
```

Or, keeping Ollama on the Windows box (§6b) — set the LLM URL explicitly and
leave the speech URLs unset, because `AI_MODE=local` fills in only what you
have not set:

```
AI_MODE=local
LOCAL_AI_BASE_URL=http://localhost:8091/v1                 # -> STT + TTS, local
SCREENING_OPENAI_BASE_URL=https://<tunnel-host>/v1         # -> LLM, remote
LOCAL_SCREENING_MODEL_NAME=scb10x/llama3.1-typhoon2-8b-instruct
TTS_LOCAL_VOICE_TH=th
TTS_LOCAL_VOICE_EN=en
```

Verified to resolve as:

```
provider : openai_compatible
LLM  -> https://<tunnel-host>/v1
STT  -> http://localhost:8091/v1
TTS  -> http://localhost:8091/v1
```

Either way, **every base URL must end in `/v1`** — the clients append their
own path (`/chat/completions`, `/audio/speech`, `/audio/transcriptions`), and
omitting it is what produced the original `404 /chat/completions`. Letting
`AI_MODE=local` fill a URL in guarantees the suffix; typing one by hand does
not, so check it.

If you moved everything, delete the devtunnel and the `*_BASE_URL` lines that
point at it. If you kept Ollama on the GPU box (§6b), the tunnel stays — but
re-point it at **8091**, not the old 8090, which Traefik owns.

## 8. Verify

```bash
curl -s localhost:8091/health | python3 -m json.tool
open http://localhost:8091/test
```

`/test` exercises LLM, STT and TTS from the browser with timings. Then a real
turn through the kiosk at **`http://localhost:5173/kiosk`** — and note that
`localhost` is what makes the microphone work at all: on any other host over
plain http the browser removes `navigator.mediaDevices` and the kiosk captures
nothing. That single fact is why co-locating everything is worth the slower
STT.

## 9. What to expect

| | Windows GPU | Mac CPU (estimate) |
|---|---:|---:|
| STT, 5 s utterance | 0.26 s | 2–5 s |
| TTS, one sentence | 0.06 s (MMS) | ~1 s (MMS) |
| LLM, 2 calls | ~8 s | similar if Ollama is local |

The Mac numbers are estimates — measure with `/metrics` rather than trusting
them. STT is the one that changes most: from 20× realtime to roughly 1×, which
is where this stack started before the GPU work.
