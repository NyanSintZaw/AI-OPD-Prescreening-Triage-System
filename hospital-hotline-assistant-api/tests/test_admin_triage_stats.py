"""The admin bands added to /admin/triage-stats: funnel, weekday matrix, daily.

The nurse dashboard only ever read `sessions`/`screened` out of `daily`. The
admin tiles each carry a sparkline, so every column they plot has to survive
the round trip — including `avg_latency_ms`, which arrives from asyncpg as a
Decimal and must not reach the client as one.
"""

from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_connection
from app.main import app
from app.routers.deps import get_current_admin_user

QUEUE = {"pending": 4, "oldest_minutes": Decimal("37")}
AGREEMENT = {"reviewed": 10, "confirmed": 8, "rerouted": 2, "avg_review_minutes": Decimal("6")}
FUNNEL = {
    "started": 40,
    "disposed": 31,
    "reviewed": 22,
    "his_pushed": 19,
    "his_failed": 2,
    "his_skipped": 1,
}


def _daily(day, **over):
    base = {
        "date": date(2026, 8, day),
        "sessions": 6,
        "screened": 5,
        "reviewed": 4,
        "rerouted": 1,
        "escalated": 0,
        "avg_latency_ms": Decimal("1506"),
    }
    return {**base, **over}


class _FakeConn:
    """Answers each statement by what it selects, and records the SQL."""

    def __init__(self):
        self.seen: list[str] = []
        self.calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql, *args):
        self.seen.append(sql)
        self.calls.append((sql, args))
        if "AS pending" in sql:
            return QUEUE
        if "AS started" in sql:
            return FUNNEL
        return AGREEMENT

    async def fetch(self, sql, *args):
        self.seen.append(sql)
        self.calls.append((sql, args))
        if "AS weekday" in sql:
            # Dense 7 x 24 — one non-zero cell so the client has a max > 0.
            return [
                {"weekday": w, "hour": h, "count": 3 if (w, h) == (2, 9) else 0}
                for w in range(7)
                for h in range(24)
            ]
        if "AS date" in sql:
            return [_daily(25), _daily(26, sessions=0, screened=0, avg_latency_ms=None)]
        if "AS level" in sql:
            return [{"level": 3, "count": 5}]
        if "AS hour" in sql:
            return [{"hour": h, "count": 0} for h in range(24)]
        return []  # departments


@pytest.fixture()
def stats_client():
    conn = _FakeConn()
    app.dependency_overrides[get_current_admin_user] = lambda: {
        "id": "u1", "email": "ops@x", "role": "super_admin", "is_active": True
    }
    app.dependency_overrides[get_connection] = lambda: conn
    yield conn
    app.dependency_overrides.clear()


async def _get(query: str = ""):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get(f"/admin/triage-stats{query}")


async def test_funnel_stages_are_returned(stats_client):
    body = (await _get()).json()
    assert body["funnel"] == FUNNEL
    # Every stage is a subset of the one before it, which is the only reason
    # the drop between two stages means anything.
    f = body["funnel"]
    assert f["started"] >= f["disposed"] >= f["reviewed"]


async def test_weekday_matrix_is_dense(stats_client):
    cells = (await _get()).json()["weekday_hourly"]
    assert len(cells) == 7 * 24
    assert {(c["weekday"], c["hour"]) for c in cells} == {
        (w, h) for w in range(7) for h in range(24)
    }
    assert next(c for c in cells if c["count"]) == {"weekday": 2, "hour": 9, "count": 3}


async def test_daily_carries_the_sparkline_columns(stats_client):
    rows = (await _get()).json()["daily"]
    assert set(rows[0]) == {
        "date", "sessions", "screened", "reviewed", "rerouted", "escalated", "avg_latency_ms",
    }
    # Decimal -> int, or the client gets "1506" and formats a string as a number.
    assert rows[0]["avg_latency_ms"] == 1506
    assert isinstance(rows[0]["avg_latency_ms"], int)
    # A day the AI never ran has no latency — not a zero, which would drag the
    # sparkline to the floor and read as "instant".
    assert rows[1]["avg_latency_ms"] is None


async def test_window_reaches_every_new_query(stats_client):
    """The funnel and the weekday matrix see the same window as everything else.

    Asserted through the arguments, not the SQL text: how the bound is spelled
    is the endpoint's business — it has already been a rolling interval and an
    explicit pair — but a panel silently reading a different period from the
    one beside it is a real defect.
    """
    await _get("?days=30")
    windowed = [
        (sql, args)
        for sql, args in stats_client.calls
        if "AS started" in sql or "AS weekday" in sql
    ]
    assert len(windowed) == 2
    bounds = {args for _, args in windowed}
    assert len(bounds) == 1, "the two queries were given different windows"
    assert all(args for _, args in windowed), "a query ran unbounded"
