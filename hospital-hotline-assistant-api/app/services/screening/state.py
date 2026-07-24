"""Per-session screening state.

Serialized to ``screening_sessions.state`` (JSONB) between turns. Each chat
turn is one bounded graph invocation: load → run → save.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Phase = Literal[
    "intake", "history", "disposed", "follow_up", "done", "escalated_to_nurse"
]


OLDCARTS_SLOTS = (
    "onset", "location", "duration", "character",
    "aggravating", "relieving", "timing", "severity",
)


class Finding(BaseModel):
    state: Literal["present", "absent"]
    value: str | None = None
    source_turn: int = 0


class TurnOutput(BaseModel):
    """What one graph invocation produced for the transport layer."""

    reply: str = ""
    classification: dict[str, Any] = Field(default_factory=dict)
    escalated: bool = False
    # canonical vital key the engine is asking the booth to measure now
    # (e.g. "temp"); the transport layer pops a numeric input for it.
    awaiting_measurement: str | None = None
    # Localized quick-reply chips [{id, label}] under the assistant bubble.
    reply_options: list[dict[str, str]] = Field(default_factory=list)
    # True when the patient-facing flow is finished (incl. follow-up capture).
    flow_complete: bool = False
    # True for turns after disposition (follow-up capture / closing).
    post_disposition: bool = False


class ScreeningState(BaseModel):
    session_id: str
    language: Literal["en", "th"] = "th"
    mode: Literal["text", "voice"] = "text"
    turn_count: int = 0
    phase: Phase = "intake"

    patient_name: str | None = None  # HIS-recorded name from the linked visit
    chief_complaint: str | None = None
    complaint_category: str | None = None
    slots: dict[str, str] = Field(default_factory=dict)  # OLDCARTS slot -> answer text
    findings: dict[str, Finding] = Field(default_factory=dict)
    vitals: dict[str, float] = Field(default_factory=dict)
    age_years: float | None = None
    age_asked: bool = False

    asked_question_ids: list[str] = Field(default_factory=list)
    questions_asked: int = 0
    pending_question_id: str | None = None
    awaiting_measurement: str | None = None  # vital the booth must measure next
    extraction_failures: int = 0

    disposition: dict[str, Any] | None = None    # serialized DispositionResult
    classification: dict[str, Any] = Field(default_factory=dict)

    # Verbatim patient note captured in the post-disposition follow-up phase.
    patient_follow_up: str | None = None

    criteria_version_id: str | None = None
    prompt_version: str = "v1"

    def finding_states(self) -> dict[str, str]:
        return {fid: f.state for fid, f in self.findings.items()}

    def answered_slots(self) -> frozenset[str]:
        return frozenset(self.slots)

    @classmethod
    def from_json(cls, payload: str | dict[str, Any]) -> "ScreeningState":
        if isinstance(payload, str):
            return cls.model_validate_json(payload)
        return cls.model_validate(payload)

    def to_json(self) -> str:
        return self.model_dump_json()
