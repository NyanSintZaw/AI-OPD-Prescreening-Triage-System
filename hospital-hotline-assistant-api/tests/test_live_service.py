import asyncio

import pytest

from app.services.ai.live_service import LiveVoiceService


class DummyTriageService:
    pass


@pytest.mark.asyncio
async def test_contact_decline_completes_assessment_and_persists_preference(monkeypatch):
    service = LiveVoiceService(triage_service=DummyTriageService())
    session_id = "test-session"
    session = {
        "queue": None,
        "transcript": ["no"],
        "agent_transcript": [],
        "muted": False,
        "activity_open": False,
        "language": "en",
        "db_connection": None,
        "db_pool": None,
        "transcript_cb": None,
        "emergency_cb": None,
        "assessment_cb": None,
        "classification": {"classified": True, "level": 1},
        "contact_preference": {},
        "contact_flow": "awaiting_consent",
        "contact_transcript_index": 0,
        "assessment_finalized": False,
        "emergency_announced": False,
        "last_emergency_severity": None,
        "audio_in_chunks": 0,
        "audio_in_bytes": 0,
        "audio_out_chunks": 0,
        "audio_out_bytes": 0,
        "first_audio_in_logged": False,
        "first_audio_out_logged": False,
    }
    service._sessions[session_id] = session

    persist_called = False
    complete_called = False

    async def fake_persist_contact_preference(session_id_arg, session_arg):
        nonlocal persist_called
        assert session_id_arg == session_id
        assert session_arg["contact_preference"]["requested"] is False
        assert session_arg["contact_preference"]["phone"] is None
        persist_called = True

    async def fake_complete_call_assessment(session_id_arg):
        nonlocal complete_called
        assert session_id_arg == session_id
        complete_called = True

    monkeypatch.setattr(service, "_persist_contact_preference", fake_persist_contact_preference)
    monkeypatch.setattr(service, "_complete_call_assessment", fake_complete_call_assessment)

    await service._handle_contact_preference_turn(session_id)
    await asyncio.sleep(0)

    assert session["contact_preference"] == {"requested": False, "phone": None}
    assert session["contact_flow"] == "done"
    assert persist_called is True
    assert complete_called is True
