"""Gemini Live ADK runner for hotline voice calls."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.ai.env import configure_google_genai_environment

configure_google_genai_environment()

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.genai import types as genai_types  # noqa: E402

from app.services.ai.agent_factory import (  # noqa: E402
    CONTACT_APP_NAME,
    LIVE_APP_NAME,
    _SESSION_SERVICE,
    build_contact_preference_agent,
    build_orchestrator,
    build_triage_agent,
)
from app.services.ai.live_config import build_live_run_config  # noqa: E402

class HotlineADKLiveRunner:
    """Async facade around ADK's bidirectional live runner.

    Shares the same Orchestrator + TriageAgent tool set that
    :class:`HotlineADKRunner` uses. The only thing that differs from
    text mode is the runner's ``app_name`` (so ADK session state is
    namespaced separately) and the
    :meth:`run_live` entry point.
    """

    def __init__(self) -> None:
        # The Live API only accepts ``gemini-live-*-native-audio`` models, so
        # we override the agents' model here instead of the Pro-tier text
        # default. Reuses the same instructions / tools / sub-agent layout
        # as HotlineADKRunner — only the wire model changes.
        live_model = settings.google_live_model_name
        triage_agent = build_triage_agent(
            model_name=live_model,
            include_contact_tool=True,
        )
        text_contact_agent = build_contact_preference_agent(
            model_name=settings.google_model_name
        )
        self._root_agent: LlmAgent = build_orchestrator(
            triage_agent,
            model_name=live_model,
        )
        self._runner: Runner = Runner(
            app_name=LIVE_APP_NAME,
            agent=self._root_agent,
            session_service=_SESSION_SERVICE,
        )
        self._contact_agent: LlmAgent = text_contact_agent
        self._contact_runner: Runner = Runner(
            app_name=CONTACT_APP_NAME,
            agent=self._contact_agent,
            session_service=_SESSION_SERVICE,
        )

    async def ensure_live_session(
        self, session_id: str, language: str
    ) -> None:
        """Idempotently materialise the live-mode ADK session.

        Mirrors :meth:`HotlineADKRunner.ensure_adk_session` but binds to
        the ``LIVE_APP_NAME`` namespace and pins ``input_mode`` to
        ``"voice"`` in initial state since this session is voice-only by
        definition.
        """

        existing = await _SESSION_SERVICE.get_session(
            app_name=LIVE_APP_NAME,
            user_id=session_id,
            session_id=session_id,
        )
        if existing is not None:
            return
        await _SESSION_SERVICE.create_session(
            app_name=LIVE_APP_NAME,
            user_id=session_id,
            session_id=session_id,
            state={
                "language": language,
                "session_id": session_id,
                "input_mode": "voice",
            },
        )

    async def get_live_session_handler(
        self, session_id: str, language: str
    ) -> Runner:
        """Make sure the ADK session is ready and return the underlying Runner.

        The caller drives the live pipeline by invoking ``runner.run_live(
        user_id=..., session_id=..., live_request_queue=..., run_config=...
        )``. The session must exist before ``run_live`` is called or ADK
        raises ``SessionNotFoundError``.
        """

        await self.ensure_live_session(session_id, language)
        return self._runner

    async def ensure_contact_session(self, session_id: str, language: str) -> None:
        existing = await _SESSION_SERVICE.get_session(
            app_name=CONTACT_APP_NAME,
            user_id=session_id,
            session_id=session_id,
        )
        if existing is not None:
            return
        await _SESSION_SERVICE.create_session(
            app_name=CONTACT_APP_NAME,
            user_id=session_id,
            session_id=session_id,
            state={
                "language": language,
                "session_id": session_id,
                "input_mode": "voice",
                "contact_phase": "contact_preference",
            },
        )

    async def run_contact_preference(
        self,
        session_id: str,
        language: str,
        user_message: str,
    ) -> tuple[str, dict[str, Any]]:
        """Run one post-triage contact-only turn through Gemini."""

        await self.ensure_contact_session(session_id, language)
        lang_code = language if language in {"en", "th"} else "en"
        lang_name = "English" if lang_code == "en" else "Thai"
        content = genai_types.Content(
            role="user",
            parts=[
                genai_types.Part(
                    text=(
                        "[PHASE: contact_preference]\n"
                        "[MODE: voice — reply in short spoken sentences, no formatting]\n"
                        f"[LANG: {lang_code} — reply EXCLUSIVELY in {lang_name}.]\n"
                        f"{user_message}"
                    )
                )
            ],
        )

        reply_chunks: list[str] = []
        contact: dict[str, Any] = {}
        async for event in self._contact_runner.run_async(
            user_id=session_id,
            session_id=session_id,
            new_message=content,
        ):
            event_content = getattr(event, "content", None)
            parts = getattr(event_content, "parts", None) or []
            is_final = False
            try:
                is_final = event.is_final_response()
            except Exception:
                is_final = False

            for part in parts:
                if is_final:
                    text = getattr(part, "text", None)
                    if text:
                        reply_chunks.append(text)

                func_response = getattr(part, "function_response", None)
                response_payload = (
                    getattr(func_response, "response", None)
                    if func_response is not None
                    else None
                )
                if (
                    isinstance(response_payload, dict)
                    and response_payload.get("contact_preference_recorded") is True
                ):
                    contact = dict(response_payload)

        return "".join(reply_chunks).strip(), contact

    def build_run_config(self, language: str) -> Any:
        """Public wrapper around :func:`_build_live_run_config` so callers
        don't have to import the module-private helper.
        """

        return build_live_run_config(language)
