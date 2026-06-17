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


def _load_triage_reference() -> dict[str, Any]:
    with _TRIAGE_FILE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
