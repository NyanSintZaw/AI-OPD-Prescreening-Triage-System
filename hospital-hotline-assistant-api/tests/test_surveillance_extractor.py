"""Unit tests for app.services.surveillance_extractor.

These tests mock both the asyncpg connection and the model call so they
run fast and offline — no real database or model server needed. The model
receives the engine's screening state (findings/slots), never the transcript.

What is tested:
  Guard 1 — skip if session has < 2 user messages (count only, content unread)
  Thai     — a Thai-only session is NOT skipped (the old English keyword guard did)
  Guard 3 — skip if routing rules already produced ≥ 3 keywords
  Happy path — all guards pass → Gemini is called → keywords upserted
  Merge     — AI keywords are merged with existing routing-rule keywords
  No AI    — Gemini returns empty list → no upsert
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.screening.state import Finding, ScreeningState

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_conn(
    *,
    messages: list[str],
    existing_keywords: list[str] | None = None,
    location_area: str | None = None,
) -> AsyncMock:
    """Build a mock asyncpg.Connection that returns preset fixtures."""

    conn = AsyncMock()

    # fetchval(): the user-message count, or location_area
    async def _fetchval(sql: str, *_args):
        return len(messages) if "count(*)" in sql else location_area

    conn.fetchval = AsyncMock(side_effect=_fetchval)

    # fetchrow(): existing disease_surveillance row, or the screening state
    state = ScreeningState(session_id="s", language="en")
    state.chief_complaint = "fever and sore throat for three days"
    state.findings["fever"] = Finding(state="present", value="3 days")

    async def _fetchrow(sql: str, *_args):
        if "screening_sessions" in sql:
            return {"state": state.to_json()}
        if existing_keywords is not None:
            row = MagicMock()
            row.__getitem__ = lambda self, k: existing_keywords if k == "symptom_keywords" else None
            return row
        return None   # no existing row

    conn.fetchrow = AsyncMock(side_effect=_fetchrow)

    # execute() records the upsert
    conn.execute = AsyncMock()

    return conn


# ── Guard 1: too few messages ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guard1_zero_messages_skips():
    from app.services.surveillance_extractor import _run

    conn = _make_conn(messages=[])
    with patch("app.services.surveillance_extractor._call_model_extract") as mock_ai:
        await _run(connection=conn, session_id="sess-1")
        mock_ai.assert_not_called()
        conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_guard1_one_message_skips():
    from app.services.surveillance_extractor import _run

    conn = _make_conn(messages=["I have a fever"])
    with patch("app.services.surveillance_extractor._call_model_extract") as mock_ai:
        await _run(connection=conn, session_id="sess-1")
        mock_ai.assert_not_called()


# ── Guard 3: routing rules already produced rich keywords ────────────────────

@pytest.mark.asyncio
async def test_guard3_three_existing_keywords_skips():
    from app.services.surveillance_extractor import _run

    conn = _make_conn(
        messages=["I have a sore throat and runny nose", "and a bit of fever too"],
        existing_keywords=["sore throat", "runny nose", "fever"],  # ≥ 3
    )
    with patch("app.services.surveillance_extractor._call_model_extract") as mock_ai:
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
        "app.services.surveillance_extractor._call_model_extract",
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
        "app.services.surveillance_extractor._call_model_extract",
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
        "app.services.surveillance_extractor._call_model_extract",
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
        "app.services.surveillance_extractor._call_model_extract",
        return_value=[],   # AI found nothing health-related
    ):
        await _run(connection=conn, session_id="sess-6")

    conn.execute.assert_not_called()


# ── What the model sees: the engine's state, never the transcript ─────────────

def test_model_input_is_screening_state_not_transcript():
    from app.services.surveillance_extractor import screening_summary_text

    state = ScreeningState(session_id="s", language="th")
    state.patient_name = "สมชายทดสอบนามสกุลยาว"
    state.complaint_category = "fever"
    state.chief_complaint = "ไข้มาสามวัน"
    state.findings["fever"] = Finding(state="present", value="3 วัน")
    state.findings["rash"] = Finding(state="absent")
    state.slots["duration"] = "3 วัน"
    text = screening_summary_text(state)
    assert "ไข้มาสามวัน" in text and "fever: 3 วัน" in text and "duration: 3 วัน" in text
    assert "rash" not in text                      # absent findings are not "reported"
    assert "สมชายทดสอบนามสกุลยาว" not in text      # identity never goes to the model


@pytest.mark.asyncio
async def test_no_screening_state_skips_model_call():
    from app.services.surveillance_extractor import _run

    conn = _make_conn(messages=["I have a fever", "and a sore throat too"])
    conn.fetchrow = AsyncMock(return_value=None)
    with patch("app.services.surveillance_extractor._call_model_extract") as mock_ai:
        await _run(connection=conn, session_id="sess-7")
        mock_ai.assert_not_called()


@pytest.mark.asyncio
async def test_thai_session_reaches_the_model():
    """The old guard grepped the transcript for English health words, so
    every Thai kiosk session was skipped. Findings are language-neutral."""
    from app.services.surveillance_extractor import _run

    conn = _make_conn(messages=["มีไข้ ปวดเมื่อยตัว", "สองวันแล้วค่ะ"])
    with patch("app.services.surveillance_extractor._call_model_extract", return_value=["fever"]) as mock_ai:
        await _run(connection=conn, session_id="sess-th")
        mock_ai.assert_called_once()
        assert "fever: 3 days" in mock_ai.call_args.args[0]
