"""Unit tests for session resume lookup by patient HN."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services.session_resume import find_active_session_by_hn


class _FakeConnection:
    """Minimal asyncpg stand-in that records the lookup and returns a canned row."""

    def __init__(self, row=None):
        self.row = row
        self.last_sql: str | None = None
        self.last_args: tuple | None = None

    async def fetchrow(self, sql: str, *args):
        self.last_sql = sql
        self.last_args = args
        return self.row


@pytest.mark.asyncio
async def test_find_active_empty_hn_skips_query():
    conn = _FakeConnection(row={"id": "x"})
    assert await find_active_session_by_hn(conn, "") is None
    assert await find_active_session_by_hn(conn, "   ") is None
    assert conn.last_sql is None


@pytest.mark.asyncio
async def test_find_active_queries_metadata_hn_and_active_status():
    session_id = uuid4()
    row = {
        "id": session_id,
        "status": "active",
        "language": "th",
        "started_at": datetime.now(timezone.utc),
        "ended_at": None,
        "user_agent": None,
        "ip_hash": None,
        "metadata": {
            "patient": {
                "hn": "09900001",
                "patient_name": "Somchai",
            }
        },
    }
    conn = _FakeConnection(row=row)
    found = await find_active_session_by_hn(conn, "  09900001  ")
    assert found is row
    assert conn.last_args == ("09900001", 12)
    assert conn.last_sql is not None
    assert "status IN ('active', 'completed')" in conn.last_sql
    assert "metadata->'patient'->>'hn'" in conn.last_sql
    # Many sessions per HN: only the newest is offered for resume.
    assert "ORDER BY started_at DESC" in conn.last_sql
    assert "LIMIT 1" in conn.last_sql
    # Abandoned runs from previous days must not hijack the HN — an HN is a
    # lifelong identity, so the window matters even more than for VNs.
    assert "make_interval(hours => $2)" in conn.last_sql


@pytest.mark.asyncio
async def test_find_active_returns_none_when_no_row():
    conn = _FakeConnection(row=None)
    assert await find_active_session_by_hn(conn, "09900099") is None


def test_session_by_hn_out_schema():
    from app.schemas import SessionByHnOut, SessionOut

    empty = SessionByHnOut(found=False, hn="09900001")
    assert empty.session is None
    assert empty.patient_name is None

    sid = uuid4()
    now = datetime.now(timezone.utc)
    filled = SessionByHnOut(
        found=True,
        hn="09900001",
        patient_name="Ada",
        session=SessionOut(
            id=sid,
            language="en",
            status="active",
            started_at=now,
            ended_at=None,
            user_agent=None,
            ip_hash=None,
            metadata={"patient": {"hn": "09900001", "patient_name": "Ada"}},
        ),
    )
    assert filled.session is not None
    assert filled.session.id == sid
