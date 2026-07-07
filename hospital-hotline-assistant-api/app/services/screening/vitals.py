"""Normalize kiosk/HIS vitals into the canonical keys the rules engine uses.

The blood-pressure kiosk and the HIS record vitals as ``systolic`` /
``diastolic`` / ``pulse_bpm`` / ``temperature``; the criteria conditions
(danger vitals) read ``sbp`` / ``dbp`` / ``hr`` / ``rr`` / ``map``. This is
the single place that bridge is defined.
"""

from __future__ import annotations

from typing import Any, Mapping

# raw kiosk/HIS key -> canonical rules-engine key
_ALIASES: dict[str, str] = {
    "systolic": "sbp",
    "sbp": "sbp",
    "diastolic": "dbp",
    "dbp": "dbp",
    "pulse": "hr",
    "pulse_bpm": "hr",
    "hr": "hr",
    "heart_rate": "hr",
    "rr": "rr",
    "respiratory_rate": "rr",
    "temperature": "temp",
    "temp": "temp",
    "spo2": "spo2",
    "pain_score": "pain_score",
}


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_vitals(raw: Mapping[str, Any] | None) -> dict[str, float]:
    """Return canonical numeric vitals, dropping unusable/absent values.

    Derives mean arterial pressure (``map``) from sbp/dbp when both are
    present, matching how the manual's danger-vital rules reference it.
    """
    if not raw:
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        canonical = _ALIASES.get(str(key).lower())
        if canonical is None:
            continue
        num = _to_float(value)
        if num is not None:
            out[canonical] = num
    if "sbp" in out and "dbp" in out and "map" not in out:
        out["map"] = round(out["dbp"] + (out["sbp"] - out["dbp"]) / 3, 1)
    return out
