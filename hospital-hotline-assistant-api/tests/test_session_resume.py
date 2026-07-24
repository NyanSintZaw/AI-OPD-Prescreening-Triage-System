"""Unit tests for session resume lookup by visit ID (VN)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services.session_resume import find_active_session_by_visit_id


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
async def test_find_active_empty_visit_id_skips_query():
    conn = _FakeConnection(row={"id": "x"})
    assert await find_active_session_by_visit_id(conn, "") is None
    assert await find_active_session_by_visit_id(conn, "   ") is None
    assert conn.last_sql is None


@pytest.mark.asyncio
async def test_find_active_queries_metadata_visit_id_and_active_status():
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
            "visit": {
                "visit_id": "990000000000000001",
                "patient_name": "Somchai",
            }
        },
    }
    conn = _FakeConnection(row=row)
    found = await find_active_session_by_visit_id(conn, "  990000000000000001  ")
    assert found is row
    assert conn.last_args == ("990000000000000001", 12)
    assert conn.last_sql is not None
    assert "status IN ('active', 'completed')" in conn.last_sql
    assert "metadata->'visit'->>'visit_id'" in conn.last_sql
    assert "ORDER BY started_at DESC" in conn.last_sql
    # Abandoned runs from previous days must not hijack the VN (E2E July 22).
    assert "make_interval(hours => $2)" in conn.last_sql


@pytest.mark.asyncio
async def test_find_active_returns_none_when_no_row():
    conn = _FakeConnection(row=None)
    assert await find_active_session_by_visit_id(conn, "990000000000000099") is None


def test_session_by_visit_out_schema():
    from app.schemas import SessionByVisitOut, SessionOut

    empty = SessionByVisitOut(found=False, visit_id="V1")
    assert empty.session is None
    assert empty.patient_name is None

    sid = uuid4()
    now = datetime.now(timezone.utc)
    filled = SessionByVisitOut(
        found=True,
        visit_id="V1",
        patient_name="Ada",
        session=SessionOut(
            id=sid,
            language="en",
            status="active",
            started_at=now,
            ended_at=None,
            user_agent=None,
            ip_hash=None,
            metadata={"visit": {"visit_id": "V1", "patient_name": "Ada"}},
        ),
    )
    assert filled.session is not None
    assert filled.session.id == sid
