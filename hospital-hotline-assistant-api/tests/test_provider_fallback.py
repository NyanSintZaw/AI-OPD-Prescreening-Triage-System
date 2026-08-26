"""Failover wiring for the local-sidecar deployment: the screening LLM and
the STT/TTS clients each try a primary provider and complete on a fallback,
so a sidecar outage degrades to the Google path instead of failing turns."""

from types import SimpleNamespace
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from app.services import speech_adapter
from app.services.google_stt import SttResult
from app.services.screening import model_adapter
from app.services.screening.model_adapter import FallbackChatModel, build_chat_model
from app.services.speech_adapter import (
    FallbackSttClient,
    FallbackTtsClient,
    build_stt_client,
    build_tts_client,
)


# ── LLM fakes ────────────────────────────────────────────────────────────


class _StaticModel(BaseChatModel):
    """Always answers ``reply``; structured output parses to ``{"who": reply}``."""

    reply: str = "ok"

    @property
    def _llm_type(self) -> str:
        return "static"

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        message = AIMessage(content=self.reply)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        return RunnableLambda(lambda _value, config=None: {"who": self.reply})


class _BoomModel(BaseChatModel):
    """Every call raises — a dead sidecar."""

    @property
    def _llm_type(self) -> str:
        return "boom"

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        raise RuntimeError("primary down")

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        def _raise(_value: Any, config: Any = None) -> Any:
            raise RuntimeError("primary down")

        return RunnableLambda(_raise)


async def test_llm_uses_primary_when_healthy():
    model = FallbackChatModel(
        primary=_StaticModel(reply="primary"), fallback=_StaticModel(reply="fallback")
    )
    reply = await model.ainvoke([HumanMessage(content="hi")])
    assert reply.content == "primary"


async def test_llm_falls_back_when_primary_raises():
    model = FallbackChatModel(primary=_BoomModel(), fallback=_StaticModel(reply="fallback"))
    reply = await model.ainvoke([HumanMessage(content="hi")])
    assert reply.content == "fallback"


async def test_structured_output_falls_back():
    # The path the screening nodes actually use (with_structured_output →
    # ainvoke) must fail over too, not just plain chat.
    model = FallbackChatModel(primary=_BoomModel(), fallback=_StaticModel(reply="fallback"))
    parsed = await model.with_structured_output(dict).ainvoke("prompt")
    assert parsed == {"who": "fallback"}


async def test_structured_output_prefers_primary():
    model = FallbackChatModel(
        primary=_StaticModel(reply="primary"), fallback=_StaticModel(reply="fallback")
    )
    parsed = await model.with_structured_output(dict).ainvoke("prompt")
    assert parsed == {"who": "primary"}


def test_build_chat_model_wires_failover(monkeypatch):
    built: list[tuple[str, str, float, int]] = []

    def _fake_build(settings, provider, model_name, timeout_s, max_retries):
        built.append((provider, model_name, timeout_s, max_retries))
        return _StaticModel(reply=provider)

    monkeypatch.setattr(model_adapter, "_build_provider", _fake_build)
    settings = SimpleNamespace(
        screening_model_provider="openai_compatible",
        screening_model_name="typhoon",
        screening_model_timeout_s=30.0,
        screening_fallback_provider="vertexai",
        screening_fallback_model_name="gemini-3.1-flash-lite",
        screening_primary_timeout_s=12.0,
    )
    model = build_chat_model(settings)
    assert isinstance(model, FallbackChatModel)
    # Primary: short leg budget, no client retries (the fallback IS the
    # retry). Fallback: the full turn budget.
    assert built == [
        ("openai_compatible", "typhoon", 12.0, 0),
        ("vertexai", "gemini-3.1-flash-lite", 30.0, 1),
    ]


def test_build_chat_model_single_provider_without_fallback(monkeypatch):
    built: list[tuple[str, str, float, int]] = []

    def _fake_build(settings, provider, model_name, timeout_s, max_retries):
        built.append((provider, model_name, timeout_s, max_retries))
        return _StaticModel(reply=provider)

    monkeypatch.setattr(model_adapter, "_build_provider", _fake_build)
    settings = SimpleNamespace(
        screening_model_provider="vertexai",
        screening_model_name="gemini-3.1-flash-lite",
        screening_model_timeout_s=30.0,
        screening_fallback_provider=None,
    )
    model = build_chat_model(settings)
    assert not isinstance(model, FallbackChatModel)
    assert built == [("vertexai", "gemini-3.1-flash-lite", 30.0, 1)]


# ── Speech fakes ─────────────────────────────────────────────────────────


class _StaticStt:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def transcribe(self, *, audio_bytes, language, mime_type) -> SttResult:
        self.calls += 1
        return SttResult(transcript=self.text, confidence=None, language_code=language)


class _BoomStt:
    async def transcribe(self, *, audio_bytes, language, mime_type) -> SttResult:
        raise RuntimeError("stt down")


class _StaticTts:
    def __init__(self, audio: bytes) -> None:
        self.audio = audio
        self.kwargs: dict | None = None

    async def synthesize(self, *, text, language, audio_encoding="mp3", sample_rate_hertz=None) -> bytes:
        self.kwargs = {
            "text": text,
            "language": language,
            "audio_encoding": audio_encoding,
            "sample_rate_hertz": sample_rate_hertz,
        }
        return self.audio


class _BoomTts:
    async def synthesize(self, *, text, language, audio_encoding="mp3", sample_rate_hertz=None) -> bytes:
        raise RuntimeError("tts down")


async def test_stt_uses_primary_when_healthy():
    primary, fallback = _StaticStt("primary"), _StaticStt("fallback")
    client = FallbackSttClient(primary, fallback)
    result = await client.transcribe(audio_bytes=b"x", language="th", mime_type="audio/wav")
    assert result.transcript == "primary"
    assert fallback.calls == 0


async def test_stt_falls_back_on_error():
    client = FallbackSttClient(_BoomStt(), _StaticStt("fallback"))
    result = await client.transcribe(audio_bytes=b"x", language="th", mime_type="audio/wav")
    assert result.transcript == "fallback"


async def test_stt_empty_transcript_is_not_an_error():
    # Silence is a valid answer — it must NOT trigger a second (cloud) pass.
    primary, fallback = _StaticStt(""), _StaticStt("fallback")
    client = FallbackSttClient(primary, fallback)
    result = await client.transcribe(audio_bytes=b"x", language="th", mime_type="audio/wav")
    assert result.transcript == ""
    assert fallback.calls == 0


async def test_tts_falls_back_and_preserves_the_request():
    fallback = _StaticTts(b"pcm-fallback")
    client = FallbackTtsClient(_BoomTts(), fallback)
    audio = await client.synthesize(
        text="สวัสดี", language="th", audio_encoding="linear16", sample_rate_hertz=24000
    )
    assert audio == b"pcm-fallback"
    # The fallback must receive the same encoding contract the voice bridge
    # asked for, or the 24 kHz scheduler gets the wrong audio format.
    assert fallback.kwargs == {
        "text": "สวัสดี",
        "language": "th",
        "audio_encoding": "linear16",
        "sample_rate_hertz": 24000,
    }


def _speech_settings(**overrides) -> SimpleNamespace:
    base = dict(
        stt_provider="openai_compatible",
        stt_base_url="http://sidecar/v1",
        stt_model="medium",
        stt_api_key=None,
        stt_fallback_provider=None,
        tts_provider="openai_compatible",
        tts_base_url="http://sidecar/v1",
        tts_model="mms-tts",
        tts_api_key=None,
        tts_local_voice_th="th",
        tts_local_voice_en="en",
        tts_fallback_provider=None,
        speech_http_timeout_s=30.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_stt_client_wires_failover(monkeypatch):
    import app.services.google_stt as google_stt

    monkeypatch.setattr(google_stt, "GoogleSttClient", lambda: _StaticStt("google"))
    client = build_stt_client(_speech_settings(stt_fallback_provider="google"))
    assert isinstance(client, FallbackSttClient)
    assert isinstance(client._primary, speech_adapter.HttpSttClient)
    assert isinstance(client._fallback, _StaticStt)


def test_build_tts_client_no_fallback_by_default(monkeypatch):
    client = build_tts_client(_speech_settings())
    assert isinstance(client, speech_adapter.HttpTtsClient)
