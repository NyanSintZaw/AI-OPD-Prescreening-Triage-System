"""Integration test: full end-to-end surveillance capture.

Requires the backend to be running on http://localhost:8000 and a live
PostgreSQL database. Run with:

    uv run pytest tests/test_surveillance_integration.py -v -s

What this test verifies:
  1. Create a session via POST /sessions
  2. Send 3 realistic chat messages (simulating a COVID conversation)
  3. End the session via PATCH /sessions/{id}  { status: completed }
  4. Wait briefly for the background extraction task to finish
  5. Query the disease_surveillance table directly and assert keywords exist
  6. Confirm the admin surveillance API (GET /admin/surveillance) also reflects
     the data — this is what the frontend dashboard reads.

The test is marked 'integration' so it can be skipped in fast/offline CI:
    uv run pytest -m "not integration"
"""

from __future__ import annotations

import asyncio
import time

import asyncpg
import httpx
import pytest

BASE_URL = "http://localhost:8000"
DB_URL = "postgresql://postgres:postgres@localhost:5432/hospital_hotline"

# Admin credentials (seeded by migration 003)
ADMIN_EMAIL = "ops.admin@mfu.local"
ADMIN_PASSWORD = "admin1234"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def http():
    """Synchronous httpx client for the whole module."""
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        yield client


@pytest.fixture(scope="module")
def admin_token(http):
    resp = http.post("/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, f"Admin login failed: {resp.text}"
    return resp.json()["access_token"]


# ── helpers ───────────────────────────────────────────────────────────────────

async def _fetch_surveillance_row(session_id: str) -> dict | None:
    conn = await asyncpg.connect(DB_URL)
    try:
        row = await conn.fetchrow(
            "SELECT symptom_keywords, symptoms_summary, severity_level, location_area "
            "FROM disease_surveillance WHERE session_id = $1",
            session_id,
        )
        return dict(row) if row else None
    finally:
        await conn.close()


def _wait_for_surveillance(session_id: str, timeout: float = 15.0) -> dict | None:
    """Poll the DB until a surveillance row appears or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = asyncio.run(_fetch_surveillance_row(session_id))
        if row and row.get("symptom_keywords"):
            return row
        time.sleep(1)
    return None


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_surveillance_captured_after_session_end(http):
    """Full flow: chat about COVID → end session → keywords in DB + API."""

    # 1. Create session
    resp = http.post("/sessions", json={"language": "en"})
    assert resp.status_code == 201
    session_id = resp.json()["id"]

    # 2. Send 3 messages that mention diseases (bypasses Guard 1 & 2)
    chat_messages = [
        "Hi, I need help.",
        "I tested positive on a COVID rapid test this morning.",
        "I also have a high fever around 38.5 degrees and I completely lost my sense of smell.",
    ]
    for msg in chat_messages:
        resp = http.post(
            f"/sessions/{session_id}/chat/stream",
            content=msg.encode(),
            headers={"Content-Type": "text/plain"},
        )
        # Streaming endpoint — just drain it, we don't inspect the AI reply here
        _ = resp.read()

    # 3. End the session (triggers background extraction)
    resp = http.patch(f"/sessions/{session_id}", json={"status": "completed"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # 4. Wait for background Gemini task (up to 15 s)
    row = _wait_for_surveillance(session_id)

    # 5. Assert keywords were captured in disease_surveillance
    assert row is not None, (
        f"disease_surveillance row not found for session {session_id} after 15 s. "
        "Check backend logs for surveillance_extractor errors."
    )
    keywords: list[str] = row["symptom_keywords"]
    assert len(keywords) >= 1, f"Expected ≥1 keyword, got: {keywords}"

    # At least one COVID/fever/smell keyword should appear
    health_terms = {"covid", "fever", "loss of smell", "anosmia", "smell"}
    assert any(
        any(term in kw.lower() for term in health_terms) for kw in keywords
    ), f"Expected a health keyword in {keywords}"

    print(f"\n[PASS] session={session_id[:8]}... keywords={keywords}")


@pytest.mark.integration
def test_surveillance_api_returns_data(http, admin_token):
    """GET /admin/surveillance should reflect the data we just saved."""

    resp = http.get(
        "/admin/surveillance?days=1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert "top_symptoms" in body
    assert "daily_trend" in body
    assert "total_reports" in body
    assert body["total_reports"] >= 1, "Expected at least 1 surveillance report"

    print(f"\n[PASS] Surveillance API: total_reports={body['total_reports']}")
    print(f"       top_symptoms={body['top_symptoms'][:3]}")


@pytest.mark.integration
def test_guard1_short_session_not_captured(http):
    """Session with only 1 user message should NOT create a surveillance row."""

    resp = http.post("/sessions", json={"language": "en"})
    session_id = resp.json()["id"]

    # Only send 1 message — Guard 1 should block Gemini
    resp = http.post(
        f"/sessions/{session_id}/messages",
        json={"role": "user", "content": "hi"},
    )
    assert resp.status_code == 201

    resp = http.patch(f"/sessions/{session_id}", json={"status": "completed"})
    assert resp.status_code == 200

    # Wait a moment and confirm NO surveillance row was created
    time.sleep(3)
    row = asyncio.run(_fetch_surveillance_row(session_id))
    assert row is None or not row.get("symptom_keywords"), (
        f"Guard 1 failed — row was created for a greeting-only session: {row}"
    )
    print(f"\n[PASS] Guard 1: greeting-only session correctly skipped.")


@pytest.mark.integration
def test_guard3_rich_routing_keywords_not_recalled(http):
    """Session already having ≥3 routing-rule keywords should skip Gemini."""
    import time as _time

    resp = http.post("/sessions", json={"language": "en"})
    session_id = resp.json()["id"]

    # Insert a surveillance row directly with 3 keywords (simulates routing rules)
    async def _seed():
        conn = await asyncpg.connect(DB_URL)
        try:
            await conn.execute(
                "INSERT INTO disease_surveillance (session_id, symptom_keywords) VALUES ($1, $2) "
                "ON CONFLICT (session_id) DO UPDATE SET symptom_keywords = EXCLUDED.symptom_keywords",
                session_id,
                ["ear pain", "hearing problem", "runny nose"],
            )
        finally:
            await conn.close()

    asyncio.run(_seed())

    resp = http.patch(f"/sessions/{session_id}", json={"status": "completed"})
    assert resp.status_code == 200

    _time.sleep(3)

    # Keywords should still be the original 3 from routing rules (unchanged)
    row = asyncio.run(_fetch_surveillance_row(session_id))
    assert row is not None
    assert set(row["symptom_keywords"]) == {"ear pain", "hearing problem", "runny nose"}, (
        f"Guard 3 failed — keywords were changed: {row['symptom_keywords']}"
    )
    print(f"\n[PASS] Guard 3: rich routing-rule data correctly not overwritten.")
