"""Helpers for skipping weight/height when a recent HN measurement exists."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Clinical default for "recent enough to skip re-asking at the booth".
# Stakeholders can tighten later; 90 days matches the plan's proposed range.
WEIGHT_HEIGHT_RECENCY = timedelta(days=90)


def _parse_iso(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def recent_weight_height(
    *,
    last_weight_kg: float | None,
    last_height_cm: float | None,
    vitals_measured_at: str | None,
    now: datetime | None = None,
    max_age: timedelta = WEIGHT_HEIGHT_RECENCY,
) -> dict[str, float]:
    """Return ``{weight_kg, height_cm}`` when a recent HN measurement exists.

    Empty dict when either value is missing or the stamp is older than
    ``max_age`` / unparseable — the booth should then ask normally.
    """
    measured_at = _parse_iso(vitals_measured_at)
    if measured_at is None:
        return {}
    if last_weight_kg is None or last_height_cm is None:
        return {}
    try:
        weight = float(last_weight_kg)
        height = float(last_height_cm)
    except (TypeError, ValueError):
        return {}
    if weight <= 0 or height <= 0:
        return {}
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    if measured_at < anchor - max_age:
        return {}
    return {"weight_kg": weight, "height_cm": height}


def merge_recent_weight_height_into_vitals(
    vitals: dict[str, Any],
    patient_history: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prefill session vitals from HN last weight/height when recent.

    Does not overwrite a fresh cuff/manual weight or height already on the
    session for this visit.
    """
    if patient_history is None:
        return vitals
    recent = recent_weight_height(
        last_weight_kg=getattr(patient_history, "last_weight_kg", None),
        last_height_cm=getattr(patient_history, "last_height_cm", None),
        vitals_measured_at=getattr(patient_history, "vitals_measured_at", None),
        now=now,
    )
    if not recent:
        return vitals
    merged = dict(vitals)
    if merged.get("weight_kg") is None and merged.get("weight") is None:
        merged["weight_kg"] = recent["weight_kg"]
        merged.setdefault("source", "his_recent")
    if merged.get("height_cm") is None and merged.get("height") is None:
        merged["height_cm"] = recent["height_cm"]
        merged.setdefault("source", "his_recent")
    return merged
