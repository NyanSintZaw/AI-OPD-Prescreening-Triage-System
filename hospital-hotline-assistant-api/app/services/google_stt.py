"""Google Cloud Speech-to-Text client.

Accepts a short audio clip (typically WEBM/Opus from the browser's MediaRecorder)
and returns a transcript. Uses the synchronous `recognize` API since push-to-talk
clips are short. Supports Thai (`th`) and English (`en`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


_LANGUAGE_CODE_BY_APP_LANGUAGE = {
    "en": "en-US",
    "th": "th-TH",
}

# Speech-adaptation phrase hints: bias recognition toward the vocabulary a
# triage answer actually uses (symptoms, yes/no, numbers 0–10, time spans) so
# clipped/accented speech isn't misheard as unrelated words (e.g. "cough" ->
# "mouth call"). Boosted per Google's SpeechContext.
_PHRASE_HINTS: dict[str, list[str]] = {
    "en-US": [
        "cough", "sore throat", "fever", "chest pain", "shortness of breath",
        "trouble breathing", "hard to breathe", "headache", "dizzy", "nausea",
        "vomiting", "diarrhea", "rash", "runny nose", "stuffy nose", "phlegm",
        "stomach pain", "abdominal pain", "bleeding", "swelling", "numbness",
        "yes", "no", "not sure", "a little", "a lot", "mild", "moderate", "severe",
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "days", "day", "weeks", "week", "hours", "since yesterday",
    ],
    "th-TH": [
        "ไอ", "เจ็บคอ", "มีไข้", "ตัวร้อน", "เจ็บหน้าอก", "แน่นหน้าอก",
        "หายใจลำบาก", "หายใจเหนื่อย", "ปวดหัว", "เวียนหัว", "คลื่นไส้",
        "อาเจียน", "ท้องเสีย", "ผื่น", "น้ำมูก", "คัดจมูก", "เสมหะ",
        "ปวดท้อง", "เลือดออก", "บวม", "ชา",
        "ใช่", "ไม่", "ไม่แน่ใจ", "นิดหน่อย", "เยอะ", "เล็กน้อย", "รุนแรง",
        "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า", "สิบ",
        "วัน", "สัปดาห์", "ชั่วโมง", "เมื่อวาน",
    ],
}


@dataclass
class SttResult:
    transcript: str
    confidence: float | None
    language_code: str


def _ensure_credentials_env() -> None:
    if settings.google_application_credentials:
        cred_path = settings.google_application_credentials
        if not pathlib.Path(cred_path).is_absolute():
            cred_path = str((pathlib.Path.cwd() / cred_path).resolve())
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path


def _encoding_for_mime(mime: str | None):
    """Map common browser audio MIME types to STT encoding enums.

    MediaRecorder defaults: Chrome/Edge -> audio/webm;codecs=opus,
    Safari -> audio/mp4. Firefox -> audio/ogg;codecs=opus.
    """

    from google.cloud import speech_v1 as speech

    if not mime:
        return speech.RecognitionConfig.AudioEncoding.WEBM_OPUS

    lowered = mime.lower()
    if "webm" in lowered:
        return speech.RecognitionConfig.AudioEncoding.WEBM_OPUS
    if "ogg" in lowered:
        return speech.RecognitionConfig.AudioEncoding.OGG_OPUS
    if "mp4" in lowered or "mp4a" in lowered or "aac" in lowered:
        # Cloud STT v1 doesn't natively recognize AAC; we let it auto-detect
        # by returning ENCODING_UNSPECIFIED.
        return speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED
    if "wav" in lowered or "x-wav" in lowered or "linear" in lowered:
        return speech.RecognitionConfig.AudioEncoding.LINEAR16
    return speech.RecognitionConfig.AudioEncoding.WEBM_OPUS


class GoogleSttClient:
    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            _ensure_credentials_env()
            from google.cloud import speech_v1 as speech

            self._client = speech.SpeechClient()
        return self._client

    async def transcribe(
        self,
        *,
        audio_bytes: bytes,
        language: str,
        mime_type: str | None,
    ) -> SttResult:
        if not audio_bytes:
            raise ValueError("audio_bytes must not be empty")

        language_code = _LANGUAGE_CODE_BY_APP_LANGUAGE.get(language, "en-US")

        return await asyncio.to_thread(
            self._transcribe_sync, audio_bytes, language_code, mime_type
        )

    def _transcribe_sync(
        self,
        audio_bytes: bytes,
        language_code: str,
        mime_type: str | None,
    ) -> SttResult:
        try:
            from google.cloud import speech_v1 as speech
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-speech is not installed. "
                "Add it via `uv sync` / `pip install google-cloud-speech`."
            ) from exc

        client = self._get_client()

        encoding = _encoding_for_mime(mime_type)
        config_kwargs: dict[str, object] = {
            "encoding": encoding,
            "language_code": language_code,
            "enable_automatic_punctuation": True,
            "model": "default",
        }
        # Opus inputs from MediaRecorder (browser) and Cloud TTS are 48 kHz.
        if encoding in (
            speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
        ):
            config_kwargs["sample_rate_hertz"] = 48000

        # Bias recognition toward the triage vocabulary for this language.
        hints = _PHRASE_HINTS.get(language_code)
        if hints:
            config_kwargs["speech_contexts"] = [
                speech.SpeechContext(phrases=hints, boost=15.0)
            ]

        config = speech.RecognitionConfig(**config_kwargs)
        audio = speech.RecognitionAudio(content=audio_bytes)

        try:
            response = client.recognize(config=config, audio=audio)
        except Exception as exc:
            logger.exception("Cloud STT recognize failed")
            raise RuntimeError(f"Cloud STT error: {exc}") from exc

        if not response.results:
            return SttResult(transcript="", confidence=None, language_code=language_code)

        best_alternative = response.results[0].alternatives[0]
        return SttResult(
            transcript=best_alternative.transcript or "",
            confidence=float(best_alternative.confidence)
            if best_alternative.confidence
            else None,
            language_code=language_code,
        )
