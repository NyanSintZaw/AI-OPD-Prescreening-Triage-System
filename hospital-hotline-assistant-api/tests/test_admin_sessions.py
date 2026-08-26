"""The admin session log: filter wiring and the counts-are-unfiltered rule."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_connection
from app.main import app
from app.routers.deps import get_current_admin_user

COUNTS = {"sessions": 40, "abandoned": 14, "ai_errors": 2, "his_failed": 3, "unreviewed": 9}


def _row(**over):
    base = {
        "session_id": uuid4(),
        "language": "th",
        "status": "active",
        "started_at": datetime(2026, 8, 21, 4, 15, tzinfo=timezone.utc),
        "ended_at": None,
        "triage_level": 3,
        "patient_hn": "51204",
        "his_status": "pushed",
        "turns": 23,
        "avg_latency_ms": 1180,
        "duration_seconds": 372,
        "review_status": "pending",
        "proposed_department_en": "OPD General Practice",
        "proposed_department_th": "OPD อายุรกรรม",
        "confirmed_department_en": None,
        "confirmed_department_th": None,
        "vitals_measured": 3,
        "criteria_version": 1,
        "ai_error": False,
        "outcome": "disposed",
        "total_count": 412,
    }
    return {**base, **over}


class _FakeConn:
    """Records every statement so the test can assert on the SQL that ran."""

    def __init__(self, rows):
        self.rows = rows
        self.seen: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql, *args):
        self.seen.append((sql, args))
        return COUNTS

    async def fetch(self, sql, *args):
        self.seen.append((sql, args))
        return self.rows


@pytest.fixture()
def override_admin():
    app.dependency_overrides[get_current_admin_user] = lambda: {
        "id": "u1", "email": "ops@x", "role": "super_admin", "is_active": True
    }
    yield
    app.dependency_overrides.clear()


async def _call(query: str = "", rows=None):
    conn = _FakeConn(rows if rows is not None else [_row()])
    app.dependency_overrides[get_connection] = lambda: conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(f"/admin/sessions{query}")
    return resp, conn


async def test_returns_rows_counts_and_total(override_admin):
    resp, _ = await _call()
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"] == COUNTS
    assert body["total"] == 412
    assert body["window"] == "7d"
    row = body["rows"][0]
    assert row["outcome"] == "disposed"
    assert row["vitals_measured"] == 3
    # The paging total rides on the row and must not leak into the row model.
    assert "total_count" not in row


async def test_counts_ignore_the_active_filters(override_admin):
    """Clicking one exception must not zero the other three."""
    _, conn = await _call("?flag=his_failed&level=3&q=512")
    counts_sql, rows_sql = conn.seen[0][0], conn.seen[1][0]
    assert "his_status = 'failed'" not in counts_sql.split("FROM enriched")[1]
    assert "his_status = 'failed'" in rows_sql
    assert "triage_level = $" in rows_sql


async def test_search_matches_hn_or_session_id(override_admin):
    _, conn = await _call("?q=51204")
    rows_sql, params = conn.seen[1]
    assert "patient_hn ILIKE" in rows_sql and "session_id::text ILIKE" in rows_sql
    assert "51204%" in params


async def test_level_none_selects_undisposed_sessions(override_admin):
    _, conn = await _call("?level=none")
    assert "triage_level IS NULL" in conn.seen[1][0]


async def test_window_today_is_calendar_day_not_rolling(override_admin):
    _, conn = await _call("?window=today")
    assert "date_trunc('day', NOW())" in conn.seen[1][0]


async def test_window_all_drops_the_lower_bound(override_admin):
    _, conn = await _call("?window=all")
    assert "s.started_at >=" not in conn.seen[1][0]


async def test_unknown_window_is_rejected(override_admin):
    resp, _ = await _call("?window=lastyear")
    assert resp.status_code == 422


async def test_empty_page_still_reports_zero_total(override_admin):
    resp, _ = await _call("?flag=ai_error", rows=[])
    assert resp.json()["total"] == 0
    assert resp.json()["counts"]["ai_errors"] == 2
