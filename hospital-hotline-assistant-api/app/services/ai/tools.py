"""Function tools exposed to the ADK agents."""

from __future__ import annotations

from typing import Any

from app.services.ai.rag_query import search_triage_manual_status
from app.services.ai.reference_data import (
    get_department_reference_data,
    get_triage_reference_data,
)


async def search_hospital_manual(query: str) -> str:
    """Search the hospital's official triage manual for guidelines, criteria,
    and department routing rules specific to this hospital.

    Call this with the patient's symptoms BEFORE classifying.
    Returns relevant sections from the uploaded hospital PDF.
    If no manual has been uploaded, returns a notice saying so.

    Examples:
    - search_hospital_manual("chest pain shortness of breath")
    - search_hospital_manual("stroke symptoms BEFAST")
    - search_hospital_manual("pediatric fever vital signs danger")
    - search_hospital_manual("อาการเจ็บหน้าอก หายใจไม่ออก")
    """
    try:
        from app.services.ai.rag_query import search_triage_manual
        return await search_triage_manual(query)
    except Exception as exc:
        return (
            f"Hospital manual search unavailable ({exc}). "
            "Use standard ESI guidelines."
        )


async def search_indexed_triage_manual(query: str, language: str = "en") -> dict:
    """Search the uploaded/indexed triage manual before static fallback.

    Call this first for patient symptoms in English or Thai. If the returned
    `available` field is false, continue with `get_triage_reference` and
    `get_department_list`.
    """

    return await search_triage_manual_status(query=query, language=language)


def get_triage_reference() -> dict:
    """Returns the complete ER Five-Level Triage system including decision_tree and
    triage_levels. ALWAYS call this before classifying. Follow decision_tree steps in order:
    Step 1 checks if dying (→Level 1). Step 2 checks high-risk/confused/severe pain (→Level 2).
    Step 3 checks resource count (none→Level 5, one→Level 4, many→proceed to Step 4).
    Step 4 checks danger zone vitals — if yes upgrade to Level 2, if no assign Level 3."""

    return get_triage_reference_data()


def get_department_list() -> list:
    """Returns available hospital departments. Use the exact department code
    (not name) in classify_triage_level.

    OPD-first policy:
    - Level 1–2 must use 'emergency'
    - Level 3–5 must use an 'opd_*' department code
    """

    return get_department_reference_data()


def classify_triage_level(
    symptoms_summary: str,
    level: int,
    color: str,
    label: str,
    key_reason: str,
    department_code: str,
    response_time: str,
    needs_emergency_contact: bool,
    pain_score: int = -1,
    pain_location: str = "",
    distress_score: int = -1,
    distress_type: str = "",
    red_flags: list[str] = None,
) -> dict:
    """Record the final triage classification. Only call after consulting
    get_triage_reference and following the decision_tree. Set needs_emergency_contact=False
    for every level; emergency is handled as a normal triage result.
    For Level 1: classify immediately without follow-ups.
    For Level 2: allow at most 1 follow-up question before classifying.

    Department policy:
    - Level 1-2: department_code must be 'emergency'
    - Level 3-5: department_code must be an OPD code (prefix 'opd_')

    Pain / distress fields are optional. Only include scores the caller
    actually gave. Pain and breathing distress are different scales.
    """

    def normalize_score(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            score = int(value)
        except (TypeError, ValueError):
            return None
        return score if 0 <= score <= 10 else None

    red_flag_items = red_flags if isinstance(red_flags, list) else [red_flags]

    return {
        "classified": True,
        "level": level,
        "color": color,
        "label": label,
        "key_reason": key_reason,
        "department_code": department_code,
        "response_time": response_time,
        "needs_emergency_contact": False,
        "symptoms_summary": symptoms_summary,
        "pain_score": normalize_score(pain_score),
        "pain_location": pain_location or None,
        "distress_score": normalize_score(distress_score),
        "distress_type": distress_type or None,
        "red_flags": [
            str(flag).strip()
            for flag in red_flag_items
            if flag is not None and str(flag).strip()
        ],
    }


def record_contact_preference(
    requested: bool | None,
    phone_number: str = "",
    preferred_time: str = "",
    relation: str = "",
    confidence: float = 0.0,
    needs_followup: bool = False,
    followup_question: str = "",
) -> dict:
    """Record a post-triage hospital-contact preference.

    This tool is only for the post-triage contact step. It must not be
    used for symptom assessment or department routing.
    """

    def clean(value: str) -> str | None:
        text = str(value or "").strip()
        return text or None

    try:
        normalized_confidence = float(confidence)
    except (TypeError, ValueError):
        normalized_confidence = 0.0
    normalized_confidence = max(0.0, min(1.0, normalized_confidence))

    return {
        "contact_preference_recorded": True,
        "requested": requested if isinstance(requested, bool) else None,
        "phone_number": clean(phone_number),
        "preferred_time": clean(preferred_time),
        "relation": clean(relation),
        "confidence": normalized_confidence,
        "needs_followup": bool(needs_followup),
        "followup_question": clean(followup_question),
    }
