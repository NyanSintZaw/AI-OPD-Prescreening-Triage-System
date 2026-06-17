"""Gemini Live ADK runner for hotline voice calls."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.ai.env import configure_google_genai_environment

configure_google_genai_environment()

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.runners import Runner  # noqa: E402

from app.services.ai.agent_factory import (  # noqa: E402
    LIVE_APP_NAME,
    _SESSION_SERVICE,
    build_emergency_agent,
    build_orchestrator,
    build_triage_agent,
)
from app.services.ai.live_config import build_live_run_config  # noqa: E402

class HotlineADKLiveRunner:
    """Async facade around ADK's bidirectional live runner.

    Shares the same Orchestrator + sub-agents + tool set that
    :class:`HotlineADKRunner` uses, so a Level 1 / Level 2 classification
    in a voice call still fires ``classify_triage_level`` and triggers
    the EmergencyAgent handoff for contact collection. The only thing
    that differs from text mode is the runner's ``app_name`` (so ADK
    session state is namespaced separately) and the
    :meth:`run_live` entry point.
    """

    def __init__(self) -> None:
        # The Live API only accepts ``gemini-live-*-native-audio`` models, so
        # we override the agents' model here instead of the Pro-tier text
        # default. Reuses the same instructions / tools / sub-agent layout
        # as HotlineADKRunner — only the wire model changes.
        live_model = settings.google_live_model_name
        triage_agent = build_triage_agent(model_name=live_model)
        emergency_agent = build_emergency_agent(model_name=live_model)
        self._root_agent: LlmAgent = build_orchestrator(
            triage_agent, emergency_agent, model_name=live_model
        )
        self._runner: Runner = Runner(
            app_name=LIVE_APP_NAME,
            agent=self._root_agent,
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

    def build_run_config(self, language: str) -> Any:
        """Public wrapper around :func:`_build_live_run_config` so callers
        don't have to import the module-private helper.
        """

        return build_live_run_config(language)
