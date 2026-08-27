# local-speech — on-prem STT/TTS sidecar

Serves the two OpenAI-audio endpoints the triage backend calls when
`STT_PROVIDER`/`TTS_PROVIDER` are `openai_compatible`, so **patient audio never
leaves the hospital**:

| Endpoint | Backed by |
|---|---|
| `POST /v1/audio/transcriptions` | faster-whisper (`medium`, th + en) |
| `POST /v1/audio/speech` | MMS-TTS / VITS (`facebook/mms-tts-tha`, `-eng`) |
| `GET /health` | model + load status |

One process serves both, so `STT_BASE_URL` and `TTS_BASE_URL` both point at it.

Running the backend on a **different machine** from this one:
see [`docs/local-ai-connecting.md`](../docs/local-ai-connecting.md).

## Run

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn server:app --host 0.0.0.0 --port 8090
```

First request per model downloads weights (~1.5 GB whisper medium, ~145 MB per
MMS voice) and takes a couple of minutes; after that they stay resident.

Port **8090** rather than the `.env.example` defaults 8080/8081 — on this
machine those are already held by an unrelated Tomcat app and Spring app.

## Why MMS-TTS and not piper

Piper ships **no Thai voice at all** — `rhasspy/piper-voices` has directories
for ~50 languages and `th` is not among them. Thai is the kiosk's default
language, so piper cannot serve the primary case. `facebook/mms-tts-tha` can.

Verified by round-tripping synthesized Thai back through whisper:

```
in : สวัสดีค่ะ กรุณาบอกอาการของคุณ
out: สวัสดีค่ะ การุณาบอกอาการของคุณ
```

Intelligible, one syllable off. It is noticeably more robotic than Google's
`th-TH-Chirp3-HD-Leda`, which is the accepted trade for going on-prem.

Known gap: MMS reads digits and Latin text poorly in Thai. Numbers spoken to
the patient (queue numbers, room numbers, "level 3") should be spelled out in
Thai words before they reach TTS.

## Two contract details that will break things if changed

1. **The voice name carries the language.** `speech_adapter.py` sends only
   `model`, `input`, `voice`, `response_format`, `sample_rate` — there is no
   language field. Hence `TTS_LOCAL_VOICE_TH=th` / `TTS_LOCAL_VOICE_EN=en`.
2. **Output must be 24 kHz.** The backend *raises* rather than resamples on a
   mismatch ([speech_adapter.py:209](../hospital-hotline-assistant-api/app/services/speech_adapter.py#L209)),
   because playing 22.05 kHz frames through the 24 kHz scheduler is a chipmunk
   voice. MMS emits 16 kHz, so the server resamples 3:2 and stamps the header.

## Tuning

Env vars, all optional:

| Var | Default | Note |
|---|---|---|
| `STT_MODEL_SIZE` | `medium` | `small` is ~2× faster, clearly worse at Thai |
| `STT_DEVICE` | `cpu` | `cuda` is far faster — see VRAM note below |
| `STT_COMPUTE_TYPE` | `int8` | use `int8_float16` on GPU |
| `STT_BEAM_SIZE` | `1` | raise for accuracy at latency cost |
| `TTS_MODEL_TH` / `TTS_MODEL_EN` | MMS | any VITS checkpoint |

**VRAM:** the card is 8 GB and the 8B triage model already holds ~5.9 GB, so
STT defaults to CPU to avoid contending with the LLM mid-call. CPU `medium`
runs at roughly **1× realtime** — a 5 s utterance costs ~5 s. Moving STT to
`cuda`/`int8_float16` (~1 GB) is the fix if it fits alongside the LLM; measure
with `nvidia-smi` during a live call before committing to it.
