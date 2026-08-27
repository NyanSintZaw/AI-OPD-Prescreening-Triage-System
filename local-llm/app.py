"""
Hospital AI avatar booth - minimal testable prototype.

Pipeline:  patient ID -> load record -> chat (text or voice) -> reply
Single user at a time. In-memory sessions with auto-timeout wipe.

Run:
    pip install -r requirements.txt
    ollama serve            # (in another terminal, if not already running)
    ollama pull llama3.2
    uvicorn app:app --host 0.0.0.0 --port 8000

Then open http://localhost:8000 in a browser.

Text chat works with just Ollama installed.
Voice (STT/TTS) activates automatically if faster-whisper / piper are installed.
"""

import os
import json
import time
import uuid
import shutil
import tempfile
import threading
import subprocess

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "scb10x/llama3.1-typhoon2-8b-instruct")
SESSION_TIMEOUT = 90          # seconds of inactivity before a session is wiped
MAX_HISTORY_MESSAGES = 20     # cap history so the context window can't overflow

# ---------------------------------------------------------------------------
# Mock patient "database" - replace with a real lookup later
# ---------------------------------------------------------------------------
PATIENTS = {
    "1001": {
        "name": "Alice Johnson",
        "history": "Type 2 diabetes. Last visit 2026-06-10 for a foot check. "
                   "Allergic to penicillin. Next appointment: 2026-08-20, 10:30am, Dr. Lee.",
    },
    "1002": {
        "name": "Bob Smith",
        "history": "Hypertension, prescribed lisinopril. "
                   "Follow-up due for a blood pressure review. No known allergies.",
    },
}

# ---------------------------------------------------------------------------
# Session store (single active user, but keyed so a new ID cleanly replaces)
# ---------------------------------------------------------------------------
sessions = {}   # session_id -> {"patient_id", "history", "last_activity"}


def purge_expired():
    now = time.time()
    for sid in list(sessions.keys()):
        if now - sessions[sid]["last_activity"] > SESSION_TIMEOUT:
            del sessions[sid]


def get_session(session_id):
    purge_expired()
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session expired or not found. Start again.")
    s["last_activity"] = time.time()
    return s


def build_system_prompt(patient):
    return (
        "You are a friendly hospital front-desk assistant at an information booth. "
        "You help ONE patient at a time with non-clinical questions: their appointment "
        "times, general directions, and reading back information already on their record. "
        "You must NOT give medical advice, diagnoses, or medication guidance - for anything "
        "clinical, tell the patient a staff member or doctor will help them. "
        "Keep answers short and clear.\n\n"
        f"Current patient name: {patient['name']}.\n"
        f"Record on file: {patient['history']}\n"
        "Only discuss THIS patient's information."
    )


# ---------------------------------------------------------------------------
# GPU sampling - peak VRAM / mean utilisation *while the model is generating*.
# Uses NVML in-process if nvidia-ml-py is installed, else shells out to
# nvidia-smi. Silently reports nothing on a CPU-only box.
# ---------------------------------------------------------------------------
_nvml = None            # None = not tried, False = unavailable, else the module
_nvml_handle = None


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
    """(vram_used_mib, vram_total_mib, util_percent) or None."""
    nvml = _nvml_init()
    if nvml:
        try:
            mem = nvml.nvmlDeviceGetMemoryInfo(_nvml_handle)
            util = nvml.nvmlDeviceGetUtilizationRates(_nvml_handle)
            return mem.used / 1048576, mem.total / 1048576, float(util.gpu)
        except Exception:
            return None
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()[0]
        used, total, util = (float(x) for x in out.split(","))
        return used, total, util
    except Exception:
        return None


class GpuWatch:
    """Polls the GPU on a background thread for the life of one generation."""

    def __init__(self, interval=0.25):
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self.peak_vram = 0.0
        self.total_vram = 0.0
        self.utils = []

    def _loop(self):
        while not self._stop.is_set():
            s = gpu_sample()
            if s:
                used, total, util = s
                self.peak_vram = max(self.peak_vram, used)
                self.total_vram = total
                self.utils.append(util)
            self._stop.wait(self.interval)

    def __enter__(self):
        if gpu_sample() is None:      # no GPU - don't spin a useless thread
            return self
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def mean_util(self):
        return sum(self.utils) / len(self.utils) if self.utils else None

    @property
    def peak_util(self):
        return max(self.utils) if self.utils else None


def print_stats(st):
    line = "-" * 46
    print(line)
    print(f"Model: {st['model']}")
    print(f"Prompt: {st['prompt_tokens']} tokens")
    print(f"Output: {st['output_tokens']} tokens")
    print(f"TTFT: {st['ttft_s']:.2f} s" if st["ttft_s"] else "TTFT: n/a")
    if st["load_s"] > 0.05:      # cold start - otherwise TTFT looks inexplicably bad
        print(f"  (of which model load: {st['load_s']:.2f} s)")
    if st["prompt_tps"]:
        print(f"Prompt processing: {st['prompt_tps']:.0f} tok/s")
    if st["gen_tps"]:
        print(f"Generation: {st['gen_tps']:.1f} tok/s")
    print(f"Total: {st['total_s']:.1f} s")
    if st["vram_used_gb"]:
        print(f"VRAM: {st['vram_used_gb']:.1f} GB / {st['vram_total_gb']:.0f} GB")
    if st["gpu_util"] is not None:
        print(f"GPU utilization: {st['gpu_util']:.0f}% avg, {st['gpu_util_peak']:.0f}% peak")
    print(line, flush=True)


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
def llm_reply(history):
    """Returns (reply_text, stats_dict). Streams so TTFT is a real measurement."""
    try:
        started = time.perf_counter()
        ttft = None
        pieces = []
        done = {}

        with GpuWatch() as gpu:
            r = requests.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "messages": history, "stream": True},
                stream=True,
                timeout=120,
            )
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise RuntimeError(chunk["error"])
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    if ttft is None:
                        ttft = time.perf_counter() - started
                    pieces.append(piece)
                if chunk.get("done"):
                    done = chunk

        wall = time.perf_counter() - started
        # Ollama reports durations in nanoseconds.
        prompt_tokens = done.get("prompt_eval_count", 0)
        output_tokens = done.get("eval_count", len(pieces))
        prompt_ns = done.get("prompt_eval_duration", 0)
        eval_ns = done.get("eval_duration", 0)
        stats = {
            "model": done.get("model", OLLAMA_MODEL),
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "ttft_s": ttft,
            "load_s": done.get("load_duration", 0) / 1e9,
            "prompt_tps": prompt_tokens / (prompt_ns / 1e9) if prompt_ns else None,
            "gen_tps": output_tokens / (eval_ns / 1e9) if eval_ns else None,
            "total_s": wall,
            "vram_used_gb": gpu.peak_vram / 1024 if gpu.peak_vram else None,
            "vram_total_gb": gpu.total_vram / 1024 if gpu.total_vram else None,
            "gpu_util": gpu.mean_util,
            "gpu_util_peak": gpu.peak_util,
        }
        print_stats(stats)
        return "".join(pieces).strip(), stats
    except requests.exceptions.ConnectionError:
        raise HTTPException(503, "Cannot reach Ollama. Is `ollama serve` running?")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"LLM error: {e}")


# ---------------------------------------------------------------------------
# Optional STT (faster-whisper) - loaded lazily
# ---------------------------------------------------------------------------
_stt_model = None


def get_stt():
    global _stt_model
    if _stt_model is None:
        from faster_whisper import WhisperModel   # raises if not installed
        _stt_model = WhisperModel("small", device="cpu", compute_type="int8")
    return _stt_model


def transcribe(audio_bytes):
    model = get_stt()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        path = f.name
    try:
        segments, _ = model.transcribe(path)
        return " ".join(seg.text for seg in segments).strip()
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Optional TTS (piper) - loaded lazily. Returns WAV bytes or None.
# ---------------------------------------------------------------------------
_tts_voice = None
PIPER_MODEL_PATH = os.environ.get("PIPER_MODEL", "en_US-lessac-medium.onnx")


def get_tts():
    global _tts_voice
    if _tts_voice is None:
        from piper import PiperVoice        # raises if not installed
        _tts_voice = PiperVoice.load(PIPER_MODEL_PATH)
    return _tts_voice


def synthesize(text):
    import wave, io
    voice = get_tts()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        voice.synthesize(text, wav)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
app = FastAPI(title="Hospital Avatar Booth")


class StartReq(BaseModel):
    patient_id: str


class ChatReq(BaseModel):
    session_id: str
    text: str


@app.post("/session/start")
def start_session(req: StartReq):
    patient = PATIENTS.get(req.patient_id)
    if not patient:
        raise HTTPException(404, "Unknown patient ID.")
    # one active patient at a time: clear any existing sessions
    sessions.clear()
    sid = uuid.uuid4().hex
    sessions[sid] = {
        "patient_id": req.patient_id,
        "history": [{"role": "system", "content": build_system_prompt(patient)}],
        "last_activity": time.time(),
    }
    return {"session_id": sid, "patient_name": patient["name"]}


@app.post("/session/end")
def end_session(session_id: str = Form(...)):
    sessions.pop(session_id, None)   # wipe everything for this patient
    return {"status": "ended"}


@app.post("/chat")
def chat(req: ChatReq):
    s = get_session(req.session_id)
    s["history"].append({"role": "user", "content": req.text})
    reply, stats = llm_reply(s["history"])
    s["history"].append({"role": "assistant", "content": reply})
    # cap history (keep system prompt + last N)
    if len(s["history"]) > MAX_HISTORY_MESSAGES:
        s["history"] = [s["history"][0]] + s["history"][-(MAX_HISTORY_MESSAGES - 1):]
    return {"reply": reply, "stats": stats}


@app.post("/chat/audio")
async def chat_audio(session_id: str = Form(...), audio: UploadFile = File(...)):
    s = get_session(session_id)
    try:
        user_text = transcribe(await audio.read())
    except ImportError:
        raise HTTPException(501, "STT not installed. `pip install faster-whisper`")
    s["history"].append({"role": "user", "content": user_text})
    reply, stats = llm_reply(s["history"])
    s["history"].append({"role": "assistant", "content": reply})
    return {"user_text": user_text, "reply": reply, "stats": stats}


@app.get("/tts")
def tts(text: str):
    """Optional server-side TTS. If piper isn't set up, client falls back to browser speech."""
    try:
        wav = synthesize(text)
    except (ImportError, FileNotFoundError):
        raise HTTPException(501, "TTS not configured; using browser speech instead.")
    return Response(content=wav, media_type="audio/wav")


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(os.path.dirname(__file__), "index.html")) as f:
        return f.read()
