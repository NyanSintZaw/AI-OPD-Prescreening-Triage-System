"""In-process STT and TTS — the models run inside the backend, not over HTTP.

The ``openai_compatible`` providers put a network hop between the backend and
the speech models. When that hop is a tunnel it drops requests, and a lost STT
call costs the patient the whole turn: the voice bridge has no transcript, so
it speaks the "system temporarily unavailable" line and the LLM is never
reached. Loading the models here removes the hop entirely for the two legs
that carry patient audio, leaving only the LLM remote.

Two engines, matching ``local-speech/server.py`` so a booth gets the same
voice whether speech runs in-process or as a sidecar:

- **STT** faster-whisper (ctranslate2). Not torch — it has its own runtime,
  which is why it works on a CPU-only box with no CUDA wheels at all.
- **TTS** F5-TTS-THAI, which is *voice cloning*: it needs a reference clip and
  that clip's exact transcript, and gives one nurse voice in both languages
  (the language comes from the text, the voice from the clip). Without a
  reference it cannot run — see ``TTS_REF_AUDIO_TH``.

Inference is synchronous and CPU/GPU-bound, so every call goes through
``asyncio.to_thread``: running it inline would block the event loop and stall
every other WebSocket on the server for the duration of the transcription.
Models load lazily under a lock, once, on first use.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import threading
import time
from typing import Any

import numpy as np

from app.services.google_stt import SttResult
from app.services.google_tts import strip_wav_header
from app.services.log_target import operational_logger

_module_logger = logging.getLogger(__name__)


def _log() -> logging.Logger:
    return operational_logger(_module_logger)


_LANGUAGE_CODE = {"en": "en-US", "th": "th-TH"}


def _pcm16_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    """Float waveform in [-1, 1] → 16-bit PCM WAV bytes."""
    import wave

    clipped = np.clip(np.asarray(samples, dtype=np.float32).reshape(-1), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear resample. Only ever a small ratio here (24k↔22.05k↔16k).

    Shipping the wrong rate is worse than it sounds: the voice bridge streams
    whatever it gets into a scheduler fixed at 24 kHz, so a 22.05 kHz buffer
    plays back as a chipmunk rather than as an obvious error.
    """
    if src_rate == dst_rate:
        return samples
    src = np.asarray(samples, dtype=np.float32).reshape(-1)
    duration = len(src) / float(src_rate)
    dst_len = int(round(duration * dst_rate))
    if dst_len <= 0 or len(src) == 0:
        return src
    return np.interp(
        np.linspace(0.0, len(src) - 1, dst_len, dtype=np.float64),
        np.arange(len(src), dtype=np.float64),
        src,
    ).astype(np.float32)


class LocalWhisperSttClient:
    """faster-whisper in this process. Satisfies the ``SttClient`` protocol."""

    def __init__(
        self,
        *,
        model_size: str = "large-v3-turbo",
        device: str = "auto",
        compute_type: str = "int8",
        beam_size: int = 1,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        # beam_size=1 (greedy) on purpose: a booth turn is one short utterance
        # and beam search costs latency the patient waits through.
        self._beam_size = beam_size
        self._model: Any = None
        self._lock = threading.Lock()
        self.runtime: dict[str, Any] = {}

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                device, compute = self._device, self._compute_type
                started = time.perf_counter()
                _log().info(
                    "Loading STT: faster-whisper %s (%s/%s)",
                    self._model_size, device, compute,
                )
                try:
                    self._model = WhisperModel(
                        self._model_size, device=device, compute_type=compute
                    )
                except Exception as exc:  # noqa: BLE001
                    # A booth that answers slowly still answers; one that
                    # cannot load STT is dead. Mirror the sidecar's fallback.
                    if device == "cpu" and compute == "int8":
                        raise
                    _log().warning(
                        "STT on %s/%s unavailable (%s) — falling back to cpu/int8",
                        device, compute, exc,
                    )
                    device, compute = "cpu", "int8"
                    self._model = WhisperModel(
                        self._model_size, device=device, compute_type=compute
                    )
                self.runtime = {
                    "model": self._model_size,
                    "device": device,
                    "compute_type": compute,
                }
                _log().info(
                    "STT ready on %s in %.1fs", device, time.perf_counter() - started
                )
        return self._model

    def _transcribe_sync(self, audio_bytes: bytes, language: str) -> str:
        model = self._load()
        segments, _info = model.transcribe(
            io.BytesIO(audio_bytes),
            language=language,
            beam_size=self._beam_size,
            # The booth mic is open the whole turn, so most buffers are mostly
            # room noise. VAD keeps whisper from hallucinating sentences into
            # silence — a known failure mode that would enter triage as if the
            # patient had said it.
            vad_filter=True,
        )
        return "".join(segment.text for segment in segments).strip()

    async def transcribe(
        self, *, audio_bytes: bytes, language: str, mime_type: str | None
    ) -> SttResult:
        if not audio_bytes:
            raise ValueError("audio_bytes must not be empty")
        # mime_type is unused: faster-whisper decodes the container itself.
        text = await asyncio.to_thread(self._transcribe_sync, audio_bytes, language)
        return SttResult(
            transcript=text,
            confidence=None,
            language_code=_LANGUAGE_CODE.get(language, "en-US"),
        )

    async def prewarm(self) -> None:
        await asyncio.to_thread(self._load)


class LocalF5TtsClient:
    """F5-TTS-THAI in this process. Satisfies the ``TtsClient`` protocol."""

    NATIVE_RATE = 24_000  # what F5 emits, and what the voice bridge wants

    def __init__(
        self,
        *,
        model: str = "v1",
        device: str = "cpu",
        refs_by_language: dict[str, tuple[str, str]],
        steps: int = 32,
        cfg: float = 2.0,
        speed_by_language: dict[str, float] | None = None,
    ) -> None:
        # Fail here rather than at the first patient turn. A missing
        # transcript is the nastier of the two: F5 still runs, aligns against
        # nothing, and degrades in a way that reads as the model simply
        # being bad.
        missing = [
            lang for lang, (audio, text) in refs_by_language.items()
            if not audio or not text
        ]
        if missing or not refs_by_language:
            raise ValueError(
                "F5 TTS is voice cloning — every language needs a reference "
                "clip AND its exact transcript; missing for: "
                + (", ".join(sorted(missing)) or "(no languages configured)")
            )
        self._model_name = model
        self._device = device
        self._refs = refs_by_language
        self._steps = steps
        self._cfg = cfg
        self._speed = speed_by_language or {"th": 0.95, "en": 1.0}
        self._tts: Any = None
        self._lock = threading.Lock()
        # Inference lock, separate from the load lock. f5_tts_th's TTS object
        # carries per-call state through infer(), so two concurrent calls
        # corrupt each other's tensors — observed as "Sizes of tensors must
        # match except in dimension 2" when a startup probe overlapped the
        # first greeting. asyncio.to_thread makes that overlap the DEFAULT,
        # so the model has to be entered one caller at a time.
        self._infer_lock = threading.Lock()
        self.runtime: dict[str, Any] = {}

    @staticmethod
    def _ensure_audio_loader() -> None:
        """Give ``torchaudio.load`` a decoder that works, or F5 cannot start.

        torchaudio 2.11 delegates decoding to ``torchcodec``, which ships
        loaders bound to FFmpeg 4-7 (``libavutil.56``-``59``). A box on
        FFmpeg 8 has ``libavutil.60`` and none of them load — and because
        macOS resolves ``@rpath`` against the literal rpath list rather than
        reusing already-loaded libraries, preloading the right FFmpeg with
        ctypes does not help either (it does on Linux).

        F5 needs exactly one decode: ``torchaudio.load(ref_audio)`` for the
        reference clip. Everything else it asks of torchaudio (Resample,
        MelSpectrogram) is pure tensor math. So fall back to soundfile —
        libsndfile, no FFmpeg involved — and leave the rest alone.
        """
        import torchaudio

        if getattr(torchaudio.load, "_soundfile_fallback", False):
            return

        original = torchaudio.load

        def load(uri: Any, *args: Any, **kwargs: Any):
            try:
                return original(uri, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                import soundfile as sf
                import torch

                _log().warning(
                    "torchaudio.load failed (%s: %s) — decoding %s with "
                    "soundfile instead",
                    type(exc).__name__, str(exc).splitlines()[0][:120], uri,
                )
                data, sample_rate = sf.read(uri, dtype="float32", always_2d=True)
                # soundfile gives (frames, channels); torchaudio's contract is
                # (channels, frames).
                return torch.from_numpy(data.T.copy()), sample_rate

        load._soundfile_fallback = True  # type: ignore[attr-defined]
        torchaudio.load = load  # type: ignore[assignment]

    @staticmethod
    def _ensure_ffmpeg() -> None:
        """Point pydub at a working ffmpeg/ffprobe if the PATH one is broken.

        F5's ``preprocess_ref_audio_text`` runs the reference clip through
        pydub, which shells out to ``ffprobe`` and parses its stdout as JSON.
        A broken ffprobe prints nothing, so the failure surfaces as
        ``JSONDecodeError: Expecting value: line 1 column 1`` — which points
        at pydub's parser and says nothing about the real cause. Homebrew
        hits this whenever ffmpeg outlives a dependency's soname bump (here:
        FFmpeg 8 against a missing ``libx265.216.dylib``).

        ``TTS_FFMPEG_DIR`` overrides; otherwise try the PATH binaries and
        fall back to known-good keg-only installs.
        """
        import shutil
        import subprocess

        from pydub import AudioSegment

        def works(binary: str | None) -> bool:
            if not binary or not os.path.exists(binary):
                return False
            try:
                return subprocess.run(
                    [binary, "-version"], capture_output=True, timeout=10
                ).returncode == 0
            except Exception:  # noqa: BLE001
                return False

        configured = os.environ.get("TTS_FFMPEG_DIR", "").strip()
        candidates = [configured] if configured else []
        path_probe = shutil.which("ffprobe")
        if path_probe and not configured:
            candidates.append(os.path.dirname(path_probe))
        candidates += ["/opt/homebrew/opt/ffmpeg@7/bin", "/usr/local/opt/ffmpeg@7/bin"]

        for directory in candidates:
            probe = os.path.join(directory, "ffprobe")
            convert = os.path.join(directory, "ffmpeg")
            if works(probe) and works(convert):
                AudioSegment.converter = convert
                setattr(AudioSegment, "ffprobe", probe)
                # Setting those attributes is NOT enough: pydub's
                # ``mediainfo_json`` calls ``get_prober_name()``, which does
                # its own ``which("ffprobe")`` and ignores them entirely. PATH
                # is the only thing it honours.
                if os.environ.get("PATH", "").split(os.pathsep)[0] != directory:
                    os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
                _log().info("pydub using ffmpeg from %s", directory)
                return
        _log().warning(
            "no working ffprobe found (tried %s) — F5 reference preprocessing "
            "will fail; set TTS_FFMPEG_DIR",
            ", ".join(c for c in candidates if c),
        )

    @staticmethod
    def _torch_device() -> str:
        """Where torch actually placed the model — reported, not chosen."""
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                return "mps"
        except Exception:  # noqa: BLE001 — reporting must never break loading
            pass
        return "cpu"

    def _load(self) -> Any:
        with self._lock:
            if self._tts is None:
                self._ensure_audio_loader()
                self._ensure_ffmpeg()
                from f5_tts_th.tts import TTS

                started = time.perf_counter()
                _log().info("Loading TTS: F5-TTS-THAI %s", self._model_name)
                # f5-tts-th (1.0.9) is TTS(model, vocoder_name, hf_cache_dir)
                # — there is no device argument, so placement follows torch's
                # own default. TTS_LOCAL_DEVICE is therefore reported, not
                # requested; steer placement with torch's device settings if a
                # future build needs it.
                self._tts = TTS(model=self._model_name)
                self.runtime = {
                    "model": f"F5-TTS-THAI/{self._model_name}",
                    "device": self._torch_device(),
                    "sample_rate": self.NATIVE_RATE,
                }
                _log().info(
                    "TTS ready on %s in %.1fs",
                    self.runtime["device"], time.perf_counter() - started,
                )
        return self._tts

    def _synthesize_sync(self, text: str, language: str) -> np.ndarray:
        tts = self._load()
        ref_audio, ref_text = self._refs.get(language) or self._refs["th"]
        with self._infer_lock:
            wav = tts.infer(
                ref_audio=ref_audio,
                ref_text=ref_text,
                gen_text=text,
                step=self._steps,
                cfg=self._cfg,
                speed=self._speed.get(language, 1.0),
            )
        # Some builds return (waveform, sample_rate) rather than a bare array.
        if isinstance(wav, tuple):
            wav = wav[0]
        # reshape(-1), NOT squeeze(): squeeze turns a 1-sample result into a
        # 0-d array that survives every check until len() raises deep inside
        # the WAV writer, with nothing pointing at the real cause.
        return np.asarray(wav, dtype=np.float32).reshape(-1)

    async def synthesize(
        self,
        *,
        text: str,
        language: str,
        audio_encoding: str = "mp3",
        sample_rate_hertz: int | None = None,
    ) -> bytes:
        if not text.strip():
            raise ValueError("text must not be empty")
        samples = await asyncio.to_thread(self._synthesize_sync, text, language)
        if samples.size == 0:
            raise RuntimeError("F5 synthesis returned no audio")

        target_rate = sample_rate_hertz or self.NATIVE_RATE
        samples = _resample(samples, self.NATIVE_RATE, target_rate)

        wav = _pcm16_wav(samples, target_rate)
        if audio_encoding == "linear16":
            # The voice bridge streams headerless PCM straight to the browser's
            # scheduler, so hand back frames only. Parse the header rather than
            # assuming 44 bytes — the same helper the Google client uses.
            return strip_wav_header(wav)
        return wav

    async def prewarm(self) -> None:
        await asyncio.to_thread(self._load)
