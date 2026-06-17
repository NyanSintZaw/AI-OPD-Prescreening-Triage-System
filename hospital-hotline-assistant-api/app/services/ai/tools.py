"""Function tools exposed to the ADK agents."""

from __future__ import annotations

from typing import Any

from app.services.ai.reference_data import (
    get_department_reference_data,
    get_triage_reference_data,
)


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
    get_triage_reference and following the decision_tree. Set needs_emergency_contact=True
    for Level 1 and Level 2. For Level 1: classify immediately without follow-ups.
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
        "needs_emergency_contact": needs_emergency_contact,
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


def collect_emergency_contact(
    patient_name: str,
    phone_number: str,
    address: str,
) -> dict:
    """Collect patient contact for ambulance dispatch. Only call this AFTER
    classify_triage_level has been called with needs_emergency_contact=True."""

    return {
        "contact_collected": True,
        "patient_name": patient_name,
        "phone_number": phone_number,
        "address": address,
    }
