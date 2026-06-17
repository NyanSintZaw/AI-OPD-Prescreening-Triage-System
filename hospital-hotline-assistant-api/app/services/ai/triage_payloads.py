"""Payload mappers for triage service results."""

from __future__ import annotations

from typing import Any

from app.services.ai.triage_models import TriageResult


def _triage_result_to_payload(result: TriageResult) -> dict[str, Any]:
    """Coerce :class:`TriageResult` into the same JSON shape the
    existing ``/sessions/{id}/chat`` REST response uses.

    Keeping the schema identical between streaming and non-streaming
    means the frontend can re-use its existing ``ChatResponsePayload``
    parser for the terminal ``complete`` event.
    """

    return {
        "reply": result.reply,
        "severity": {
            "level": result.severity_level,
            "explanation": result.severity_explanation,
            "confidence": result.severity_confidence,
        },
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
        "symptoms": None,
        "follow_up_question": result.follow_up_question,
        "follow_up_reason": result.follow_up_reason,
        "alert_sent": result.alert_sent,
        "model_name": result.model_name,
        "latency_ms": result.latency_ms,
    }
