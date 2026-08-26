"""Speech adapter: one construction point for every STT/TTS backend.

Mirrors ``screening/model_adapter.py`` — the serving backend is a config
choice, not a code change:

- ``google`` (default): Cloud Speech-to-Text / Text-to-Speech, same ADC auth
  as the rest of the app.
- ``openai_compatible``: any OpenAI-audio-compatible HTTP endpoint —
  faster-whisper-server / Speaches / whisper.cpp server for STT, Speaches /
  kokoro-fastapi / openedai-speech for TTS — so patient audio can stay inside
  the hospital (the privacy claim in ``docs/ai-model-io.md``).

``STT_FALLBACK_PROVIDER``/``TTS_FALLBACK_PROVIDER`` optionally name a second
provider tried automatically when the primary errors — so a local sidecar can
be primary without a sidecar outage silencing the booth.

The Protocols capture exactly what the two callers use: the ``/stt`` + ``/tts``
routes (``app/routers/speech.py``) and the voice bridge
(``app/services/screening/voice_bridge.py``).
"""

from __future__ import annotations

import logging
import struct
from typing import Any, Protocol, runtime_checkable

from app.services.google_stt import SttResult
from app.services.google_tts import strip_wav_header

logger = logging.getLogger(__name__)


@runtime_checkable
class SttClient(Protocol):
    async def transcribe(
        self, *, audio_bytes: bytes, language: str, mime_type: str | None
    ) -> SttResult: ...


@runtime_checkable
class TtsClient(Protocol):
    async def synthesize(
        self,
        *,
        text: str,
        language: str,
        audio_encoding: str = "mp3",
        sample_rate_hertz: int | None = None,
    ) -> bytes: ...


_LANGUAGE_CODE = {"en": "en-US", "th": "th-TH"}

# Whisper servers sniff the container with ffmpeg, but they route on the file
# extension first, so the part has to be named for what it holds.
_EXT_BY_MIME = (
    ("webm", ".webm"),
    ("ogg", ".ogg"),
    ("mp4", ".m4a"),
    ("aac", ".m4a"),
    ("mpeg", ".mp3"),
    ("wav", ".wav"),
)


def _filename_for(mime: str | None) -> str:
    lowered = (mime or "").lower()
    for needle, ext in _EXT_BY_MIME:
        if needle in lowered:
            return f"audio{ext}"
    return "audio.wav"


def _wav_sample_rate(audio: bytes) -> int | None:
    """Sample rate from a WAV ``fmt `` chunk, or None if it isn't a WAV."""

    if not audio.startswith(b"RIFF"):
        return None
    fmt_index = audio.find(b"fmt ")
    if fmt_index == -1 or len(audio) < fmt_index + 16:
        return None
    return struct.unpack_from("<I", audio, fmt_index + 12)[0]


class HttpSttClient:
    """STT over the OpenAI ``/v1/audio/transcriptions`` contract."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        transport: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._transport = transport

    async def transcribe(
        self, *, audio_bytes: bytes, language: str, mime_type: str | None
    ) -> SttResult:
        if not audio_bytes:
            raise ValueError("audio_bytes must not be empty")

        import httpx

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_s, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/audio/transcriptions",
                    headers=headers,
                    data={
                        "model": self._model,
                        "language": language,
                        "response_format": "json",
                    },
                    files={
                        "file": (
                            _filename_for(mime_type),
                            audio_bytes,
                            mime_type or "application/octet-stream",
                        )
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.exception("Local STT transcription failed")
            raise RuntimeError(f"Local STT error: {exc}") from exc

        return SttResult(
            transcript=(payload.get("text") or "").strip(),
            # The OpenAI transcription contract carries no confidence score.
            confidence=None,
            language_code=_LANGUAGE_CODE.get(language, "en-US"),
        )


class HttpTtsClient:
    """TTS over the OpenAI ``/v1/audio/speech`` contract.

    ``audio_encoding="linear16"`` asks the server for WAV and returns the raw
    frames, matching what the voice bridge streams (headerless PCM at
    ``sample_rate_hertz``).
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        voice_by_language: dict[str, str],
        api_key: str | None = None,
        timeout_s: float = 30.0,
        transport: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._voices = voice_by_language
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._transport = transport

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

        import httpx

        linear16 = audio_encoding == "linear16"
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        body: dict[str, Any] = {
            "model": self._model,
            "input": text,
            "voice": self._voices.get(language) or self._voices["en"],
            "response_format": "wav" if linear16 else "mp3",
        }
        if sample_rate_hertz is not None:
            # Honoured by Speaches; ignored by servers that don't support it,
            # which is why the rate is verified below rather than assumed.
            body["sample_rate"] = sample_rate_hertz
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_s, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/audio/speech", headers=headers, json=body
                )
                response.raise_for_status()
                audio = response.content
        except Exception as exc:
            logger.exception("Local TTS synthesis failed")
            raise RuntimeError(f"Local TTS error: {exc}") from exc

        if not linear16:
            return audio

        rate = _wav_sample_rate(audio)
        if sample_rate_hertz is not None and rate not in (None, sample_rate_hertz):
            # Playing 22.05 kHz frames through a 24 kHz scheduler is a
            # chipmunk voice, so fail loudly instead of shipping garble.
            # ponytail: no resampling — configure the server's output rate,
            # or add a resampler here if a server can't be configured.
            raise RuntimeError(
                f"Local TTS returned {rate} Hz audio, expected {sample_rate_hertz} Hz"
            )
        return strip_wav_header(audio)


class FallbackSttClient:
    """Failover pair behind the ``SttClient`` protocol: transcribe on the
    primary; any error completes on the fallback instead of failing the
    voice turn. An empty transcript is a valid result (silence), not an
    error — it does not trigger the fallback."""

    def __init__(self, primary: SttClient, fallback: SttClient) -> None:
        self._primary = primary
        self._fallback = fallback

    async def transcribe(
        self, *, audio_bytes: bytes, language: str, mime_type: str | None
    ) -> SttResult:
        try:
            return await self._primary.transcribe(
                audio_bytes=audio_bytes, language=language, mime_type=mime_type
            )
        except Exception:
            logger.warning("Primary STT failed; using fallback", exc_info=True)
            return await self._fallback.transcribe(
                audio_bytes=audio_bytes, language=language, mime_type=mime_type
            )


class FallbackTtsClient:
    """Failover pair behind the ``TtsClient`` protocol, same contract as
    :class:`FallbackSttClient` — the caller keeps hearing a voice even when
    the primary TTS is down."""

    def __init__(self, primary: TtsClient, fallback: TtsClient) -> None:
        self._primary = primary
        self._fallback = fallback

    async def synthesize(
        self,
        *,
        text: str,
        language: str,
        audio_encoding: str = "mp3",
        sample_rate_hertz: int | None = None,
    ) -> bytes:
        try:
            return await self._primary.synthesize(
                text=text,
                language=language,
                audio_encoding=audio_encoding,
                sample_rate_hertz=sample_rate_hertz,
            )
        except Exception:
            logger.warning("Primary TTS failed; using fallback", exc_info=True)
            return await self._fallback.synthesize(
                text=text,
                language=language,
                audio_encoding=audio_encoding,
                sample_rate_hertz=sample_rate_hertz,
            )


def _stt_for_provider(settings: Any, provider: str) -> SttClient:
    if provider == "google":
        from app.services.google_stt import GoogleSttClient

        return GoogleSttClient()
    if provider == "openai_compatible":
        return HttpSttClient(
            base_url=settings.stt_base_url or "http://localhost:8080/v1",
            model=getattr(settings, "stt_model", "whisper-1"),
            api_key=getattr(settings, "stt_api_key", None),
            timeout_s=float(getattr(settings, "speech_http_timeout_s", 30.0)),
        )
    raise ValueError(f"Unknown stt_provider: {provider!r}")


def _tts_for_provider(settings: Any, provider: str) -> TtsClient:
    if provider == "google":
        from app.services.google_tts import GoogleTtsClient

        return GoogleTtsClient()
    if provider == "openai_compatible":
        return HttpTtsClient(
            base_url=settings.tts_base_url or "http://localhost:8081/v1",
            model=getattr(settings, "tts_model", "tts-1"),
            voice_by_language={
                "en": getattr(settings, "tts_local_voice_en", "alloy"),
                "th": getattr(settings, "tts_local_voice_th", "alloy"),
            },
            api_key=getattr(settings, "tts_api_key", None),
            timeout_s=float(getattr(settings, "speech_http_timeout_s", 30.0)),
        )
    raise ValueError(f"Unknown tts_provider: {provider!r}")


def build_stt_client(settings: Any) -> SttClient:
    provider = getattr(settings, "stt_provider", "google")
    client = _stt_for_provider(settings, provider)
    fallback = getattr(settings, "stt_fallback_provider", None)
    if fallback and fallback != provider:
        return FallbackSttClient(client, _stt_for_provider(settings, fallback))
    return client


def build_tts_client(settings: Any) -> TtsClient:
    provider = getattr(settings, "tts_provider", "google")
    client = _tts_for_provider(settings, provider)
    fallback = getattr(settings, "tts_fallback_provider", None)
    if fallback and fallback != provider:
        return FallbackTtsClient(client, _tts_for_provider(settings, fallback))
    return client
