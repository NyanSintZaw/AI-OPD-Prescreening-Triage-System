"""Unit tests for the weight/height HN-recency skip (self-reported at the
booth when the HIS has no recent measurement)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.screening.weight_height import (
    WEIGHT_HEIGHT_RECENCY,
    merge_recent_weight_height_into_vitals,
    recent_weight_height,
)


def test_recent_weight_height_within_window():
    now = datetime(2026, 7, 21, tzinfo=timezone.utc)
    measured = (now - timedelta(days=30)).isoformat()
    out = recent_weight_height(
        last_weight_kg=70.5,
        last_height_cm=165,
        vitals_measured_at=measured,
        now=now,
    )
    assert out == {"weight_kg": 70.5, "height_cm": 165.0}


def test_recent_weight_height_stale_or_incomplete():
    now = datetime(2026, 7, 21, tzinfo=timezone.utc)
    stale = (now - WEIGHT_HEIGHT_RECENCY - timedelta(days=1)).isoformat()
    assert recent_weight_height(
        last_weight_kg=70, last_height_cm=165, vitals_measured_at=stale, now=now
    ) == {}
    assert recent_weight_height(
        last_weight_kg=70, last_height_cm=None,
        vitals_measured_at=now.isoformat(), now=now,
    ) == {}


def test_merge_does_not_overwrite_fresh_session_vitals():
    history = SimpleNamespace(
        last_weight_kg=70,
        last_height_cm=165,
        vitals_measured_at=datetime.now(timezone.utc).isoformat(),
    )
    merged = merge_recent_weight_height_into_vitals(
        {"weight_kg": 72, "height_cm": 166}, history
    )
    assert merged["weight_kg"] == 72
    assert merged["height_cm"] == 166

    filled = merge_recent_weight_height_into_vitals({}, history)
    assert filled["weight_kg"] == 70
    assert filled["height_cm"] == 165
    assert filled["source"] == "his_recent"
