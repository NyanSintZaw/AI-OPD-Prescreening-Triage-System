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


class _DropAdditionalPropertiesWarning(logging.Filter):
    """Silence the benign 'Key additionalProperties is not supported in schema,
    ignoring' spam.

    langchain-google-vertexai strips Pydantic's ``additionalProperties: false``
    because Gemini's schema dialect doesn't support it; the output is still
    constrained by the rest of the schema (verified benign — GH #1038). Passing
    Pydantic models to ``with_structured_output`` is the recommended approach,
    so we quiet the log rather than change the schema.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "additionalProperties" not in record.getMessage()


def _silence_schema_warning() -> None:
    for name in (
        "langchain_google_genai",
        "langchain_google_genai.chat_models",
        "langchain_google_genai._function_utils",
        # legacy package name, still filtered in case it's imported elsewhere
        "langchain_google_vertexai",
        "langchain_google_vertexai.functions_utils",
    ):
        logging.getLogger(name).addFilter(_DropAdditionalPropertiesWarning())

# Optional observability hook: called with (call_site, model_name, latency_ms,
# ok). OpenTelemetry/Langfuse instrumentation can attach here via config
# without touching node code.
InstrumentationHook = Callable[[str, str, int, bool], Awaitable[None] | None]


def build_chat_model(settings: Any) -> BaseChatModel:
    provider = getattr(settings, "screening_model_provider", "vertexai")
    model_name = getattr(settings, "screening_model_name", "gemini-2.5-flash")
    # Client-side deadline so a stalled call fails fast instead of hanging the
    # turn. The screening nodes also wrap every call in asyncio.wait_for
    # (belt-and-suspenders), but this gives the SDK a real deadline to honour.
    timeout_s = float(getattr(settings, "screening_model_timeout_s", 30.0))

    if provider == "openai_compatible":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            base_url=settings.screening_openai_base_url,
            api_key=settings.screening_openai_api_key or "not-needed",
            temperature=0.1,
            timeout=timeout_s,
            max_retries=1,
        )

    if provider == "vertexai":
        # langchain-google-genai (the consolidated google-genai SDK) with
        # ``vertexai=True`` is the supported replacement for the deprecated
        # ``langchain_google_vertexai.ChatVertexAI``. Same Vertex backend and
        # ADC auth (project + location, no api_key), just the unified client.
        from langchain_google_genai import ChatGoogleGenerativeAI

        _silence_schema_warning()
        return ChatGoogleGenerativeAI(
            model=model_name,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            vertexai=True,
            temperature=0.1,
            timeout=timeout_s,
            max_retries=1,
        )

    raise ValueError(f"Unknown screening_model_provider: {provider!r}")
