"""Payload mappers for triage service results."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.ai.triage_models import TriageResult


def should_redact_patient_severity() -> bool:
    """Patients never see the triage level — they only get the department
    destination (nurse requirement / SRS scope boundary). Nurse/admin surfaces
    read the DB rows and are unaffected."""

    return True


def severity_payload(result: TriageResult, *, redact: bool | None = None) -> dict[str, Any]:
    if redact is None:
        redact = should_redact_patient_severity()
    if redact:
        return {"level": "unknown", "explanation": None, "confidence": None}
    return {
        "level": result.severity_level,
        "explanation": result.severity_explanation,
        "confidence": result.severity_confidence,
    }


def assessment_status(result: TriageResult) -> str:
    return "complete" if result.severity_level != "unknown" else "in_progress"


def _triage_result_to_payload(result: TriageResult) -> dict[str, Any]:
    """Coerce :class:`TriageResult` into the same JSON shape the
    existing ``/sessions/{id}/chat`` REST response uses.

    Keeping the schema identical between streaming and non-streaming
    means the frontend can re-use its existing ``ChatResponsePayload``
    parser for the terminal ``complete`` event.
    """

    return {
        "reply": result.reply,
        "severity": severity_payload(result),
        "assessment_status": assessment_status(result),
        "department": (
            {
                "department_id": result.department_id,
                "reason": result.department_reason,
                "confidence": result.department_confidence,
            }
            if result.department_id
            else None
        ),
        "emergency": (
            {
                "trigger_id": result.emergency_trigger_id,
                "alert_message": result.emergency_alert_message,
                "detected_symptoms": result.detected_symptoms,
            }
            if result.emergency_trigger_id or result.emergency_alert_message
            else None
        ),
        "symptoms": {
            "raw_text": result.raw_text,
            "body_location": None,
            "duration_text": None,
            "pain_score": result.pain_score,
            "pain_location": result.pain_location,
            "distress_score": result.distress_score,
            "distress_type": result.distress_type,
            "red_flags": result.red_flags,
        },
        "follow_up_question": result.follow_up_question,
        "follow_up_reason": result.follow_up_reason,
        "alert_sent": result.alert_sent,
        "model_name": result.model_name,
        "latency_ms": result.latency_ms,
        "contact": result.contact or None,
        "awaiting_measurement": result.awaiting_measurement,
    }
