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


RECENT_TURNS_MAX = 4  # two patient + two assistant lines

OLDCARTS_SLOTS = (
    "onset", "location", "duration", "character",
    "aggravating", "relieving", "timing", "severity",
)


class Finding(BaseModel):
    state: Literal["present", "absent"]
    value: str | None = None
    source_turn: int = 0
    # True when this finding was established by something stronger than
    # free-text extraction: the patient answered the question that checks it
    # (chip tap or verbatim ask), it came from the HIS record / history
    # intake, or it was derived from an instrument reading. Rules that would
    # alone dispose level 1–2 only fire on confirmed findings — an emergency
    # is never declared from inferred words (see graph.route_after_ingest).
    confirmed: bool = False
    # Exact patient words the extractor cited for this finding, and whether
    # they actually appear in the utterance — the nurse-trace audit line.
    evidence: str | None = None
    evidence_verified: bool | None = None


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
    # Complaints the patient replaced mid-interview ("พูดผิด ไม่ได้ปวดท้อง
    # เจ็บหน้าอก"): [{turn, category, chief_complaint}] before each switch,
    # newest last. Nurse-facing provenance; never read by the rules.
    complaint_history: list[dict[str, Any]] = Field(default_factory=list)
    slots: dict[str, str] = Field(default_factory=dict)  # OLDCARTS slot -> answer text
    findings: dict[str, Finding] = Field(default_factory=dict)
    vitals: dict[str, float] = Field(default_factory=dict)
    # Objective (cuff/HIS) readings, canonical keys — a record of which vitals
    # were instrument-measured; spoken/extracted values must never override.
    measured_vitals: dict[str, float] = Field(default_factory=dict)
    # Values rejected as physiologically impossible, keyed by canonical vital:
    # {value, reason, source, attempts, turn, text_en, text_th}. Kept even once
    # a good value arrives — nurse review shows the flagged number rather than
    # a blank, and the question node uses it to word the re-ask.
    rejected_vitals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    age_years: float | None = None
    age_asked: bool = False
    # Closed set: "male" | "female" | "unknown". "unknown" (missing HIS value,
    # declined answer, or any value outside the set) is the SAFE default —
    # rule evaluation treats it as matching every gender predicate (never
    # suppresses an escalation) and question policy treats it as "still ask"
    # (a gender-skippable question is only skipped on a definite mismatch).
    # Values come from the HIS record or the patient's own statement — never
    # inferred from name, voice, or symptoms.
    gender: Literal["male", "female", "unknown"] = "unknown"

    asked_question_ids: list[str] = Field(default_factory=list)
    questions_asked: int = 0
    pending_question_id: str | None = None
    # Present-but-unconfirmed finding ids currently blocking a level-1/2
    # disposition; the question node serves their confirm questions first.
    # Recomputed every turn by the red-flag gate — derived state, not history.
    pending_confirm: list[str] = Field(default_factory=list)
    # Critical findings the patient just retracted in free text after having
    # confirmed them ("ไม่ได้เหงื่อออกแล้ว" after a chip-tap yes). Set by
    # ingest for ONE routing decision: the graph asks the verbatim confirm
    # once before the retraction cancels a level-1/2 rule — the mirror of
    # confirm-before-fire, so an STT mis-hear can't silently stand down an
    # emergency. Cleared every turn.
    pending_retraction: list[str] = Field(default_factory=list)
    awaiting_measurement: str | None = None  # vital the booth must measure next
    extraction_failures: int = 0

    disposition: dict[str, Any] | None = None    # serialized DispositionResult
    classification: dict[str, Any] = Field(default_factory=dict)

    # Verbatim patient note captured in the post-disposition follow-up phase.
    patient_follow_up: str | None = None
    # The last two exchanges verbatim ({"role": "patient"|"assistant", "text"}),
    # so the question renderer can acknowledge what was just said instead of
    # firing each question in isolation (the "reading a template" feel).
    # Capped at RECENT_TURNS_MAX; never read by the rules engine.
    recent_turns: list[dict[str, str]] = Field(default_factory=list)

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
