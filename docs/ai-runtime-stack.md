# AI runtime stack — LLM, STT, TTS

What actually serves a patient turn: which model, on which provider, over which
contract. Measured on the booth workstation (Windows, RTX 4000 SFF Ada 20 GB)
on 2026-08-24.

For *why* the stack is split the way it is, see
[`local-stack-design.md`](local-stack-design.md). For connecting a backend on a
different machine, see [`local-ai-connecting.md`](local-ai-connecting.md).

---

## 1. One switch decides everything

`AI_MODE` ([config.py:67](../hospital-hotline-assistant-api/app/config.py#L67))
resolves all three providers at once, so they cannot drift apart:

| `AI_MODE` | LLM | STT | TTS |
|---|---|---|---|
| `local` | Ollama via the gateway | faster-whisper | MMS-TTS |
| `cloud` | Gemini on Vertex AI | Google Cloud STT | Google Cloud TTS |
| `custom` | whatever the three `*_PROVIDER` vars say | | |

In `local` mode it also fills in any of the three base URLs left unset from
`LOCAL_AI_BASE_URL` (default `http://localhost:8090/v1`) and supplies a dummy
API key, because the OpenAI client rejects an empty one.

> **The default is `custom`, not `local`.** Setting only the base URLs leaves
> the providers on `vertexai`/`google`, so the stack looks on-prem while still
> sending patient audio to the cloud. `run-local.ps1` / `run-local.sh` set
> `AI_MODE=local` for you; if you start services by hand, set it yourself.

Check what is actually resolved at runtime: `GET /health` on the backend
returns `ai_mode_summary` — mode, `provider:model`, stt, tts.

---

## 2. Topology in local mode

Everything on-prem goes through **one port**. Ollama stays on loopback and is
reached only through the gateway's proxy, so there is no unauthenticated LLM
endpoint on the hospital LAN.

```
browser kiosk
   │  16 kHz Int16 PCM  (binary WS frames)
   ▼
backend  WS /ws/voice/{session_id}  →  voice_bridge.py
   │
   ├─ STT  POST :8090/v1/audio/transcriptions ─┐
   ├─ LLM  POST :8090/v1/chat/completions ─────┤   local-speech gateway
   └─ TTS  POST :8090/v1/audio/speech ─────────┘   (server.py)
                                                        │
                                                        └─ LLM proxied to
                                                           127.0.0.1:11434
                                                           (Ollama)
   ▲
   │  24 kHz Int16 PCM  (binary WS frames)
```

---

## 3. LLM

| | Local | Cloud |
|---|---|---|
| Model | `scb10x/llama3.1-typhoon2-8b-instruct` | `gemini-3.1-flash-lite` |
| Provider | `openai_compatible` | `vertexai` |
| Client | `ChatOpenAI` | `ChatGoogleGenerativeAI` |
| Endpoint | `:8090/v1/chat/completions` → Ollama | Vertex AI |

Built by `build_chat_model()`
([model_adapter.py:54](../hospital-hotline-assistant-api/app/services/screening/model_adapter.py#L54)).
Shared settings: **temperature 0.1** (extraction must be as deterministic as
sampling allows), **30 s timeout**, **1 retry**. Gemini 3+ additionally gets
`thinking_level=minimal`; 2.x models get `thinking_budget=0` instead — sending
both is a 400.

### Where the LLM is actually called

The engine is **decision-separated**: the model never decides triage. It only
extracts structured findings, paraphrases questions, and phrases explanations —
a pure rules engine decides level and department. Three of the eight graph
nodes call it:

| Node | Job |
|---|---|
| `ingest.py` | extract structured findings from the utterance |
| `question.py` | paraphrase the next question (red-flag/scale wording stays verbatim) |
| `explain.py` | phrase the explanation, RAG-grounded, validated for leaks |

`dispose.py`, `followup.py`, `terminal.py` are pure — no model call. A typical
turn is **two LLM calls**: ingest, then question *or* explain.

### Measured

- **50.1 tok/s** generating Thai (typhoon2 8B, Q4).
- **9.2 GB resident** at `num_ctx` 8192 — 4.9 GB of weights plus KV cache.
  Budget this, don't assume the on-disk size.
- Identical to the 50.3 tok/s the old RTX 4060 Ti 8 GB managed. Generation is
  **memory-bandwidth-bound** (288 vs ~280 GB/s), so the bigger card bought
  capacity, not speed.

> Set `OLLAMA_MAX_LOADED_MODELS=1`. Ollama keeps recently-used models resident
> in parallel; two 8B models measured 15.7 GB of 20 GB here, which starves
> whisper and VITS back onto the CPU.

---

## 4. STT

| | Local | Cloud |
|---|---|---|
| Engine | faster-whisper (ctranslate2) | Google Cloud Speech-to-Text |
| Model | `large-v3-turbo` | — |
| Device / precision | `cuda` / `float16` | — |
| Beam size | 1 | — |
| VAD | `vad_filter=True` (trims edges; the bridge already endpoints) | — |

`large-v3-turbo` has a distilled 4-layer decoder against 32 in `large-v3`,
making it several times faster for near-identical transcription — and clearly
better at Thai than the `medium` it replaced.

**Contract** — OpenAI `/v1/audio/transcriptions`, multipart
([speech_adapter.py:82](../hospital-hotline-assistant-api/app/services/speech_adapter.py#L82)):
fields `model`, `language`, `response_format=json`, plus the audio as `file`.
The response carries no confidence score, so `SttResult.confidence` is always
`None`.

**Audio in:** the browser worklet sends 16 kHz mono Int16 PCM as binary WS
frames; the bridge wraps the buffered turn in a WAV header before posting.

**Measured: 0.257 s for 5.21 s of audio — 20.3× realtime.** The previous
`medium`/int8 CPU configuration ran at ~1.0× realtime, i.e. a 5-second
utterance cost 5 seconds.

---

## 5. TTS

| | Local | Cloud |
|---|---|---|
| Engine | MMS-TTS / VITS via transformers | Google Cloud Text-to-Speech |
| Thai voice | `facebook/mms-tts-tha` | `th-TH-Chirp3-HD-Leda` |
| English voice | `facebook/mms-tts-eng` | `en-US-Chirp3-HD-Leda` |
| Device | `cuda` | — |
| Native rate | 16 kHz → resampled 3:2 → 24 kHz | 24 kHz |

Piper ships **no Thai voice at all**, and Thai is the kiosk default — that is
the whole reason for MMS. XTTS-v2 and Kokoro have no Thai either.

**Contract** — OpenAI `/v1/audio/speech`, JSON
([speech_adapter.py:168](../hospital-hotline-assistant-api/app/services/speech_adapter.py#L168)):
`model`, `input`, `voice`, `response_format`, `sample_rate`.

Two details that break things if changed:

1. **The voice name carries the language.** There is no language field in the
   request, so `TTS_LOCAL_VOICE_TH=th` / `TTS_LOCAL_VOICE_EN=en` is what
   selects the Thai model. The config default is `alloy` for both — it **must**
   be overridden for the local gateway.
2. **Output must be 24 kHz.** The backend *raises* rather than resamples on a
   mismatch ([speech_adapter.py:210](../hospital-hotline-assistant-api/app/services/speech_adapter.py#L210)),
   because playing 22.05 kHz frames through the 24 kHz scheduler is a chipmunk
   voice. MMS emits 16 kHz, so the gateway resamples exactly 3:2 and stamps the
   header.

**Measured: 0.059 s for 3.34 s of Thai audio — 57× realtime** (against ~2.1×
on CPU). Round-tripping synthesized Thai back through whisper:

```
in : สวัสดีค่ะ กรุณาบอกอาการของคุณ
out: สวัสดีคัด กรณาบอกอาการของคุณ
```

Intelligible, a couple of syllables off. Noticeably more robotic than Chirp3 —
the accepted trade for on-prem.

**Known gap:** MMS reads digits and Latin text poorly in Thai. Queue numbers,
room numbers and "level 3" should be spelled out in Thai words before reaching
TTS. That is a **text-normalization fix, not a model one** — most Thai TTS has
the same weakness.

---

## 6. One patient turn, end to end

1. Browser streams 16 kHz PCM up the WebSocket.
2. Turn ends on the patient tapping **"I'm finished speaking"**; silence
   auto-detect is only a safety net.
3. Buffered PCM → WAV → **STT**.
4. Transcript → `process_chat_stream` → one bounded LangGraph invocation:
   ingest (**LLM**) → red-flag gate + completeness gate (pure rules) →
   question or dispose → explain (**LLM**, validated).
5. Reply text → **TTS** → LINEAR16 24 kHz, chunked back down the socket.
6. The turn persists as it happens; patient-facing replies never contain
   triage level, colour, diagnosis or prescription.

### Latency budget

| Stage | CPU (before) | GPU (now) |
|---|---:|---:|
| Speech to text | ~5.00 s | **0.26 s** |
| Extraction call (LLM) | ~2.00 s | ~2.00 s |
| Question or explain call (LLM) | ~2.00 s | ~2.00 s |
| Text to speech | ~1.90 s | **0.08 s** |
| **Compute subtotal** | **~10.9 s** | **~4.3 s** |

The two LLM calls are now **over half** the remaining budget, and they are
bandwidth-bound — they will not improve without a smaller model or a shorter
prompt. Cutting prompt size is the lever.

> **Note the end-of-turn discrepancy.** `local-stack-design.md` §4 budgets
> 2.50 s for silence detection, but `voice_silence_hang_ms` is **8000** in
> [config.py](../hospital-hotline-assistant-api/app/config.py). The stack is
> button-first, so a patient who taps pays ~0 — but a patient who never taps
> pays 8 s. Reconcile the two before quoting a turn total.

---

## 7. Config reference

Backend `.env`:

| Var | Local value | Note |
|---|---|---|
| `AI_MODE` | `local` | overrides the three providers below |
| `LOCAL_AI_BASE_URL` | `http://localhost:8090/v1` | fills any URL left unset |
| `LOCAL_SCREENING_MODEL_NAME` | `scb10x/llama3.1-typhoon2-8b-instruct` | must exist in `ollama list` |
| `CLOUD_SCREENING_MODEL_NAME` | `gemini-3.1-flash-lite` | |
| `TTS_LOCAL_VOICE_TH` / `_EN` | `th` / `en` | **default `alloy` is wrong for the gateway** |
| `SCREENING_MODEL_TEMPERATURE` | `0.1` | |
| `SCREENING_MODEL_TIMEOUT_S` | `30` | |

Gateway (`local-speech/`) environment:

| Var | Default | Note |
|---|---|---|
| `STT_MODEL_SIZE` | `large-v3-turbo` | `large-v3` also fits (~4.7 GB) |
| `STT_DEVICE` | `cuda` | falls back to CPU int8 |
| `STT_COMPUTE_TYPE` | `float16` | |
| `STT_BEAM_SIZE` | `1` | headroom to raise; measure first |
| `TTS_DEVICE` | `cuda` | needs a CUDA torch build |
| `TTS_MODEL_TH` / `_EN` | MMS | any VITS checkpoint |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | proxy upstream |
| `LLM_TIMEOUT_S` | `180` | |

---

## 8. Verifying a deployment

```bash
curl -s http://localhost:8090/health     # per-stage device + LLM reachability
curl -s http://localhost:8090/metrics    # p50/p95 per stage
```

`/health` reports `device` (what actually loaded) next to `device_requested`
(what was asked for). If they differ, a CUDA fallback fired and the reason is
in the server log.

**Read `latency_s` from `/metrics`, not wall-clock from a client.** An HTTP
round trip measured 2.09 s for work the server did in 0.059 s.

Two independent CUDA paths, which fail separately:

- **STT** runs on ctranslate2, needing `nvidia-cublas-cu12` / `nvidia-cudnn-cu12`
  even when torch is present.
- **TTS** runs on torch — a CPU-only wheel pins it to the CPU whatever
  `TTS_DEVICE` says.

On Windows, `_preload_cuda_libs()` must prepend those wheel directories to
`os.environ["PATH"]`: ctranslate2 requests its libraries by bare name, and
Windows resolves bare names through PATH, **not** through
`os.add_dll_directory`. PATH is read per `LoadLibrary` call, so setting it
in-process works — the opposite of Linux, where `LD_LIBRARY_PATH` is read once
at exec and the libraries must be `dlopen`ed explicitly instead.

> **The gateway has no authentication and re-serves the LLM.** Bound to
> `0.0.0.0` it is reachable by anything that can route to the host — during
> testing, requests arrived from a non-local address within minutes. Firewall
> the port to the app node, or bind `127.0.0.1` when the backend is local.
