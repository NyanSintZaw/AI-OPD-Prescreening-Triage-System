"""On-prem speech sidecar: OpenAI-compatible STT + TTS for the triage backend.

Speaks exactly the two endpoints ``app/services/speech_adapter.py`` calls when
``STT_PROVIDER``/``TTS_PROVIDER`` are ``openai_compatible``, so patient audio
never leaves the hospital:

    POST /v1/audio/transcriptions   faster-whisper  (th + en)
    POST /v1/audio/speech           MMS-TTS (VITS)  (th + en)

Why MMS and not piper: piper ships no Thai voice at all (rhasspy/piper-voices
has no ``th`` directory), and Thai is the kiosk's default language.
``facebook/mms-tts-tha`` is the practical local option.

Two contract details the backend enforces, both handled here:

- ``/v1/audio/speech`` receives ``voice`` but NO language field, so the voice
  name IS the language selector — set ``TTS_LOCAL_VOICE_TH=th`` and
  ``TTS_LOCAL_VOICE_EN=en`` in the backend .env.
- The backend *raises* rather than resamples if the WAV comes back at the
  wrong rate (speech_adapter.py:209). MMS emits 16 kHz; the voice bridge wants
  24 kHz. We resample here, exactly 3:2, and stamp the header accordingly.

Run:
    pip install -r requirements.txt
    uvicorn server:app --host 0.0.0.0 --port 8090
"""

import io
import os
import time
import wave
import json
import logging
import tempfile
import threading

import httpx
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from scipy.signal import resample_poly

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
logger = logging.getLogger("local-speech")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# medium/int8 on CPU is the balance point for a kiosk: large-v3 is clearly
# better at Thai but pushes a 5 s utterance past the point where the pause
# feels broken. Both stay off the GPU on purpose — the 8B triage model already
# holds ~5.9 GB of the 8 GB card and must not contend during a live call.
STT_MODEL_SIZE = os.environ.get("STT_MODEL_SIZE", "medium")
STT_DEVICE = os.environ.get("STT_DEVICE", "cuda")
STT_COMPUTE_TYPE = os.environ.get("STT_COMPUTE_TYPE", "int8_float16")
STT_BEAM_SIZE = int(os.environ.get("STT_BEAM_SIZE", "1"))


def _preload_cuda_libs():
    """Make the pip-installed CUDA libraries loadable by ctranslate2.

    nvidia-cublas-cu12 / nvidia-cudnn-cu12 drop their .so files inside
    site-packages, which is not on the dynamic loader's search path — so
    faster-whisper on GPU dies with "Library libcublas.so.12 is not found".
    Setting LD_LIBRARY_PATH from inside the process is too late (the loader
    reads it at exec), so open them explicitly instead: once a library is in
    the process, later dlopen calls resolve to it.
    """
    import ctypes
    import glob
    import site

    roots = list(site.getsitepackages())
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass
    loaded = 0
    # cublasLt must precede cublas — cublas depends on it.
    for pattern in ("cudnn/lib/libcudnn*.so*", "cublas/lib/libcublasLt.so*",
                    "cublas/lib/libcublas.so*"):
        for root in roots:
            for path in sorted(glob.glob(os.path.join(root, "nvidia", pattern))):
                try:
                    ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                    loaded += 1
                except OSError:
                    pass
    return loaded

TTS_MODELS = {
    "th": os.environ.get("TTS_MODEL_TH", "facebook/mms-tts-tha"),
    "en": os.environ.get("TTS_MODEL_EN", "facebook/mms-tts-eng"),
}
MMS_SAMPLE_RATE = 16_000          # what VITS/MMS emits
DEFAULT_OUTPUT_RATE = 24_000      # what the voice bridge plays

# Upstream LLM. Ollama binds 127.0.0.1 by default and changing that needs root
# (it runs under systemd), so instead of exposing it we proxy to it from here —
# this process already listens on 0.0.0.0. One port leaves the machine, which
# is also what docs/local-stack-design.md specifies: no unauthenticated LLM
# endpoint on the hospital LAN.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "180"))

_LANG_ALIASES = {
    "th": "th", "tha": "th", "th-th": "th", "thai": "th",
    "en": "en", "eng": "en", "en-us": "en", "english": "en",
}


def normalize_language(value, default="en"):
    if not value:
        return default
    return _LANG_ALIASES.get(str(value).strip().lower(), default)


# ---------------------------------------------------------------------------
# Telemetry - what every stage cost, and what the hardware was doing while it
# ran. Sampled DURING the call on a background thread: reading utilisation
# after the work finishes just shows an idle machine.
# ---------------------------------------------------------------------------
_nvml = None
_nvml_handle = None
METRICS_KEEP = 200
_metrics = []
_metrics_lock = threading.Lock()


def _nvml_init():
    global _nvml, _nvml_handle
    if _nvml is None:
        try:
            import pynvml
            pynvml.nvmlInit()
            _nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml = pynvml
        except Exception:
            _nvml = False
    return _nvml


def gpu_sample():
    """(vram_used_mib, vram_total_mib, gpu_util_pct) or None."""
    nvml = _nvml_init()
    if not nvml:
        return None
    try:
        mem = nvml.nvmlDeviceGetMemoryInfo(_nvml_handle)
        util = nvml.nvmlDeviceGetUtilizationRates(_nvml_handle)
        return mem.used / 1048576, mem.total / 1048576, float(util.gpu)
    except Exception:
        return None


class Probe:
    """Samples GPU + CPU for the duration of one request."""

    def __init__(self, stage, interval=0.2):
        self.stage = stage
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self.gpu_utils = []
        self.cpu_utils = []
        self.peak_vram = 0.0
        self.total_vram = 0.0
        self.started = None
        self.elapsed = None

    def _loop(self):
        import psutil
        psutil.cpu_percent(None)          # prime the counter
        while not self._stop.is_set():
            s = gpu_sample()
            if s:
                used, total, util = s
                self.peak_vram = max(self.peak_vram, used)
                self.total_vram = total
                self.gpu_utils.append(util)
            self.cpu_utils.append(psutil.cpu_percent(None))
            self._stop.wait(self.interval)

    def __enter__(self):
        self.started = time.perf_counter()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.elapsed = time.perf_counter() - self.started

    @staticmethod
    def _avg(xs):
        return sum(xs) / len(xs) if xs else None

    def record(self, **extra):
        row = {
            "stage": self.stage,
            "latency_s": round(self.elapsed or 0, 3),
            "gpu_util_avg": self._avg(self.gpu_utils),
            "gpu_util_peak": max(self.gpu_utils) if self.gpu_utils else None,
            "cpu_util_avg": self._avg(self.cpu_utils),
            "vram_used_gb": round(self.peak_vram / 1024, 2) if self.peak_vram else None,
            "vram_total_gb": round(self.total_vram / 1024, 1) if self.total_vram else None,
            **extra,
        }
        with _metrics_lock:
            _metrics.append(row)
            del _metrics[:-METRICS_KEEP]
        return row


def _fmt_hw(row):
    bits = []
    if row.get("gpu_util_avg") is not None:
        bits.append(f"gpu={row['gpu_util_avg']:.0f}%/{row['gpu_util_peak']:.0f}pk")
    if row.get("cpu_util_avg") is not None:
        bits.append(f"cpu={row['cpu_util_avg']:.0f}%")
    if row.get("vram_used_gb"):
        bits.append(f"vram={row['vram_used_gb']:.1f}/{row['vram_total_gb']:.0f}GB")
    return "  ".join(bits)


# ---------------------------------------------------------------------------
# STT - faster-whisper, loaded once on first use
# ---------------------------------------------------------------------------
_stt_model = None
_stt_lock = threading.Lock()
# What STT actually ended up on, which may differ from the requested config
# when the GPU was unavailable and it fell back.
_stt_runtime = {"device": STT_DEVICE, "compute_type": STT_COMPUTE_TYPE}


def get_stt():
    global _stt_model
    with _stt_lock:
        if _stt_model is None:
            device, compute = STT_DEVICE, STT_COMPUTE_TYPE
            if device == "cuda":
                n = _preload_cuda_libs()
                logger.info("preloaded %d CUDA libraries", n)

            from faster_whisper import WhisperModel

            t0 = time.perf_counter()
            logger.info(
                "Loading STT: faster-whisper %s (%s/%s)",
                STT_MODEL_SIZE, device, compute,
            )
            try:
                _stt_model = WhisperModel(
                    STT_MODEL_SIZE, device=device, compute_type=compute
                )
            except Exception as exc:
                if device != "cuda":
                    raise
                # A booth that answers slowly still answers; one that refuses to
                # load STT is dead. Fall back rather than take the kiosk down.
                logger.warning(
                    "GPU STT unavailable (%s) — falling back to CPU int8", exc
                )
                device, compute = "cpu", "int8"
                _stt_model = WhisperModel(
                    STT_MODEL_SIZE, device=device, compute_type=compute
                )
            _stt_runtime.update(device=device, compute_type=compute)
            logger.info(
                "STT ready on %s in %.1f s", device, time.perf_counter() - t0
            )
    return _stt_model


# ---------------------------------------------------------------------------
# TTS - MMS-TTS (VITS) per language, loaded once on first use
# ---------------------------------------------------------------------------
_tts_cache = {}
_tts_lock = threading.Lock()


def get_tts(language):
    with _tts_lock:
        if language not in _tts_cache:
            import torch
            from transformers import AutoTokenizer, VitsModel

            name = TTS_MODELS[language]
            t0 = time.perf_counter()
            logger.info("Loading TTS: %s (%s)", name, language)
            tokenizer = AutoTokenizer.from_pretrained(name)
            model = VitsModel.from_pretrained(name)
            model.eval()
            if getattr(tokenizer, "is_uroman", False):
                # MMS checkpoints for some scripts need romanized input; if a
                # future voice needs it, feeding raw script silently produces
                # garbage, so say so rather than ship noise.
                logger.warning(
                    "%s expects uroman-romanized input; raw %s text will be mispronounced",
                    name, language,
                )
            _tts_cache[language] = (tokenizer, model, torch)
            logger.info("TTS %s ready in %.1f s", language, time.perf_counter() - t0)
    return _tts_cache[language]


def synthesize(text, language, output_rate):
    tokenizer, model, torch = get_tts(language)
    inputs = tokenizer(text, return_tensors="pt")
    with torch.no_grad():
        waveform = model(**inputs).waveform[0].cpu().numpy()
    return to_wav(waveform, MMS_SAMPLE_RATE, output_rate)


def to_wav(samples, source_rate, target_rate):
    """float32 [-1,1] at source_rate -> 16-bit PCM WAV at target_rate."""
    if target_rate != source_rate:
        # 16k -> 24k is exactly 3:2, so polyphase resampling is clean and cheap.
        g = np.gcd(int(target_rate), int(source_rate))
        samples = resample_poly(samples, target_rate // g, source_rate // g)

    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 1.0:                      # resampling can overshoot past full scale
        samples = samples / peak
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(target_rate)
        wav.writeframes(pcm.tobytes())
    return buf.getvalue(), len(pcm) / target_rate


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
app = FastAPI(title="Local Speech Sidecar")


@app.get("/")
def index():
    """A bare GET / used to 404, which reads like the server is down when it is
    only an unrouted path. Point it at what is actually here instead."""
    return {
        "service": "local-speech — on-prem STT / TTS / LLM gateway",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "routes": [
            "POST /v1/audio/transcriptions",
            "POST /v1/audio/speech",
            "POST /v1/chat/completions",
            "GET  /v1/models",
        ],
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "stt": {
            "model": STT_MODEL_SIZE,
            "device": STT_DEVICE,
            "compute_type": STT_COMPUTE_TYPE,
            "loaded": _stt_model is not None,
        },
        "tts": {"models": TTS_MODELS, "loaded": sorted(_tts_cache)},
        "llm": {"upstream": OLLAMA_URL, "reachable": _llm_reachable()},
        "output_sample_rate": DEFAULT_OUTPUT_RATE,
    }


def _llm_reachable():
    try:
        return httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2).status_code == 200
    except Exception:
        return False


@app.get("/metrics")
def metrics(stage: str | None = None, limit: int = 50):
    """Recent per-request timings and hardware usage.

    ``summary`` is per stage so a slow turn can be attributed without reading
    the log: p50/p95 latency, mean GPU and CPU utilisation, peak VRAM.
    """
    with _metrics_lock:
        rows = [r for r in _metrics if not stage or r["stage"] == stage]

    def pct(values, q):
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[min(int(len(ordered) * q), len(ordered) - 1)], 3)

    summary = {}
    for name in sorted({r["stage"] for r in rows}):
        group = [r for r in rows if r["stage"] == name]
        lat = [r["latency_s"] for r in group]
        gpu = [r["gpu_util_avg"] for r in group if r.get("gpu_util_avg") is not None]
        cpu = [r["cpu_util_avg"] for r in group if r.get("cpu_util_avg") is not None]
        vram = [r["vram_used_gb"] for r in group if r.get("vram_used_gb")]
        ttft = [r["ttft_s"] for r in group if r.get("ttft_s") is not None]
        summary[name] = {
            "count": len(group),
            "latency_p50": pct(lat, 0.5),
            "latency_p95": pct(lat, 0.95),
            "ttft_p50": pct(ttft, 0.5) if ttft else None,
            "gpu_util_avg": round(sum(gpu) / len(gpu), 1) if gpu else None,
            "cpu_util_avg": round(sum(cpu) / len(cpu), 1) if cpu else None,
            "vram_peak_gb": max(vram) if vram else None,
        }
    return {"summary": summary, "recent": rows[-limit:]}


@app.get("/v1/models")
async def list_models():
    """Speech models plus whatever the upstream LLM is serving."""
    ids = [STT_MODEL_SIZE] + list(TTS_MODELS.values())
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            ids += [m["name"] for m in r.json().get("models", [])]
    except Exception:
        logger.warning("upstream LLM not reachable at %s", OLLAMA_URL)
    return {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Pass-through to Ollama, so the backend reaches STT, TTS and the LLM on
    this one port. Streaming responses are forwarded chunk by chunk."""
    body = await request.body()
    try:
        streaming = json.loads(body).get("stream", False)
    except Exception:
        streaming = False

    url = f"{OLLAMA_URL}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    started = time.perf_counter()

    if not streaming:
        try:
            with Probe("llm") as probe:
                async with httpx.AsyncClient(timeout=LLM_TIMEOUT_S) as client:
                    r = await client.post(url, content=body, headers=headers)
        except Exception as exc:
            logger.exception("LLM proxy failed")
            raise HTTPException(502, f"LLM upstream error: {exc}") from exc
        usage = {}
        try:
            usage = r.json().get("usage") or {}
        except Exception:
            pass
        elapsed = probe.elapsed or 0.0
        out = usage.get("completion_tokens")
        row = probe.record(
            stream=False,
            prompt_tokens=usage.get("prompt_tokens"),
            output_tokens=out,
            # Non-streaming has no first token to time; this is the whole call.
            gen_tps=round(out / elapsed, 1) if out and elapsed else None,
        )
        logger.info(
            "LLM  prompt=%s output=%s latency=%.2fs (%.1f tok/s)  %s",
            usage.get("prompt_tokens", "?"), out or "?", elapsed,
            (out / elapsed) if out and elapsed else 0.0, _fmt_hw(row),
        )
        return Response(
            content=r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "application/json"),
        )

    async def relay():
        ttft = None
        chunks = 0
        probe = Probe("llm")
        probe.__enter__()
        try:
            async with httpx.AsyncClient(timeout=LLM_TIMEOUT_S) as client:
                async with client.stream(
                    "POST", url, content=body, headers=headers
                ) as r:
                    async for chunk in r.aiter_raw():
                        if ttft is None:
                            ttft = time.perf_counter() - started
                        chunks += 1
                        yield chunk
        except Exception as exc:
            logger.exception("LLM stream proxy failed")
            # The client is already receiving a 200 body here, so the only way
            # to signal failure is an SSE error event it can surface.
            yield f'data: {{"error":{json.dumps(str(exc))}}}\n\n'.encode()
        finally:
            probe.__exit__()
            elapsed = probe.elapsed or 0.0
            gen = (elapsed - ttft) if ttft is not None else None
            row = probe.record(
                stream=True,
                ttft_s=round(ttft, 3) if ttft is not None else None,
                chunks=chunks,
                # Chunks are near enough to tokens for a live rate readout.
                gen_tps=round(chunks / gen, 1) if gen and gen > 0 else None,
            )
            logger.info(
                "LLM  stream ttft=%s total=%.2fs chunks=%d (%s tok/s)  %s",
                f"{ttft:.2f}s" if ttft is not None else "n/a",
                elapsed, chunks,
                f"{chunks / gen:.1f}" if gen and gen > 0 else "?", _fmt_hw(row),
            )

    return StreamingResponse(relay(), media_type="text/event-stream")


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form(None),
    language: str = Form(None),
    response_format: str = Form("json"),
    temperature: float = Form(0.0),
):
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "empty audio")

    lang = normalize_language(language, default=None)
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio)
        path = f.name

    try:
        with Probe("stt") as probe:
            segments, info = get_stt().transcribe(
                path,
                language=lang,        # None lets whisper detect
                beam_size=STT_BEAM_SIZE,
                temperature=temperature,
                vad_filter=True,      # the bridge already endpoints, this trims edges
            )
            text = " ".join(seg.text for seg in segments).strip()
    except Exception as exc:
        logger.exception("STT failed")
        raise HTTPException(500, f"STT error: {exc}") from exc
    finally:
        os.unlink(path)

    elapsed = probe.elapsed or 0.0
    row = probe.record(
        language=info.language,
        audio_s=round(info.duration, 2),
        realtime_factor=round(info.duration / elapsed, 2) if elapsed else None,
        device=_stt_runtime["device"],
    )
    logger.info(
        "STT  lang=%s audio=%.1fs latency=%.2fs (%.1fx RT) on %s  %s  %r",
        info.language, info.duration, elapsed,
        (info.duration / elapsed) if elapsed else 0.0,
        _stt_runtime["device"], _fmt_hw(row), text[:50],
    )
    if response_format == "text":
        return Response(content=text, media_type="text/plain")
    return {"text": text}


class SpeechReq(BaseModel):
    input: str
    model: str = "mms-tts"
    # The backend sends no language field - the voice name carries it.
    voice: str = "en"
    response_format: str = "wav"
    sample_rate: int | None = None
    speed: float = 1.0


@app.post("/v1/audio/speech")
def speech(req: SpeechReq):
    text = (req.input or "").strip()
    if not text:
        raise HTTPException(400, "input must not be empty")

    language = normalize_language(req.voice)
    rate = req.sample_rate or DEFAULT_OUTPUT_RATE
    if req.response_format not in ("wav", "pcm"):
        # No mp3 encoder here on purpose; the voice bridge asks for wav.
        raise HTTPException(
            400, f"response_format {req.response_format!r} not supported; use wav"
        )

    try:
        with Probe("tts") as probe:
            wav, audio_seconds = synthesize(text, language, rate)
    except Exception as exc:
        logger.exception("TTS failed")
        raise HTTPException(500, f"TTS error: {exc}") from exc

    elapsed = probe.elapsed or 0.0
    row = probe.record(
        language=language,
        chars=len(text),
        audio_s=round(audio_seconds, 2),
        realtime_factor=round(audio_seconds / elapsed, 2) if elapsed else None,
    )
    logger.info(
        "TTS  lang=%s chars=%d audio=%.1fs latency=%.2fs (%.1fx RT)  %s",
        language, len(text), audio_seconds, elapsed,
        (audio_seconds / elapsed) if elapsed else 0.0, _fmt_hw(row),
    )
    if req.response_format == "pcm":
        return Response(content=wav[44:], media_type="application/octet-stream")
    return Response(content=wav, media_type="audio/wav")
