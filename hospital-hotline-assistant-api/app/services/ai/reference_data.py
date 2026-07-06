"""Reference-data loading for ADK triage tools."""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR: pathlib.Path = pathlib.Path(__file__).parents[2] / "data"

_TRIAGE_FILE = DATA_DIR / "er_triage_five_level_system.json"
_DEPARTMENTS_FILE = DATA_DIR / "departments.json"

_TRIAGE_FALLBACK: dict[str, Any] = {
    "knowledge_base": "ER Triage Five-Level System fallback",
    "source": "built-in minimal fallback",
    "source_id": "built_in_default",
    "note": (
        "ยังไม่มีการอัปโหลดคู่มือการคัดกรองผู้ป่วย "
        "กรุณาแจ้งผู้ดูแลระบบเพื่ออัปโหลดไฟล์ PDF คู่มือโรงพยาบาล "
        "(No hospital triage manual has been uploaded yet. "
        "Please ask the admin to upload the hospital PDF manual.)"
    ),
    "decision_tree": {
        "step1": (
            "Is the patient dying (unresponsive, pulseless, not breathing)? "
            "If YES → Level 1"
        ),
        "step2": (
            "High-risk situation, confusion, severe pain (≥7/10), or acute distress? "
            "If YES → Level 2"
        ),
        "step3": (
            "Count expected resources: 0 → Level 5, 1 → Level 4, ≥2 → Step 4"
        ),
        "step4": (
            "Danger-zone vitals (HR<50 or >180, SpO2<90%, RR<10 or >40, SBP<90 mmHg)? "
            "YES → upgrade to Level 2, NO → Level 3"
        ),
    },
    "triage_levels": [
        {
            "level": 1,
            "color": "red",
            "label": "Immediate / ฉุกเฉินวิกฤต",
            "response_time": "Immediate",
            "description": "Life-threatening. Requires immediate physician intervention.",
        },
        {
            "level": 2,
            "color": "orange",
            "label": "Emergency / ฉุกเฉินเร่งด่วน",
            "response_time": "≤10 minutes",
            "description": "High-risk, confused, severe pain, or dangerous vital signs.",
        },
        {
            "level": 3,
            "color": "yellow",
            "label": "Urgent / ฉุกเฉิน",
            "response_time": "≤30 minutes",
            "description": "Multiple resources expected. Stable but needs prompt care.",
        },
        {
            "level": 4,
            "color": "green",
            "label": "Less-Urgent / กึ่งฉุกเฉิน",
            "response_time": "≤60 minutes",
            "description": "Single resource expected. Non-urgent presentation.",
        },
        {
            "level": 5,
            "color": "blue",
            "label": "Non-Urgent / ไม่ฉุกเฉิน",
            "response_time": "≤120 minutes",
            "description": "No resources expected. Minor complaint.",
        },
    ],
}


def _load_triage_reference() -> dict[str, Any]:
    try:
        with _TRIAGE_FILE.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning(
            "Could not load %s (%s); using minimal fallback",
            _TRIAGE_FILE.name,
            exc,
        )
        return _TRIAGE_FALLBACK


def _load_departments() -> list[dict[str, Any]]:
    fallback: list[dict[str, Any]] = [
        {"code": "emergency", "name": "Emergency & Trauma"}
    ]
    try:
        with _DEPARTMENTS_FILE.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        departments = payload.get("departments")
        if isinstance(departments, list) and departments:
            return departments
        logger.warning(
            "departments.json missing 'departments' key or empty; using fallback"
        )
        return fallback
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("Could not load departments.json (%s); using fallback", exc)
        return fallback


_TRIAGE_REF: dict[str, Any] = _load_triage_reference()
_DEPARTMENTS: list[dict[str, Any]] = _load_departments()


def get_triage_reference_data() -> dict[str, Any]:
    return _TRIAGE_REF


def get_department_reference_data() -> list[dict[str, Any]]:
    return _DEPARTMENTS


def reload_triage_reference() -> None:
    """Re-read er_triage_five_level_system.json and refresh the in-memory cache.

    Call this after a new PDF has been ingested so the ADK triage agents
    immediately see the updated hospital-specific rules without restarting.
    """
    global _TRIAGE_REF
    _TRIAGE_REF = _load_triage_reference()
    source = _TRIAGE_REF.get("source", "unknown")
    logger.info("Triage reference reloaded (source=%s).", source)
