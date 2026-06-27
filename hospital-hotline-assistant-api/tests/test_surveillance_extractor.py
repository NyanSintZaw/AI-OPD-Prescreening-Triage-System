"""Unit tests for app.services.surveillance_extractor.

These tests mock both the asyncpg connection and the Gemini API call so
they run fast and offline — no real database or Google credentials needed.

What is tested:
  Guard 1 — skip if session has < 2 user messages
  Guard 2 — skip if all messages are greetings / too short
  Guard 3 — skip if routing rules already produced ≥ 3 keywords
  Happy path — all guards pass → Gemini is called → keywords upserted
  Merge     — AI keywords are merged with existing routing-rule keywords
  No AI    — Gemini returns empty list → no upsert
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_conn(
    *,
    messages: list[str],
    existing_keywords: list[str] | None = None,
    location_area: str | None = None,
) -> AsyncMock:
    """Build a mock asyncpg.Connection that returns preset fixtures."""

    conn = AsyncMock()

    # fetch() for user messages  →  list of record-like dicts
    conn.fetch.return_value = [{"content": m} for m in messages]

    # fetchrow() for existing disease_surveillance row
    if existing_keywords is not None:
        row = MagicMock()
        row.__getitem__ = lambda self, k: existing_keywords if k == "symptom_keywords" else None
        conn.fetchrow.return_value = row
    else:
        conn.fetchrow.return_value = None   # no existing row

    # fetchval() for location_area
    conn.fetchval.return_value = location_area

    # execute() records the upsert
    conn.execute = AsyncMock()

    return conn


# ── Guard 1: too few messages ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guard1_zero_messages_skips():
    from app.services.surveillance_extractor import _run

    conn = _make_conn(messages=[])
    with patch("app.services.surveillance_extractor._call_gemini_extract") as mock_ai:
        await _run(connection=conn, session_id="sess-1")
        mock_ai.assert_not_called()
        conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_guard1_one_message_skips():
    from app.services.surveillance_extractor import _run

    conn = _make_conn(messages=["I have a fever"])
    with patch("app.services.surveillance_extractor._call_gemini_extract") as mock_ai:
        await _run(connection=conn, session_id="sess-1")
        mock_ai.assert_not_called()


# ── Guard 2: only greetings / too short ──────────────────────────────────────

@pytest.mark.asyncio
async def test_guard2_only_greetings_skips():
    from app.services.surveillance_extractor import _run

    conn = _make_conn(messages=["hi", "hello"])
    with patch("app.services.surveillance_extractor._call_gemini_extract") as mock_ai:
        await _run(connection=conn, session_id="sess-2")
        mock_ai.assert_not_called()


@pytest.mark.asyncio
async def test_guard2_short_messages_skips():
    from app.services.surveillance_extractor import _run

    # Both messages ≤ 10 chars
    conn = _make_conn(messages=["ok", "yes"])
    with patch("app.services.surveillance_extractor._call_gemini_extract") as mock_ai:
        await _run(connection=conn, session_id="sess-2")
        mock_ai.assert_not_called()


# ── Guard 2b: no health signal words ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_guard2b_doctor_only_query_skips():
    """Pure doctor/schedule query with no health words → Gemini not called."""
    from app.services.surveillance_extractor import _run

    conn = _make_conn(messages=[
        "Is Dr. Smith available today?",
        "What time does the ENT specialist work this week?",
    ])
    with patch("app.services.surveillance_extractor._call_gemini_extract") as mock_ai:
        await _run(connection=conn, session_id="sess-2b-1")
        mock_ai.assert_not_called()
        conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_guard2b_health_word_in_doctor_query_passes():
    """Doctor query that also mentions a symptom should pass Guard 2b."""
    from app.services.surveillance_extractor import _run

    conn = _make_conn(messages=[
        "I have a fever — is there a doctor available now?",
        "My temperature is 39 degrees, can I see someone today?",
    ])
    with patch(
        "app.services.surveillance_extractor._call_gemini_extract",
        return_value=["fever"],
    ) as mock_ai:
        await _run(connection=conn, session_id="sess-2b-2")
        mock_ai.assert_called_once()


# ── Guard 3: routing rules already produced rich keywords ────────────────────

@pytest.mark.asyncio
async def test_guard3_three_existing_keywords_skips():
    from app.services.surveillance_extractor import _run

    conn = _make_conn(
        messages=["I have a sore throat and runny nose", "and a bit of fever too"],
        existing_keywords=["sore throat", "runny nose", "fever"],  # ≥ 3
    )
    with patch("app.services.surveillance_extractor._call_gemini_extract") as mock_ai:
        await _run(connection=conn, session_id="sess-3")
        mock_ai.assert_not_called()
        conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_guard3_two_existing_keywords_does_not_skip():
    """2 keywords < threshold → should still call Gemini."""
    from app.services.surveillance_extractor import _run

    conn = _make_conn(
        messages=["I have a sore throat and bad headache", "and some fever"],
        existing_keywords=["sore throat", "headache"],  # < 3
    )
    with patch(
        "app.services.surveillance_extractor._call_gemini_extract",
        return_value=["sore throat", "headache", "fever"],
    ) as mock_ai:
        await _run(connection=conn, session_id="sess-3")
        mock_ai.assert_called_once()


# ── Happy path: all guards pass ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_saves_keywords():
    from app.services.surveillance_extractor import _run

    conn = _make_conn(
        messages=[
            "hi",
            "I tested positive for COVID",
            "I also have a fever and I lost my sense of smell",
        ],
        existing_keywords=None,
        location_area="Mueang Chiang Rai",
    )

    extracted = ["covid", "fever", "loss of smell"]
    with patch(
        "app.services.surveillance_extractor._call_gemini_extract",
        return_value=extracted,
    ):
        await _run(connection=conn, session_id="sess-4")

    # execute() must have been called with the upsert SQL
    # call signature: execute(sql, session_id, keywords, summary, location)
    #   args[0] = SQL, args[1] = session_id, args[2] = keywords, args[3] = summary, args[4] = location
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args
    saved_keywords = call_args.args[2]          # $2 = symptom_keywords
    saved_location = call_args.args[4]          # $4 = location_area
    assert set(saved_keywords) == set(extracted)
    assert saved_location == "Mueang Chiang Rai"


# ── Merge: combine AI keywords with existing routing-rule keywords ────────────

@pytest.mark.asyncio
async def test_merges_ai_with_existing_routing_keywords():
    from app.services.surveillance_extractor import _run

    conn = _make_conn(
        messages=[
            "I have COVID and also a very bad sore throat",
            "Fever for three days now",
        ],
        existing_keywords=["sore throat"],   # 1 keyword from routing rule
    )

    with patch(
        "app.services.surveillance_extractor._call_gemini_extract",
        return_value=["covid", "fever", "sore throat"],  # AI also found sore throat
    ):
        await _run(connection=conn, session_id="sess-5")

    call_args = conn.execute.call_args
    saved_keywords: list[str] = call_args.args[2]   # args[0]=sql, [1]=session_id, [2]=keywords

    # Merged, deduplicated
    assert "covid" in saved_keywords
    assert "fever" in saved_keywords
    assert "sore throat" in saved_keywords
    assert saved_keywords.count("sore throat") == 1  # no duplicates


# ── No AI output: Gemini returns empty → nothing saved ───────────────────────

@pytest.mark.asyncio
async def test_empty_ai_result_does_not_upsert():
    from app.services.surveillance_extractor import _run

    conn = _make_conn(
        messages=["hi there", "Can I speak to a doctor please?"],
        existing_keywords=None,
    )

    with patch(
        "app.services.surveillance_extractor._call_gemini_extract",
        return_value=[],   # AI found nothing health-related
    ):
        await _run(connection=conn, session_id="sess-6")

    conn.execute.assert_not_called()
