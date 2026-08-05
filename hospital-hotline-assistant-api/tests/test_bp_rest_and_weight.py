"""Unit tests for BP rest-window helpers and weight/height recency skip."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.bp_rest import (
    REST_DURATION,
    compute_rest_until,
    is_hypertensive_crisis,
)
from app.services.screening.weight_height import (
    WEIGHT_HEIGHT_RECENCY,
    merge_recent_weight_height_into_vitals,
    recent_weight_height,
)


def test_hypertensive_crisis_thresholds():
    assert is_hypertensive_crisis(181, 80) is True
    assert is_hypertensive_crisis(180, 80) is False  # gt, not ge
    assert is_hypertensive_crisis(120, 111) is True
    assert is_hypertensive_crisis(120, 110) is False
    assert is_hypertensive_crisis(120, 80) is False
    assert is_hypertensive_crisis(None, None) is False


def test_compute_rest_until_is_15_minutes():
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    until = compute_rest_until(now=now)
    assert until - now == REST_DURATION
    assert until == now + timedelta(minutes=15)


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


# ── recheck lifecycle (rest once, confirmatory reading proceeds) ─────────────


class _WindowConn:
    """Fake conn tracking bp_rest_windows rows for lifecycle tests."""

    def __init__(self, prior_rows: int = 0):
        self.prior_rows = prior_rows
        self.opened = 0
        self.resolved = 0

    async def fetchrow(self, sql, *args):
        if "SELECT 1 FROM bp_rest_windows" in sql:
            return {"?column?": 1} if self.prior_rows else None
        return None

    async def execute(self, sql, *args):
        if "INSERT INTO bp_rest_windows" in sql:
            self.opened += 1
        if "SET resolved_at" in sql:
            self.resolved += 1
        return "OK"


async def test_first_crisis_has_no_prior_window():
    from app.services.bp_rest import has_prior_window

    conn = _WindowConn(prior_rows=0)
    assert await has_prior_window(conn, hn="09900001") is False
    conn2 = _WindowConn(prior_rows=1)
    assert await has_prior_window(conn2, hn="09900001") is True
    # No key → never a window (anonymous flows degrade gracefully).
    assert await has_prior_window(_WindowConn(1)) is False


async def test_resolve_windows_marks_open_rows():
    from app.services.bp_rest import resolve_windows_for

    conn = _WindowConn()
    await resolve_windows_for(conn, hn="09900001")
    assert conn.resolved == 1
    conn2 = _WindowConn()
    await resolve_windows_for(conn2)  # no key → no-op
    assert conn2.resolved == 0


def test_turn_context_strips_pending_recheck_bp():
    # The crisis reading that opened the window must NOT reach the rules
    # engine — only the post-rest confirmatory reading may (meeting flow).
    from app.services.triage_service import _turn_context

    ctx = _turn_context({
        "vitals": {
            "systolic": 190, "diastolic": 115, "pulse_bpm": 90,
            "temperature": 37.2, "bp_recheck_pending": True,
        },
    })
    assert ctx is not None
    vitals = ctx["vitals"]
    assert "systolic" not in vitals and "diastolic" not in vitals
    assert vitals["temperature"] == 37.2          # other vitals still flow
    assert "bp_recheck_pending" not in vitals

    # Without the flag, BP flows to the engine untouched.
    ctx2 = _turn_context({"vitals": {"systolic": 190, "diastolic": 115}})
    assert ctx2 is not None and ctx2["vitals"]["systolic"] == 190


# ── Cuff records that are not possible readings ───────────────────────────
#
# A slipped cuff or a record read mid-cycle can report numbers no body
# produces. Those must be discarded at the parser, because 300/220 would
# otherwise satisfy "sbp > 180" and both open a rest window and dispose an
# emergency off a measurement that never happened.

def _omblepy_stdout(records):
    import json as _json

    from app.services.blood_pressure import _RESULT_MARKER

    return (
        "communication finished\n"
        + _RESULT_MARKER
        + _json.dumps([records])
        + "\n"
    )


def _record(sys_, dia, bpm, when):
    return {"sys": sys_, "dia": dia, "bpm": bpm, "datetime": when}


def test_parser_discards_implausible_records():
    from app.services.blood_pressure import _parse_result_json

    reading, discarded = _parse_result_json(_omblepy_stdout([
        _record(300, 220, 80, "2026-08-03 10:00:00"),
    ]))
    assert reading is None
    assert discarded == 1


def test_parser_keeps_a_real_crisis_reading():
    from app.services.blood_pressure import _parse_result_json

    reading, discarded = _parse_result_json(_omblepy_stdout([
        _record(250, 130, 92, "2026-08-03 10:00:00"),
    ]))
    assert discarded == 0
    assert reading is not None and reading.systolic == 250


def test_a_newer_garbage_record_cannot_mask_an_older_good_one():
    """The newest record normally wins — but not when it isn't a reading."""
    from app.services.blood_pressure import _parse_result_json

    reading, discarded = _parse_result_json(_omblepy_stdout([
        _record(118, 76, 70, "2026-08-03 10:00:00"),
        _record(300, 220, 80, "2026-08-03 10:05:00"),  # newer, impossible
    ]))
    assert discarded == 1
    assert reading is not None and reading.systolic == 118


def test_implausible_only_batch_is_not_reported_as_no_records():
    """The patient is told to measure again, not that the monitor is empty."""
    from app.services.blood_pressure import _parse_result_json

    reading, discarded = _parse_result_json(_omblepy_stdout([
        _record(5, 3, 40, "2026-08-03 10:00:00"),
    ]))
    assert reading is None and discarded == 1
