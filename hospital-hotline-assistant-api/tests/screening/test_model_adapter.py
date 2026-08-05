"""build_chat_model: thinking config must match the model family.

Gemini 3+ returns HTTP 400 if thinking_level and thinking_budget are both
sent, and Gemini 2.x doesn't understand thinking_level — so the adapter must
pick exactly one knob per family.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import langchain_google_genai

from app.services.screening.model_adapter import build_chat_model


def _build(settings: SimpleNamespace) -> Any:
    return cast(Any, build_chat_model(settings))


class _CapturedModel:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


def _settings(
    model_name: str,
    thinking_level: str | None = "minimal",
    temperature: float = 0.1,
) -> SimpleNamespace:
    return SimpleNamespace(
        screening_model_provider="vertexai",
        screening_model_name=model_name,
        screening_model_timeout_s=30.0,
        screening_thinking_level=thinking_level,
        screening_model_temperature=temperature,
        google_cloud_project="test-project",
        google_cloud_location="global",
    )


def test_gemini3_gets_thinking_level_only(monkeypatch):
    monkeypatch.setattr(
        langchain_google_genai, "ChatGoogleGenerativeAI", _CapturedModel
    )
    model = _build(_settings("gemini-3.1-flash-lite"))
    assert model.kwargs["thinking_level"] == "minimal"
    assert "thinking_budget" not in model.kwargs
    # Extraction determinism: temperature is pinned for EVERY family,
    # including Gemini 3.x (previously left at the 1.0 default).
    assert model.kwargs["temperature"] == 0.1
    assert model.kwargs["location"] == "global"


def test_gemini3_temperature_comes_from_settings(monkeypatch):
    monkeypatch.setattr(
        langchain_google_genai, "ChatGoogleGenerativeAI", _CapturedModel
    )
    model = _build(_settings("gemini-3.5-flash", temperature=0.0))
    assert model.kwargs["temperature"] == 0.0


def test_gemini2_gets_thinking_budget_zero(monkeypatch):
    monkeypatch.setattr(
        langchain_google_genai, "ChatGoogleGenerativeAI", _CapturedModel
    )
    model = _build(_settings("gemini-2.5-flash"))
    assert model.kwargs["thinking_budget"] == 0
    assert "thinking_level" not in model.kwargs
    assert model.kwargs["temperature"] == 0.1


def test_thinking_level_none_sends_neither(monkeypatch):
    monkeypatch.setattr(
        langchain_google_genai, "ChatGoogleGenerativeAI", _CapturedModel
    )
    model = _build(_settings("gemini-3.5-flash", thinking_level=None))
    assert "thinking_level" not in model.kwargs
    assert "thinking_budget" not in model.kwargs
    assert model.kwargs["temperature"] == 0.1
