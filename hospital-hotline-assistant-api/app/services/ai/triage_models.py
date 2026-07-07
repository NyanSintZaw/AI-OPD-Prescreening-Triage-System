"""Shared triage result and engine model types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol


@dataclass
class TriageResult:
    reply: str
    severity_level: str
    severity_explanation: str | None
    severity_confidence: float | None
    department_id: str | None
    department_reason: str | None
    department_confidence: float | None
    emergency_trigger_id: str | None
    emergency_alert_message: str | None
    detected_symptoms: list[str]
    follow_up_question: str | None
    follow_up_reason: str | None
    model_name: str | None
    latency_ms: int
    alert_sent: bool
    raw_text: str
    pain_score: int | None
    pain_location: str | None
    distress_score: int | None
    distress_type: str | None
    red_flags: list[str]
    contact: dict[str, Any]



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
        schedule_context: str | None = None,
        turn_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the model turn result with reply/classification/contact.

        ``turn_context`` carries objective, non-LLM inputs (age, measured
        vitals) the deterministic engine merges into state before deciding.
        """

    async def run_turn_stream(
        self,
        *,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
        schedule_context: str | None = None,
        turn_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream model events for a turn."""

    async def ensure_session(
        self, *, session_id: str, language: str, input_mode: str
    ) -> None:
        """Ensure session state exists for this triage engine."""

    def decision_from_classification(self, classification: dict[str, Any]) -> TriageDecision:
        """Normalize a model classification dict to a stable decision object."""
