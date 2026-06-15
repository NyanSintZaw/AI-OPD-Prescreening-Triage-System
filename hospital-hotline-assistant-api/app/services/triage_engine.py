from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

from app.services.adk_agent import HotlineADKRunner


@dataclass
class TriageDecision:
    """Normalized triage decision independent from the conversation transport."""

    esi_level: int | None
    severity_level: str
    opd_department_code: str | None
    key_reason: str | None
    symptoms_summary: str | None
    needs_emergency_contact: bool
    classification: dict[str, Any]


class TriageEngine(Protocol):
    async def run_turn(
        self,
        *,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
    ) -> dict[str, Any]:
        """Return the model turn result with reply/classification/contact."""

    async def run_turn_stream(
        self,
        *,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream model events for a turn."""

    async def ensure_session(
        self, *, session_id: str, language: str, input_mode: str
    ) -> None:
        """Ensure session state exists for this triage engine."""

    def decision_from_classification(self, classification: dict[str, Any]) -> TriageDecision:
        """Normalize a model classification dict to a stable decision object."""


class LlmTriageEngine:
    """Current triage engine implementation backed by ADK/Gemini."""

    _LEVEL_TO_SEVERITY: dict[int, str] = {
        1: "emergency",
        2: "emergency",
        3: "urgent",
        4: "general",
        5: "general",
    }

    def __init__(self, runner: HotlineADKRunner | None = None) -> None:
        self._runner = runner or HotlineADKRunner()

    async def run_turn(
        self,
        *,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
    ) -> dict[str, Any]:
        return await self._runner.chat(
            session_id=session_id,
            language=language,
            user_message=content,
            input_mode=input_mode,
        )

    async def run_turn_stream(
        self,
        *,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in self._runner.chat_stream(
            session_id=session_id,
            language=language,
            user_message=content,
            input_mode=input_mode,
        ):
            yield event

    async def ensure_session(
        self, *, session_id: str, language: str, input_mode: str
    ) -> None:
        await self._runner.ensure_adk_session(session_id, language, input_mode)

    def decision_from_classification(self, classification: dict[str, Any]) -> TriageDecision:
        level = classification.get("level")
        esi_level = level if isinstance(level, int) else None
        severity = self._LEVEL_TO_SEVERITY.get(esi_level, "unknown")
        department_code = classification.get("department_code")
        dept = str(department_code) if department_code else None

        return TriageDecision(
            esi_level=esi_level,
            severity_level=severity,
            opd_department_code=dept,
            key_reason=classification.get("key_reason"),
            symptoms_summary=classification.get("symptoms_summary"),
            needs_emergency_contact=bool(classification.get("needs_emergency_contact")),
            classification=classification,
        )
