# local-speech — on-prem STT / TTS / LLM gateway

One process serving everything the triage backend needs when `AI_MODE=local`,
so **no patient text or audio leaves the hospital**:

| Endpoint | Backed by |
|---|---|
| `POST /v1/audio/transcriptions` | faster-whisper (`large-v3-turbo`, th + en) |
| `POST /v1/audio/speech` | MMS-TTS / VITS (`facebook/mms-tts-tha`, `-eng`) |
| `POST /v1/chat/completions` | pass-through proxy to Ollama |
| `GET /v1/models` | speech models + whatever Ollama serves |
| `GET /health` | resolved device per stage, LLM reachability |
| `GET /metrics` | p50/p95 latency, TTFT, GPU/CPU util, peak VRAM |

The name predates the LLM proxy. `SCREENING_OPENAI_BASE_URL`, `STT_BASE_URL`
and `TTS_BASE_URL` all point at this one port — set `AI_MODE=local` in the
backend `.env` and it fills all three in for you.

Ollama stays bound to `127.0.0.1` and is reached only through this proxy, so
there is no unauthenticated LLM endpoint on the hospital LAN.

Running the backend on a **different machine**:
see [`docs/local-ai-connecting.md`](../docs/local-ai-connecting.md).

## Run

Port **8090** rather than the `.env.example` defaults 8080/8081 — those were
already held by an unrelated Tomcat and Spring app on the original box.

**Windows** (the current AI node):

```powershell
py -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\uvicorn server:app --host 0.0.0.0 --port 8090
```

**Linux:**

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn server:app --host 0.0.0.0 --port 8090
```

Or let `..\run-local.ps1` (Windows) / `../run-local.sh` (Linux) start the whole
stack. First request per model downloads weights (~1.6 GB whisper turbo, ~145 MB
per MMS voice) and takes a couple of minutes; after that they stay resident.

> **`--host 0.0.0.0` means anyone who can route to this machine can use it.**
> The gateway has no authentication, and it re-serves the LLM: reaching it is
> reaching Ollama. During testing here the log showed requests arriving from a
> non-local address (`202.28.45.131`) within minutes of the port opening — so
> this is not hypothetical on the hospital network. Firewall the port to the
> app node before leaving it running; see §5 of
> [`docs/local-ai-connecting.md`](../docs/local-ai-connecting.md). Bind
> `127.0.0.1` instead when the backend runs on this same machine.

## GPU

Sized for the **RTX 4000 SFF Ada, 20 GB**. All three stages stay resident at
once. Measured on this box:

| Stage | VRAM | Note |
|---|---:|---|
| Triage LLM (typhoon2 8B, ctx 8192) | **9.2 GB** | `ollama ps`, 100% GPU |
| STT (whisper `large-v3-turbo`, fp16) | ~2.5 GB | |
| TTS (two VITS voices) | ~0.3 GB | |
| **Total** | **~12 GB of 20 GB** | |

The LLM figure is the one that surprises: 4.9 GB of weights on disk becomes
9.2 GB resident once Ollama allocates the KV cache for an 8192-token context.
Raising the context window raises this — budget it, don't assume it.

Measured speed once it is actually on the GPU:

| Stage | Before (CPU) | After (GPU) |
|---|---|---|
| STT `large-v3-turbo` fp16 | ~5.0 s — 1.0× realtime | **0.257 s — 20.3× realtime** |
| TTS MMS/VITS, Thai | ~1.90 s — 2.1× realtime | **0.059 s — 57× realtime** |
| LLM typhoon2 8B, Thai | — | 50.1 tok/s (unchanged, bandwidth-bound) |

Together that takes roughly **6.5 s out of every patient turn** (13.4 s → ~6.8 s).

Measure with `GET /metrics` — and read `latency_s` there, not wall-clock from a
client: an HTTP round trip from PowerShell showed 2.09 s for work the server
did in 0.059 s.

> **Set `OLLAMA_MAX_LOADED_MODELS=1`.** Ollama keeps recently-used models
> resident in parallel by default. Two 8B models at once measured 15.7 GB of
> 20 GB here, which leaves too little for whisper and VITS and pushes them back
> to the CPU — the exact regression this setup exists to avoid.

Two separate CUDA paths, and they fail independently:

- **STT** runs on **ctranslate2, not torch**, so it needs `nvidia-cublas-cu12`
  and `nvidia-cudnn-cu12` even when torch is installed. `_preload_cuda_libs()`
  makes them loadable: `os.add_dll_directory` on Windows, explicit `dlopen` on
  Linux (`LD_LIBRARY_PATH` is read at exec, too early to set from in-process).
- **TTS** runs on **torch**. A CPU-only wheel silently pins it to the CPU no
  matter what `TTS_DEVICE` says, which is why `requirements.txt` pulls from the
  cu124 index.

Both fall back to CPU rather than taking the booth down, so check `/health`
after any dependency change — it reports `device` (what loaded) alongside
`device_requested` (what you asked for):

```bash
curl -s http://localhost:8090/health
```

If `device` says `cpu` while `device_requested` says `cuda`, the fallback fired;
the reason is in the server log.

**Caveat — this is a 70 W card.** 20 GB of VRAM, but only ~280 GB/s of memory
bandwidth, and LLM generation is bandwidth-bound.

Measured here: typhoon2 8B generates Thai at **50.1 tok/s** — against the
**50.3 tok/s** the old RTX 4060 Ti 8 GB managed (§4 of
[`docs/local-stack-design.md`](../docs/local-stack-design.md)). The bigger card
bought **no generation speed at all**, because the two have near-identical
bandwidth (288 vs ~280 GB/s). What it bought is capacity.

So: don't spend the headroom on a heavier quantization or a bigger model
expecting it to be free — it costs throughput roughly in proportion to size.
Spend it on keeping all three stages resident and getting STT off the CPU,
which is where the turn latency actually was.

## Tuning

Env vars, all optional:

| Var | Default | Note |
|---|---|---|
| `STT_MODEL_SIZE` | `large-v3-turbo` | distilled decoder; ~large-v3 quality, far faster. `large-v3` fits too (~4.7 GB) |
| `STT_DEVICE` | `cuda` | falls back to CPU int8 automatically |
| `STT_COMPUTE_TYPE` | `float16` | `int8_float16` saves VRAM you no longer need to save |
| `STT_BEAM_SIZE` | `1` | there is GPU headroom to raise it — measure on real Thai utterances |
| `TTS_DEVICE` | `cuda` | needs a CUDA torch build; ignored by CPU-only wheels |
| `TTS_MODEL_TH` / `TTS_MODEL_EN` | MMS | any VITS checkpoint |
| `TTS_ENGINE_TH` / `_EN` | `mms` | `f5` switches that language to F5-TTS-THAI |
| `TTS_REF_AUDIO_TH` | — | F5 reference clip; 5–15 s works best |
| `TTS_REF_TEXT_TH` | — | that clip's transcript, **exact** — F5 aligns against it |
| `TTS_SPEED_TH` / `_EN` | `0.95` / `1.0` | applies to whichever engine serves the language |
| `F5_STEPS` / `F5_CFG` | `32` / `2.0` | more steps = slower and better |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | upstream for the LLM proxy |
| `LLM_TIMEOUT_S` | `180` | |

For the best Thai word-error-rate, a Thai fine-tune of large-v3
(`biodatlab/whisper-th-large-v3-combined`, NECTEC's `Pathumma-whisper-th-large-v3`)
beats vanilla Whisper, at the cost of English. Both need converting with
`ct2-transformers-converter` first. 20 GB is enough to hold a Thai model and
turbo for English side by side — `get_tts()` is already per-language cached and
`get_stt()` would need the same treatment.

## F5-TTS for Thai (optional)

MMS Thai is a **male** voice, and `mms-tts-tha` / `mms-tts-eng` are different
speakers — so the on-prem nurse is two different people depending on language.
F5-TTS clones one reference clip, giving a female voice and the same speaker in
both languages.

```powershell
.\venv\Scripts\pip install f5-tts-th
$env:TTS_ENGINE_TH    = 'f5'
$env:TTS_ENGINE_EN    = 'f5'     # optional — see "one voice" below
$env:TTS_REF_AUDIO_TH = 'C:\path\to\nurse_ref.wav'
$env:TTS_REF_TEXT_TH  = '<exact transcript of that clip>'
```

**Engine is per language and both default to `mms`.** Setting only
`TTS_ENGINE_TH=f5` leaves English on MMS — which is a different (and, for
Thai, male) speaker, so the booth changes voice when the patient switches
language.

**One voice, both languages.** `TTS_REF_AUDIO_EN` / `TTS_REF_TEXT_EN` fall back
to the Thai pair, because cloning takes the *voice* from the reference and the
*language* from the text. One clip therefore covers both — the
[config.py](../hospital-hotline-assistant-api/app/config.py) intent that "the
nurse avatar is the same person in th and en", which MMS structurally cannot
meet. Verified here: the Thai reference produced English at 0.70 s for 1.86 s
of audio (2.6× realtime) and round-tripped exactly. Bear in mind
`F5-TTS-THAI` is a *Thai* fine-tune, so judge its English accent by ear before
committing — an exact round-trip proves intelligibility, not naturalness.

**ffmpeg is required and is not a pip dependency.** `f5_tts_th` decodes the
reference through pydub, which shells out to `ffmpeg`/`ffprobe`; without them
inference dies with `[WinError 2] The system cannot find the file specified`
*after* the model has loaded, so `/health` will happily report `engine: f5`
right up until the first request. Put both binaries on PATH.

Measured here (RTX 4000 SFF Ada), same Thai sentence:

| | MMS | F5 |
|---|---|---|
| Latency | 0.089 s | **0.72 s** |
| Realtime factor | 17–45× | **~4.1×** |
| Output rate | 16 kHz → resampled | **24 kHz native** |
| Whisper round-trip | `สวัสดีคัด กรณาบอกอาการของคุณ` | `สวัสดีค่ะ กรุณาบอกอาการของคุณ` (exact) |

So F5 costs roughly **+0.64 s per turn** and returns a cleaner round-trip. Note
that a round-trip proves *intelligibility, not tone* — whisper is context-robust
and will transcribe a tonally wrong vowel back to the right characters. Thai is
tonal and this is a medical booth: **have a native speaker score the output
before trusting it**, weighted toward the 183 digit-bearing strings in
`screening_criteria.json`.

If F5 fails at inference the engine is **demoted to MMS for the rest of the
process** rather than failing the turn; `/health` then shows `demoted_from` and
`demote_reason`.

## Why MMS-TTS and not piper

Piper ships **no Thai voice at all** — `rhasspy/piper-voices` has directories
for ~50 languages and `th` is not among them. Thai is the kiosk's default
language, so piper cannot serve the primary case. `facebook/mms-tts-tha` can.
(XTTS-v2 and Kokoro have no Thai either; Kokoro is excellent but English-only.)

Verified by round-tripping synthesized Thai back through whisper:

```
in : สวัสดีค่ะ กรุณาบอกอาการของคุณ
out: สวัสดีค่ะ การุณาบอกอาการของคุณ
```

Intelligible, one syllable off. It is noticeably more robotic than Google's
`th-TH-Chirp3-HD-Leda`, which is the accepted trade for going on-prem. If that
gap starts to matter, `VIZINTZOR/F5-TTS-THAI` is the natural next step —
markedly more natural, but slower, and TTS sits directly on the path to the
patient hearing a reply. Measure it against MMS on `/metrics` first.

Known gap: MMS reads digits and Latin text poorly in Thai. Numbers spoken to
the patient (queue numbers, room numbers, "level 3") should be spelled out in
Thai words before they reach TTS. That is a **text-normalization fix, not a
model one** — most Thai TTS has the same weakness, so switching models will not
resolve it.

## Two contract details that will break things if changed

1. **The voice name carries the language.** `speech_adapter.py` sends only
   `model`, `input`, `voice`, `response_format`, `sample_rate` — there is no
   language field. Hence `TTS_LOCAL_VOICE_TH=th` / `TTS_LOCAL_VOICE_EN=en`.
2. **Output must be 24 kHz.** The backend *raises* rather than resamples on a
   mismatch ([speech_adapter.py:209](../hospital-hotline-assistant-api/app/services/speech_adapter.py#L209)),
   because playing 22.05 kHz frames through the 24 kHz scheduler is a chipmunk
   voice. MMS emits 16 kHz, so the server resamples 3:2 and stamps the header.
