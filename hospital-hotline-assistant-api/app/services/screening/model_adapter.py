"""Model adapter: one construction point for every LLM the engine uses.

The contract is LangChain's ``BaseChatModel`` so the serving backend is a
config choice, not a code change:

- ``vertexai`` (default): Gemini on Vertex AI — same ADC auth as the rest of
  the app (``GOOGLE_CLOUD_PROJECT``/``GOOGLE_CLOUD_LOCATION``).
- ``openai_compatible``: any OpenAI-compatible endpoint — vLLM or Ollama
  serving a local model (e.g. Typhoon/Qwen) for the on-prem deployment.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)

# Optional observability hook: called with (call_site, model_name, latency_ms,
# ok). OpenTelemetry/Langfuse instrumentation can attach here via config
# without touching node code.
InstrumentationHook = Callable[[str, str, int, bool], Awaitable[None] | None]


def build_chat_model(settings: Any) -> BaseChatModel:
    provider = getattr(settings, "screening_model_provider", "vertexai")
    model_name = getattr(settings, "screening_model_name", "gemini-2.5-flash")

    if provider == "openai_compatible":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            base_url=settings.screening_openai_base_url,
            api_key=settings.screening_openai_api_key or "not-needed",
            temperature=0.1,
        )

    if provider == "vertexai":
        from langchain_google_vertexai import ChatVertexAI

        return ChatVertexAI(
            model_name=model_name,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            temperature=0.1,
        )

    raise ValueError(f"Unknown screening_model_provider: {provider!r}")
