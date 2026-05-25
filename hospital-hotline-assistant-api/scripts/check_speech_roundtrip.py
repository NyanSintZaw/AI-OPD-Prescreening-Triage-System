"""End-to-end TTS + STT loopback.

Synthesizes an English phrase as OGG_OPUS via Cloud TTS, then submits it to
Cloud STT through the running FastAPI server (`POST /stt`) and prints the
recognized transcript.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import urllib.request

import httpx


REPO_DIR = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS",
    str(REPO_DIR / "phoenix_gcp_credentials.json"),
)

PHRASE = sys.argv[1] if len(sys.argv) > 1 else "I have a sore throat and a mild fever for two days."
LANGUAGE = sys.argv[2] if len(sys.argv) > 2 else "en"

VOICES = {
    "en": ("en-US", "en-US-Standard-C"),
    "th": ("th-TH", "th-TH-Standard-A"),
}
voice_lang, voice_name = VOICES.get(LANGUAGE, VOICES["en"])

from google.cloud import texttospeech_v1 as tts  # noqa: E402

tts_client = tts.TextToSpeechClient()
synthesis_input = tts.SynthesisInput(text=PHRASE)
voice = tts.VoiceSelectionParams(language_code=voice_lang, name=voice_name)
audio_config = tts.AudioConfig(
    audio_encoding=tts.AudioEncoding.OGG_OPUS,
    sample_rate_hertz=48000,
)
response = tts_client.synthesize_speech(
    input=synthesis_input, voice=voice, audio_config=audio_config
)
audio_bytes = bytes(response.audio_content)
print(f"TTS OGG_OPUS bytes: {len(audio_bytes)}")

files = {"audio": ("speech.ogg", io.BytesIO(audio_bytes), "audio/ogg")}
data = {"language": LANGUAGE}
with httpx.Client(timeout=30) as client:
    r = client.post("http://127.0.0.1:8000/stt", files=files, data=data)
    r.raise_for_status()
    payload = r.json()
print("STT transcript:", payload.get("transcript"))
print("STT confidence:", payload.get("confidence"))
print("STT language:  ", payload.get("language_code"))
