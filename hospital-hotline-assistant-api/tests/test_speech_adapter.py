"""STT/TTS provider seam — factories, Protocol conformance, HTTP provider.

No Google or network calls: the local providers are driven through an httpx
MockTransport.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.services.google_stt import GoogleSttClient
from app.services.google_tts import GoogleTtsClient
from app.services.screening.voice_bridge import OUTPUT_SAMPLE_RATE, pcm16_to_wav
from app.services.speech_adapter import (
    HttpSttClient,
    HttpTtsClient,
    SttClient,
    TtsClient,
    build_stt_client,
    build_tts_client,
)

LOCAL = SimpleNamespace(
    stt_provider="openai_compatible",
    stt_base_url="http://booth-gpu:8080/v1",
    stt_model="Systran/faster-whisper-large-v3",
    stt_api_key=None,
    tts_provider="openai_compatible",
    tts_base_url="http://booth-gpu:8081/v1/",
    tts_model="tts-1",
    tts_api_key=None,
    tts_local_voice_th="th_female",
    tts_local_voice_en="alloy",
    speech_http_timeout_s=5.0,
)


# ── factories ────────────────────────────────────────────────────────────────

def test_settings_default_to_google():
    assert Settings.model_fields["stt_provider"].default == "google"
    assert Settings.model_fields["tts_provider"].default == "google"


def test_factories_return_google_by_default():
    # Nothing configured at all → today's behaviour, unchanged.
    empty = SimpleNamespace()
    assert isinstance(build_stt_client(empty), GoogleSttClient)
    assert isinstance(build_tts_client(empty), GoogleTtsClient)
    google = SimpleNamespace(stt_provider="google", tts_provider="google")
    assert isinstance(build_stt_client(google), GoogleSttClient)
    assert isinstance(build_tts_client(google), GoogleTtsClient)


def test_factories_return_local_clients_when_configured():
    assert isinstance(build_stt_client(LOCAL), HttpSttClient)
    assert isinstance(build_tts_client(LOCAL), HttpTtsClient)


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="stt_provider"):
        build_stt_client(SimpleNamespace(stt_provider="whisper.cpp"))
    with pytest.raises(ValueError, match="tts_provider"):
        build_tts_client(SimpleNamespace(tts_provider="piper"))


def test_both_providers_satisfy_the_protocols():
    for client in (GoogleSttClient(), build_stt_client(LOCAL)):
        assert isinstance(client, SttClient)
    for client in (GoogleTtsClient(), build_tts_client(LOCAL)):
        assert isinstance(client, TtsClient)


# ── local STT ────────────────────────────────────────────────────────────────

async def test_local_stt_posts_openai_multipart_and_parses_text():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "  ปวดหัวมาสองวัน  "})

    client = HttpSttClient(
        base_url="http://booth-gpu:8080/v1",
        model="faster-whisper",
        transport=httpx.MockTransport(handler),
    )
    result = await client.transcribe(
        audio_bytes=b"\x01\x02" * 100, language="th", mime_type="audio/wav"
    )

    assert seen["url"] == "http://booth-gpu:8080/v1/audio/transcriptions"
    body = seen["body"]
    assert b'name="model"\r\n\r\nfaster-whisper' in body
    assert b'name="language"\r\n\r\nth' in body
    assert b'filename="audio.wav"' in body
    assert result.transcript == "ปวดหัวมาสองวัน"
    assert result.language_code == "th-TH"
    assert result.confidence is None


async def test_local_stt_names_the_part_for_the_browser_container():
    def handler(request: httpx.Request) -> httpx.Response:
        assert b'filename="audio.webm"' in request.content
        return httpx.Response(200, json={"text": "hi"})

    client = HttpSttClient(
        base_url="http://x/v1", model="m", transport=httpx.MockTransport(handler)
    )
    out = await client.transcribe(
        audio_bytes=b"x", language="en", mime_type="audio/webm;codecs=opus"
    )
    assert out.transcript == "hi"


async def test_local_stt_rejects_empty_audio_and_wraps_http_errors():
    client = HttpSttClient(
        base_url="http://x/v1",
        model="m",
        transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")),
    )
    with pytest.raises(ValueError):
        await client.transcribe(audio_bytes=b"", language="en", mime_type=None)
    with pytest.raises(RuntimeError, match="Local STT error"):
        await client.transcribe(audio_bytes=b"x", language="en", mime_type=None)


# ── local TTS ────────────────────────────────────────────────────────────────

def _tts(handler, **kwargs) -> HttpTtsClient:
    return HttpTtsClient(
        base_url="http://booth-gpu:8081/v1",
        model="tts-1",
        voice_by_language={"en": "alloy", "th": "th_female"},
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_local_tts_linear16_returns_headerless_pcm_at_the_bridge_rate():
    pcm = b"\x11\x22" * 480
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, content=pcm16_to_wav(pcm, OUTPUT_SAMPLE_RATE))

    audio = await _tts(handler).synthesize(
        text="สวัสดีค่ะ",
        language="th",
        audio_encoding="linear16",
        sample_rate_hertz=OUTPUT_SAMPLE_RATE,
    )

    assert seen["url"] == "http://booth-gpu:8081/v1/audio/speech"
    assert seen["json"]["voice"] == "th_female"
    assert seen["json"]["response_format"] == "wav"
    assert seen["json"]["sample_rate"] == 24_000
    assert audio == pcm  # exactly what the WS streams, no RIFF container


async def test_local_tts_rejects_a_wrong_sample_rate():
    handler = lambda r: httpx.Response(200, content=pcm16_to_wav(b"\x00\x00", 22_050))
    with pytest.raises(RuntimeError, match="22050 Hz"):
        await _tts(handler).synthesize(
            text="hello",
            language="en",
            audio_encoding="linear16",
            sample_rate_hertz=OUTPUT_SAMPLE_RATE,
        )


async def test_local_tts_defaults_to_mp3_for_the_rest_route():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, content=b"ID3fake-mp3")

    audio = await _tts(handler).synthesize(text="hello", language="en")
    assert b'"response_format": "mp3"' in seen["body"] or b'"response_format":"mp3"' in seen["body"]
    assert audio == b"ID3fake-mp3"  # passed through untouched


async def test_local_tts_rejects_empty_text():
    with pytest.raises(ValueError):
        await _tts(lambda r: httpx.Response(200)).synthesize(text="   ", language="en")
