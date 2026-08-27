"""On-prem gateway: OpenAI-compatible STT + TTS + LLM for the triage backend.

Serves every endpoint the backend calls when ``AI_MODE=local``, so no patient
text or audio leaves the hospital:

    POST /v1/audio/transcriptions   faster-whisper  (th + en)
    POST /v1/audio/speech           MMS-TTS (VITS)  (th + en)
    POST /v1/chat/completions       pass-through proxy to Ollama

The module name predates the LLM proxy. Ollama stays bound to 127.0.0.1 and is
reached only through here, so one port leaves the machine and there is no
unauthenticated LLM endpoint on the hospital LAN.

STT and TTS take *different* CUDA paths and fail independently: STT runs on
ctranslate2 (needs the nvidia-cu12 wheels), TTS on torch (needs a CUDA build).
Both fall back to CPU rather than taking the booth down — ``GET /health``
reports what actually loaded next to what was requested.

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

import contextlib
import io
import os
import re
import time
import wave
import json
import logging
import tempfile
import threading

import httpx
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel
from scipy.signal import resample_poly

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
logger = logging.getLogger("local-speech")

# The per-turn story (STT -> LLM -> TTS) is the point of this log; everything
# else buries it. httpx narrates every upstream call, huggingface narrates
# every cache probe, and uvicorn repeats each request we already log with more
# detail. LOG_VERBOSE=1 puts them back when debugging transport itself.
LOG_VERBOSE = os.environ.get("LOG_VERBOSE", "").strip().lower() in ("1", "true", "yes")
if not LOG_VERBOSE:
    for _noisy in ("httpx", "httpcore", "huggingface_hub", "urllib3",
                   "filelock", "uvicorn.access"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

# Read local-speech/.env before any config below is evaluated, so engine and
# reference settings survive a restart instead of living in one shell's
# environment. Real environment variables still win, which keeps
# `TTS_ENGINE_TH=mms uvicorn ...` working as a one-off override.
try:
    from dotenv import load_dotenv

    _ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if load_dotenv(_ENV_FILE, override=False):
        logger.info("loaded config from %s", _ENV_FILE)
except ImportError:      # python-dotenv is optional; env vars alone still work
    pass

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# large-v3-turbo on the GPU: a distilled 4-layer decoder (against 32 in
# large-v3) makes it several times faster for near-identical transcription,
# and it is clearly better at Thai than medium. The 20 GB card holds it
# alongside the 8B triage model and TTS with room to spare, so nothing has to
# stay on the CPU any more. get_stt() falls back to CPU int8 on its own when
# CUDA is missing, so these defaults are safe on a machine without a GPU.
STT_MODEL_SIZE = os.environ.get("STT_MODEL_SIZE", "large-v3-turbo")
STT_DEVICE = os.environ.get("STT_DEVICE", "cuda")
STT_COMPUTE_TYPE = os.environ.get("STT_COMPUTE_TYPE", "float16")
# 5 rather than 1: measured on short clinical answers it cost nothing at all
# (0.24-0.26 s against 0.22-0.40 s greedy, on a 20 GB card that transcribes at
# 20x+ realtime), and beam search only helps once the audio is less clean than
# a test clip. There is no reason to run greedy here.
STT_BEAM_SIZE = int(os.environ.get("STT_BEAM_SIZE", "5"))


# os.add_dll_directory() returns a handle that un-registers the directory when
# it is closed — and it closes on garbage collection. Hold them for the life of
# the process or the search path silently empties again.
_dll_dirs = []


def _claim_cudnn(dirs):
    """Load torch's cuDNN first so it is the one the whole process uses.

    Three copies of ``cudnn64_9.dll`` ship in this venv — ctranslate2 bundles
    9.10 in its own package directory, the nvidia-cudnn-cu12 wheel has 9.24,
    torch/lib has 9.1 — and a Windows process can only hold ONE module per
    base name. Whichever loads first serves everyone.

    ctranslate2 loads its bundled copy out of its own directory, so PATH order
    cannot win the race: with STT warming before TTS, torch later asked 9.10
    for a symbol it does not export and the process died outright —
    ``Could not load symbol cudnnGetLibConfig. Error code 127``, exit code 9,
    no traceback. Claiming the name here, before either library initialises,
    is what actually decides it. torch's build is the fussy one; ctranslate2
    runs happily against it (measured: whisper on cuda, 8x realtime).
    """
    import ctypes

    for d in dirs:
        if not d.lower().endswith(os.path.join("torch", "lib")):
            continue
        dll = os.path.join(d, "cudnn64_9.dll")
        if not os.path.isfile(dll):
            continue
        try:
            ctypes.WinDLL(dll)
            logger.info("claimed cuDNN for the process: %s", dll)
        except OSError as exc:
            # Not fatal on its own — it only means the race is back open.
            logger.warning("could not preload torch cuDNN (%s): %s", dll, exc)
        return


def _preload_cuda_libs():
    """Make the pip-installed CUDA libraries loadable by ctranslate2.

    nvidia-cublas-cu12 / nvidia-cudnn-cu12 drop their shared libraries inside
    site-packages, which is not on the loader's search path — so faster-whisper
    on GPU dies with "Library libcublas.so.12 is not found" on Linux, or a bare
    "DLL load failed" on Windows. The two platforms need opposite fixes.

    Linux: setting LD_LIBRARY_PATH from inside the process is too late (the
    loader read it at exec), so open the libraries explicitly — once one is in
    the process, later dlopen calls resolve to it.

    Windows: ctranslate2 asks for its CUDA libraries by bare name
    (``LoadLibrary("cublas64_12.dll")``), and that resolves through the
    standard search order — which consults **PATH** but NOT the list built by
    os.add_dll_directory. add_dll_directory alone therefore fails with
    "Library cublas64_12.dll is not found or cannot be loaded" even though the
    directory is registered. Prepending to os.environ["PATH"] is what actually
    works, and unlike Linux it takes effect immediately: Windows reads PATH per
    LoadLibrary call, not once at exec. add_dll_directory is kept as well —
    it covers dependent-DLL resolution for extension modules, which PATH does
    not on Python 3.8+.
    """
    import glob
    import site

    roots = list(site.getsitepackages())
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass

    if os.name == "nt":
        found = []
        # ORDER IS LOad-BEARING. torch/lib must come first. Both torch and the
        # nvidia-cudnn-cu12 wheel ship a cudnn64_9.dll, and only ONE can be
        # resident: whichever is found first serves the whole process. With the
        # nvidia wheel winning, torch's CUDA kernels later ask for a symbol it
        # does not export and the process dies outright —
        #   "Could not load symbol cudnnGetLibConfig. Error code 127"
        # exit code 9, no traceback, mid-request. ctranslate2 is the tolerant
        # one of the two and runs fine against torch's build, so let torch's
        # win and keep the nvidia wheels as the fallback for a torch-less box.
        for pattern in (os.path.join("torch", "lib"),
                        os.path.join("nvidia", "*", "bin")):
            for root in roots:
                for path in sorted(glob.glob(os.path.join(root, pattern))):
                    if os.path.isdir(path) and path not in found:
                        found.append(path)
        for path in found:
            try:
                _dll_dirs.append(os.add_dll_directory(path))
            except OSError:
                pass
        if found:
            os.environ["PATH"] = os.pathsep.join(
                found + [os.environ.get("PATH", "")]
            )
        _claim_cudnn(found)
        return len(found)

    import ctypes

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
# VITS is small enough to run on the CPU, but on the GPU it is comfortably
# under the delay a patient reads as a pause. Needs a CUDA torch build — a
# CPU-only wheel silently ignores this, so get_tts() says so rather than
# leaving a "why is TTS still slow" mystery.
TTS_DEVICE = os.environ.get("TTS_DEVICE", "cuda")
DEFAULT_OUTPUT_RATE = 24_000      # what the voice bridge plays

# ── TTS engine per language ────────────────────────────────────────────────
# "mms" — facebook/mms-tts-* (VITS). One forward pass, ~57x realtime, but the
#         Thai checkpoint is a MALE voice and th/en are different speakers.
# "f5"  — F5-TTS-THAI voice cloning. Female nurse voice, and one reference
#         clip gives the same speaker in both languages. Flow matching, so
#         markedly slower: budget for it before switching a live booth.
# Per language so Thai can move to F5 while English stays on MMS.
TTS_ENGINES = {
    "th": os.environ.get("TTS_ENGINE_TH", "mms").strip().lower(),
    "en": os.environ.get("TTS_ENGINE_EN", "mms").strip().lower(),
}

# Each engine emits its own rate. F5 emits 24 kHz — exactly what the voice
# bridge plays — so its resample is a no-op; MMS emits 16 kHz and still needs
# the 3:2. This is why the source rate is per-engine and not a global.
MMS_SAMPLE_RATE = 16_000          # what VITS/MMS emits
F5_SAMPLE_RATE = 24_000           # what F5-TTS emits

# F5 is voice cloning: it needs a reference clip AND that clip's transcript.
# Both are required — a wrong transcript degrades output badly, because the
# model aligns the reference against it. Without them Thai falls back to MMS.
F5_MODEL = os.environ.get("F5_MODEL", "v1")
TTS_REF_AUDIO_TH = os.environ.get("TTS_REF_AUDIO_TH", "").strip()
TTS_REF_TEXT_TH = os.environ.get("TTS_REF_TEXT_TH", "").strip()
# English falls back to the Thai clip on purpose: cloning takes the voice from
# the reference and the language from the text, so ONE clip gives the same
# nurse in both languages — which is what config.py asks for and what MMS
# cannot do (mms-tts-tha and mms-tts-eng are different speakers, and the Thai
# one is male). Set these only if you want a separate English reference.
TTS_REF_AUDIO_EN = os.environ.get("TTS_REF_AUDIO_EN", "").strip() or TTS_REF_AUDIO_TH
TTS_REF_TEXT_EN = os.environ.get("TTS_REF_TEXT_EN", "").strip() or TTS_REF_TEXT_TH
_F5_REFS = {
    "th": (TTS_REF_AUDIO_TH, TTS_REF_TEXT_TH),
    "en": (TTS_REF_AUDIO_EN, TTS_REF_TEXT_EN),
}
# Sampling knobs. 32 steps / cfg 2.0 are the F5 defaults; more steps is
# slower and better, and latency is the scarce resource here.
F5_STEPS = int(os.environ.get("F5_STEPS", "32"))
F5_CFG = float(os.environ.get("F5_CFG", "2.0"))
# Slightly under 1.0 reads as calmer and is easier to follow in a noisy
# booth — an unhurried nurse rather than a brisk one.
TTS_SPEED_TH = float(os.environ.get("TTS_SPEED_TH", "0.95"))
TTS_SPEED_EN = float(os.environ.get("TTS_SPEED_EN", "1.0"))
_ENGINE_SPEED = {"th": TTS_SPEED_TH, "en": TTS_SPEED_EN}

# Upstream LLM. Ollama binds 127.0.0.1 by default and changing that needs root
# (it runs under systemd), so instead of exposing it we proxy to it from here —
# this process already listens on 0.0.0.0. One port leaves the machine, which
# is also what docs/local-stack-design.md specifies: no unauthenticated LLM
# endpoint on the hospital LAN.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
# Pin this model in VRAM at startup so the first patient never pays the load.
# A cold 8B costs ~11 s here and has been measured at 75 s on a cold page
# cache, against the backend's model timeout — so the first turn after any
# restart simply dies. OLLAMA_KEEP_ALIVE is NOT a reliable way to do this:
# Ollama's background service respawns with its own environment and ignored
# it (ollama ps still showed a 4-minute expiry). keep_alive=-1 on a native
# /api/generate call does work — that reports "Forever".
LLM_PIN_MODEL = os.environ.get("LLM_PIN_MODEL", "").strip()
# How often to re-check that the pin survived, in seconds. 0 disables.
# This Ollama is shared: another client requesting a different model evicts
# ours, which destroys keep_alive=-1 and leaves the next patient turn paying a
# cold reload (~6 s warm disk, ~75 s cold — past the backend's timeout).
# Ollama's own env vars are not usable here; its process runs under another
# account and cannot be restarted, so OLLAMA_KEEP_ALIVE / MAX_LOADED_MODELS are
# silently ignored. Re-pinning through the API is the only lever left.
LLM_PIN_INTERVAL_S = float(os.environ.get("LLM_PIN_INTERVAL_S", "60"))

# Browsers refuse a cross-origin fetch without these headers, so the kiosk on
# :5173 and the /test page cannot reach the gateway without them. Default is
# permissive because the gateway has no authentication anyway — CORS is not
# what is keeping anyone out, the firewall and the tailnet ACL are. Narrow it
# with CORS_ORIGINS="http://kiosk:5173,http://localhost:5173" when the origins
# are known.
CORS_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()
]
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "180"))

_LANG_ALIASES = {
    "th": "th", "tha": "th", "th-th": "th", "thai": "th",
    "en": "en", "eng": "en", "en-us": "en", "english": "en",
}


def normalize_language(value, default="en"):
    if not value:
        return default
    return _LANG_ALIASES.get(str(value).strip().lower(), default)


# Thai script is a contiguous, unambiguous block — nothing else uses it.
_THAI_SCRIPT = re.compile(r"[฀-๿]")


def resolve_speech_language(voice, text):
    """Language for synthesis. The voice name is the contract, Thai script wins.

    ``/v1/audio/speech`` carries no language field, so the voice name IS the
    selector. That makes a backend misconfiguration silent and severe: the
    default of ``TTS_LOCAL_VOICE_TH`` is ``alloy`` (an OpenAI voice name that
    means nothing here), which falls through to the ``en`` default — so Thai
    text was synthesized with the English voice and a Thai patient heard
    English, with no error raised anywhere.

    Thai script cannot appear in English text, so use it as the tiebreak and
    say loudly when the two disagree.
    """
    known = str(voice or "").strip().lower() in _LANG_ALIASES
    language = normalize_language(voice)
    if known:
        # An explicit 'th'/'en' is the backend stating the session language,
        # and it wins. Script is NOT a safe override here: the kiosk greets by
        # name, so an English line legitimately contains Thai characters
        # ("Hello สมชาย ใจดี, welcome") and any-Thai-character detection would
        # flip the whole utterance to the Thai voice. Only flag a lopsided
        # mismatch, which means a real backend bug rather than a proper noun.
        thai = len(_THAI_SCRIPT.findall(text or ""))
        letters = sum(1 for c in (text or "") if c.isalpha())
        if letters and language == "en" and thai / letters > 0.6:
            logger.warning(
                "voice='en' but %.0f%% of the text is Thai script — check the "
                "session language; synthesizing as en as asked.",
                100 * thai / letters,
            )
        return language

    # Unrecognised voice name (the backend default 'alloy' is an OpenAI voice,
    # meaningless here) would otherwise fall through to the 'en' default and
    # speak Thai text in the English voice, silently. Here script IS the best
    # signal available, because the voice name carries none.
    if _THAI_SCRIPT.search(text or ""):
        logger.warning(
            "voice=%r is not a language selector and the text contains Thai — "
            "synthesizing as th. Set TTS_LOCAL_VOICE_TH=th / _EN=en in the "
            "backend .env.", voice,
        )
        return "th"
    logger.warning(
        "voice=%r is not a language selector — defaulting to %r. The "
        "backend should send TTS_LOCAL_VOICE_TH/EN as 'th'/'en'.",
        voice, language,
    )
    return language


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
# Cache entries are dicts, not tuples, because the two engines carry
# different payloads. Every entry has: engine, device, sample_rate.
_tts_cache = {}
_tts_lock = threading.Lock()
# What TTS actually ended up as, per language — which may differ from what was
# requested when torch turned out to be a CPU-only build, or when F5 could not
# load and Thai fell back to MMS. Keyed by language because the engine is now
# a per-language choice, so one global value could not express it.
_tts_runtime = {}


def _resolve_torch_device(requested):
    """Requested device, downgraded to cpu when this torch cannot do CUDA."""
    import torch

    if requested == "cuda" and not torch.cuda.is_available():
        # The usual cause is the CPU-only torch wheel, which is easy to
        # install by accident and impossible to spot from the outside.
        logger.warning(
            "TTS_DEVICE=cuda but this torch build reports no CUDA (%s) — "
            "running TTS on CPU", torch.__version__,
        )
        return "cpu"
    return requested


def _load_mms(language, device):
    """facebook/mms-tts-* (VITS). One forward pass per utterance."""
    import torch
    from transformers import AutoTokenizer, VitsModel

    name = TTS_MODELS[language]
    logger.info("Loading TTS: %s (%s, mms)", name, language)
    tokenizer = AutoTokenizer.from_pretrained(name)
    model = VitsModel.from_pretrained(name)
    model.eval()
    # Pace is a model attribute on VITS, not an inference argument as it is on
    # F5 — so set it once here. Doing it per call would mutate state shared by
    # every in-flight request.
    speed = _ENGINE_SPEED.get(language, 1.0)
    if speed and speed != 1.0 and hasattr(model, "speaking_rate"):
        model.speaking_rate = speed
        logger.info("TTS %s speaking_rate=%.2f", language, speed)
    try:
        model = model.to(device)
    except Exception as exc:      # noqa: BLE001 — a slow booth beats a dead one
        logger.warning("TTS could not move to %s (%s) — using CPU", device, exc)
        device = "cpu"
        model = model.to("cpu")
    if getattr(tokenizer, "is_uroman", False):
        # MMS checkpoints for some scripts need romanized input; if a
        # future voice needs it, feeding raw script silently produces
        # garbage, so say so rather than ship noise.
        logger.warning(
            "%s expects uroman-romanized input; raw %s text will be mispronounced",
            name, language,
        )
    return {
        "engine": "mms",
        # NOT "model": that key already holds the torch module below, and a
        # duplicate silently kept the module — which then reached
        # jsonable_encoder via /health and 500'd on 'torch.dtype'.
        "model_name": name,
        "device": device,
        "sample_rate": MMS_SAMPLE_RATE,
        "tokenizer": tokenizer,
        "model": model,
        "torch": torch,
    }


def _load_f5(language, device):
    """F5-TTS voice cloning. Raises so get_tts() can fall back to MMS.

    The reference clip and its transcript are read and validated HERE, once,
    and reused for every request — re-reading env or stat-ing the file per
    utterance would put filesystem latency on the patient's critical path.
    """
    ref_audio, ref_text = _F5_REFS.get(language, ("", ""))
    suffix = language.upper()
    if not ref_audio or not os.path.isfile(ref_audio):
        raise RuntimeError(
            f"TTS_REF_AUDIO_{suffix} is unset or not a file ({ref_audio!r})"
        )
    if not ref_text:
        # A missing transcript is worse than a missing clip: F5 still runs but
        # aligns against nothing, and the output degrades in a way that is easy
        # to mistake for the model simply being bad.
        raise RuntimeError(
            f"TTS_REF_TEXT_{suffix} is unset (F5 needs the clip's transcript)"
        )

    from f5_tts_th.tts import TTS

    logger.info("Loading TTS: F5-TTS-THAI %s (%s, f5, %s)", F5_MODEL, language, device)
    try:
        tts = TTS(model=F5_MODEL, device=device)
    except TypeError:
        # Not every f5-tts-th build accepts a device kwarg; those place the
        # model by torch's own default instead.
        logger.info("f5_tts_th.TTS takes no device kwarg — using torch default")
        tts = TTS(model=F5_MODEL)

    return {
        "engine": "f5",
        "model_name": f"F5-TTS-THAI/{F5_MODEL}",
        "device": device,
        "sample_rate": F5_SAMPLE_RATE,
        "tts": tts,
        "ref_audio": ref_audio,
        "ref_text": ref_text,
    }


def get_tts(language):
    """Load (once) and return the cache entry for a language.

    Fallback chain, mirroring get_stt(): F5 on the requested device → F5 on
    CPU → MMS. A booth that sounds worse still triages; one that cannot speak
    is dead.
    """
    with _tts_lock:
        if language in _tts_cache:
            return _tts_cache[language]

        t0 = time.perf_counter()
        requested = TTS_ENGINES.get(language, "mms")
        device = _resolve_torch_device(TTS_DEVICE)
        entry = None

        if requested == "f5":
            try:
                entry = _load_f5(language, device)
            except Exception as exc:      # noqa: BLE001
                if device != "cpu":
                    logger.warning("F5 TTS unavailable on %s (%s) — retrying on CPU",
                                   device, exc)
                    try:
                        entry = _load_f5(language, "cpu")
                    except Exception as exc2:   # noqa: BLE001
                        logger.warning("F5 TTS unavailable on CPU too (%s) — "
                                       "falling back to MMS for %s", exc2, language)
                else:
                    logger.warning("F5 TTS unavailable (%s) — falling back to MMS "
                                   "for %s", exc, language)
        elif requested != "mms":
            logger.warning("unknown TTS_ENGINE_%s=%r — using mms",
                           language.upper(), requested)

        if entry is None:
            entry = _load_mms(language, device)

        _tts_cache[language] = entry
        _tts_runtime[language] = {
            "engine": entry["engine"],
            "model": entry["model_name"],
            "engine_requested": requested,
            "device": entry["device"],
            "sample_rate": entry["sample_rate"],
        }
        logger.info(
            "TTS %s ready: %s on %s in %.1f s",
            language, entry["engine"], entry["device"], time.perf_counter() - t0,
        )
    return _tts_cache[language]


def _synth_mms(entry, text, speed):
    # speed is unused here: VITS pace is baked in at load (see _load_mms).
    torch = entry["torch"]
    tokenizer, model, device = entry["tokenizer"], entry["model"], entry["device"]
    inputs = tokenizer(text, return_tensors="pt")
    # Inputs must sit on the same device as the weights, or torch raises.
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        return model(**inputs).waveform[0].float().cpu().numpy()


def _synth_f5(entry, text, speed):
    # f5_tts_th prints "Converting audio...", the reference text, the full
    # gen_text and a tqdm bar straight to stdout/stderr on EVERY call, which
    # drowns the per-turn log. Capture it and only surface it if the call
    # fails, where it is actually diagnostic. LOG_VERBOSE=1 lets it through.
    if LOG_VERBOSE:
        return _synth_f5_inner(entry, text, speed)
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            return _synth_f5_inner(entry, text, speed)
    except Exception:
        noise = sink.getvalue().strip()
        if noise:
            logger.warning("F5 output before the failure: %s", noise[-800:])
        raise


def _synth_f5_inner(entry, text, speed):
    wav = entry["tts"].infer(
        ref_audio=entry["ref_audio"],
        ref_text=entry["ref_text"],
        gen_text=text,
        step=F5_STEPS,
        cfg=F5_CFG,
        speed=speed,
    )
    # Some builds return (waveform, sample_rate) rather than a bare array.
    if isinstance(wav, tuple):
        wav = wav[0]
    # reshape(-1), NOT squeeze(): squeeze turns a 1-sample result into a
    # 0-d array, which survives every check in to_wav until len(pcm) raises
    # "object of type 'numpy.int16' has no len()" — a 500 with no clue that
    # TTS produced nothing. reshape(-1) always yields 1-D.
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    if wav.size < 2:
        # Degenerate output. Raise so synthesize() can demote to MMS and the
        # patient still hears the line, rather than serving silence.
        raise RuntimeError(f"F5 returned {wav.size} samples (no usable audio)")
    return wav


def _demote_to_mms(language, reason):
    """Swap a language's engine to MMS for the rest of the process."""
    with _tts_lock:
        entry = _load_mms(language, _resolve_torch_device(TTS_DEVICE))
        _tts_cache[language] = entry
        _tts_runtime[language] = {
            "engine": entry["engine"],
            "model": entry["model_name"],
            "engine_requested": TTS_ENGINES.get(language, "mms"),
            "device": entry["device"],
            "sample_rate": entry["sample_rate"],
            "demoted_from": "f5",
            "demote_reason": str(reason)[:200],
        }
    return entry


def synthesize(text, language, output_rate):
    """Returns (wav_bytes, audio_seconds) — unchanged contract for speech()."""
    entry = get_tts(language)
    speed = _ENGINE_SPEED.get(language, 1.0)
    if entry["engine"] == "f5":
        try:
            waveform = _synth_f5(entry, text, speed)
        except Exception as exc:      # noqa: BLE001
            # Loading F5 successfully does NOT mean it can infer: the reference
            # decode shells out to ffmpeg, and CUDA kernels resolve lazily — so
            # the first real failure lands here, not in the loader. A dead turn
            # is worse than a plainer voice, so demote for the rest of the
            # process rather than 500 on this turn and every later one.
            logger.exception("F5 inference failed for %s — demoting to MMS", language)
            entry = _demote_to_mms(language, exc)
            waveform = _synth_mms(entry, text, speed)
    else:
        waveform = _synth_mms(entry, text, speed)
    # Per-engine source rate: F5 already emits 24 kHz so to_wav's resample is a
    # no-op, while MMS's 16 kHz still gets the exact 3:2. Read AFTER any
    # demotion above, or a demoted turn would be resampled at the wrong rate.
    return to_wav(waveform, entry["sample_rate"], output_rate)


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
# Load the models at startup instead of on the first request. Lazily loading
# them means the FIRST PATIENT of the day pays the cost: F5 takes ~13 s from a
# warm disk cache and minutes on a cold one, while the backend's TTS client
# gives up after speech_http_timeout_s (30 s) — so that turn dies with an
# httpx.ReadTimeout and the booth greets nobody. Warming runs on a background
# thread so the port still opens immediately and /health answers while it
# works; watch "loaded" there to know when it is actually ready.
PREWARM = os.environ.get("PREWARM", "1").strip().lower() not in ("0", "false", "no")


def _pin_llm(quiet=False):
    """Load LLM_PIN_MODEL and hold it in VRAM indefinitely."""
    if not LLM_PIN_MODEL:
        logger.info("prewarm: LLM_PIN_MODEL unset — the LLM will load on first use")
        return
    # No prompt: Ollama loads and holds the model without generating.
    body = {"model": LLM_PIN_MODEL, "keep_alive": -1}
    t0 = time.perf_counter()
    r = httpx.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=600)
    r.raise_for_status()
    if not quiet:
        logger.info("prewarm: LLM %s pinned in %.1f s",
                    LLM_PIN_MODEL, time.perf_counter() - t0)


def _norm_model(name):
    """Ollama always reports an explicit tag; config usually omits it, and a
    bare name means :latest. Comparing them raw made the watchdog declare an
    eviction on every tick while the model was plainly resident."""
    name = (name or "").strip()
    return name if ":" in name else f"{name}:latest"


def _llm_resident():
    """Model names Ollama currently holds in VRAM."""
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        r.raise_for_status()
        return {_norm_model(m.get("name", "")) for m in r.json().get("models", [])}
    except Exception:      # noqa: BLE001 — a failed check just means try again
        return None


def _pin_watchdog():
    """Re-pin the triage model whenever it gets evicted.

    Logs every re-pin, so the frequency of eviction is visible rather than
    showing up as an occasional mysteriously slow first turn.
    """
    while True:
        time.sleep(LLM_PIN_INTERVAL_S)
        resident = _llm_resident()
        if resident is not None and _norm_model(LLM_PIN_MODEL) not in resident:
            logger.warning(
                "LLM %s was evicted (resident: %s) — re-pinning",
                LLM_PIN_MODEL, ", ".join(sorted(resident)) or "nothing",
            )
        try:
            # Unconditional rather than only on eviction. The pin has been
            # observed lapsing to a ~5 min expiry after other traffic — most
            # likely a foreign request reloading the model without keep_alive —
            # and by the time it has actually disappeared a patient is already
            # waiting on the reload. Re-asserting every tick is a bare load
            # call with no generation, so it is nearly free insurance. (A plain
            # chat call through this gateway does NOT clear the pin; that was
            # measured, so this is not the mechanism.)
            _pin_llm(quiet=True)
        except Exception:      # noqa: BLE001
            logger.exception("re-pin failed; the next turn may pay a cold load")


def _prewarm():
    for name, fn in (
        ("STT", lambda: get_stt()),
        ("LLM", _pin_llm),
        # Only the languages an engine is configured for; get_tts() falls back
        # to MMS by itself if F5 cannot load.
        *[(f"TTS {lang}", (lambda l=lang: get_tts(l))) for lang in TTS_ENGINES],
    ):
        try:
            t0 = time.perf_counter()
            fn()
            logger.info("prewarm: %s ready in %.1f s", name, time.perf_counter() - t0)
        except Exception:      # noqa: BLE001 — a cold model is not fatal, it just costs the first turn
            logger.exception("prewarm: %s failed; it will load on first use", name)


@contextlib.asynccontextmanager
async def lifespan(_app):
    if PREWARM:
        threading.Thread(target=_prewarm, daemon=True, name="prewarm").start()
        if LLM_PIN_MODEL and LLM_PIN_INTERVAL_S > 0:
            threading.Thread(target=_pin_watchdog, daemon=True,
                             name="pin-watchdog").start()
    else:
        logger.info("PREWARM disabled — models load on first request")
    yield


app = FastAPI(title="Local AI Gateway (STT / TTS / LLM)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
            "POST /v1/embeddings, /v1/completions  (relayed to Ollama)",
            "GET  /api/tags, /api/ps, /api/version  (relayed to Ollama)",
            "GET  /test   (browser connectivity check)",
        ],
    }


@app.get("/test", response_class=HTMLResponse)
def test_page():
    """Browser-side connectivity check, served from the gateway itself.

    Same-origin on purpose: opening it from :8090 means a failure here is the
    gateway, not CORS or a stale file:// copy. It exercises /health,
    /v1/chat/completions, /v1/audio/speech and /v1/audio/transcriptions the
    way the kiosk does, so "can the frontend reach this box" gets a yes/no
    from the machine that is actually asking.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_page.html")
    try:
        with open(path, encoding="utf-8") as fh:
            return HTMLResponse(fh.read())
    except OSError as exc:
        raise HTTPException(500, f"test page missing: {exc}") from exc


@app.get("/health")
def health():
    return {
        "status": "ok",
        "stt": {
            "model": STT_MODEL_SIZE,
            # Requested vs actual: a GPU that failed to load falls back to CPU
            # silently, and "why is every turn slow" is answered right here.
            "device": _stt_runtime["device"],
            "device_requested": STT_DEVICE,
            "compute_type": _stt_runtime["compute_type"],
            "loaded": _stt_model is not None,
        },
        "tts": {
            # The MMS checkpoints, which are only in use where runtime says
            # engine=mms. Reading this as "what is loaded" led a teammate to
            # diagnose F5 as inactive while it was serving every request —
            # runtime[lang].model is the authoritative answer.
            "mms_models_configured": TTS_MODELS,
            "engines_requested": TTS_ENGINES,
            "device_requested": TTS_DEVICE,
            # Per language, what actually loaded. A Thai row reading
            # engine=mms while engine_requested=f5 is the F5 fallback having
            # fired — the reason is one warning back in the log.
            "runtime": _tts_runtime,
            "loaded": sorted(_tts_cache),
            "speed": _ENGINE_SPEED,
        },
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
    logger.info("<- LLM   from backend: %.0f KB prompt%s",
                len(body) / 1024, " (streaming)" if streaming else "")

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
            "-> LLM   %s tokens back to backend  (%s prompt, %.2fs = "
            "%.1f tok/s)  %s",
            out or "?", usage.get("prompt_tokens", "?"), elapsed,
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


# ── Ollama passthrough ─────────────────────────────────────────────────────
# Ollama binds 127.0.0.1 and stays there; this process is what makes it
# reachable from another machine. Everything below is a thin relay to it.
#
# The mutating endpoints are DELIBERATELY not relayed. /api/delete,
# /api/pull, /api/create, /api/copy and /api/push let any caller destroy or
# replace the triage model, and this port has no authentication — publishing
# them would mean anyone who can route here can wipe the booth's LLM. Run
# those on the host itself.
_OLLAMA_BLOCKED = {
    "/api/delete", "/api/pull", "/api/push", "/api/create", "/api/copy",
}


async def _relay_to_ollama(request: Request, path: str) -> Response:
    """Forward one request to Ollama and hand back exactly what it said."""
    if path in _OLLAMA_BLOCKED:
        raise HTTPException(
            403,
            f"{path} is not exposed: it can modify or delete models and this "
            "port is unauthenticated. Run it on the host.",
        )
    body = await request.body()
    url = f"{OLLAMA_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_S) as client:
            r = await client.request(
                request.method, url, content=body or None,
                headers={"Content-Type": request.headers.get(
                    "content-type", "application/json")},
                params=dict(request.query_params),
            )
    except Exception as exc:
        logger.exception("Ollama relay failed for %s", path)
        raise HTTPException(502, f"Ollama upstream error: {exc}") from exc
    return Response(
        content=r.content, status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )


@app.post("/v1/embeddings")
async def v1_embeddings(request: Request):
    return await _relay_to_ollama(request, "/v1/embeddings")


@app.post("/v1/completions")
async def v1_completions(request: Request):
    return await _relay_to_ollama(request, "/v1/completions")


@app.get("/api/tags")
async def api_tags(request: Request):
    return await _relay_to_ollama(request, "/api/tags")


@app.get("/api/ps")
async def api_ps(request: Request):
    return await _relay_to_ollama(request, "/api/ps")


@app.get("/api/version")
async def api_version(request: Request):
    return await _relay_to_ollama(request, "/api/version")


@app.post("/api/show")
async def api_show(request: Request):
    return await _relay_to_ollama(request, "/api/show")


@app.api_route("/api/{path:path}", methods=["GET", "POST"])
async def api_catchall(request: Request, path: str):
    """Anything else under /api — blocked ones answer 403 with the reason,
    so a caller is told rather than left guessing at a 404."""
    return await _relay_to_ollama(request, f"/api/{path}")


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
    logger.info("<- STT   from backend: %s, %.0f KB", file.filename or "audio",
                len(audio) / 1024)

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
        "-> STT   %r  (lang=%s, %.1fs audio in %.2fs = %.1fx RT, %s)  %s",
        text[:70], info.language, info.duration, elapsed,
        (info.duration / elapsed) if elapsed else 0.0,
        _stt_runtime["device"], _fmt_hw(row),
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

    language = resolve_speech_language(req.voice, text)
    logger.info("<- TTS   from backend: %s, %d chars: %r",
                language, len(text), text[:60])
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
    # Which engine produced this. Without it /metrics cannot attribute a
    # latency to mms vs f5, which is the whole point of running both.
    rt = _tts_runtime.get(language, {})
    row = probe.record(
        language=language,
        engine=rt.get("engine"),
        device=rt.get("device"),
        chars=len(text),
        audio_s=round(audio_seconds, 2),
        realtime_factor=round(audio_seconds / elapsed, 2) if elapsed else None,
    )
    logger.info(
        "-> TTS   %.0f KB of audio sent to backend  (%s, %.1fs speech in "
        "%.2fs = %.1fx RT, %s)  %s",
        len(wav) / 1024, rt.get("engine", "?"), audio_seconds, elapsed,
        (audio_seconds / elapsed) if elapsed else 0.0,
        rt.get("device", "?"), _fmt_hw(row),
    )
    if req.response_format == "pcm":
        return Response(content=wav[44:], media_type="application/octet-stream")
    return Response(content=wav, media_type="audio/wav")
