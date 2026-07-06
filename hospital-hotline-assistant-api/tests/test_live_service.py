import asyncio

import pytest

import app.services.ai.live_service as live_service_module
from app.services.ai.live_events import _smart_append
from app.services.ai.live_service import LiveVoiceService
from app.services.ai.triage_models import TriageResult


class DummyTriageService:
    pass


class _FakeTranscription:
    def __init__(self, text: str):
        self.text = text


class _FakeLiveEvent:
    def __init__(self, *, input_text: str | None = None, output_text: str | None = None):
        self.content = None
        self.input_transcription = (
            _FakeTranscription(input_text) if input_text is not None else None
        )
        self.output_transcription = (
            _FakeTranscription(output_text) if output_text is not None else None
        )

    def get_function_responses(self):
        return []


def _minimal_live_session(**overrides):
    session = {
        "queue": None,
        "transcript": [],
        "agent_transcript": [],
        "conversation_events": [],
        "conversation_sequence": 0,
        "muted": False,
        "activity_open": False,
        "language": "en",
        "db_connection": None,
        "db_pool": None,
        "transcript_cb": None,
        "emergency_cb": None,
        "assessment_cb": None,
        "classification": {"classified": True, "level": 3},
        "contact_preference": {},
        "contact_flow": "done",
        "contact_transcript_index": 0,
        "contact_goodbye_queued": False,
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
    session.update(overrides)
    return session


async def _consume_live_event(service: LiveVoiceService, session_id: str, event):
    async for _ in service._handle_live_event(session_id, event):
        pass


def test_smart_append_collapses_thai_no_space_duplicate_fragment():
    chunks = ["สวัสดีค่ะ"]

    delta = _smart_append(chunks, "สวัสดีค่ะสวัสดีค่ะ")

    assert delta is None
    assert chunks == ["สวัสดีค่ะ"]


def test_smart_append_merges_thai_overlap_without_repeating_text():
    chunks = ["กรุณาบอกอาการ"]

    delta = _smart_append(chunks, "อาการของคุณ")

    assert delta == "ของคุณ"
    assert " ".join(chunks) == "กรุณาบอกอาการ ของคุณ"


@pytest.mark.asyncio
async def test_live_transcript_events_preserve_back_and_forth_order():
    service = LiveVoiceService(triage_service=DummyTriageService())
    session_id = "segmented-session"
    service._sessions[session_id] = _minimal_live_session()

    await _consume_live_event(
        service, session_id, _FakeLiveEvent(input_text="I have a headache")
    )
    await _consume_live_event(
        service, session_id, _FakeLiveEvent(output_text="Do you have vision changes?")
    )
    await _consume_live_event(
        service, session_id, _FakeLiveEvent(input_text="Yes, I cannot see clearly")
    )

    assert service._sessions[session_id]["conversation_events"] == [
        {
            "sequence": 0,
            "role": "user",
            "input_mode": "voice",
            "content": "I have a headache",
        },
        {
            "sequence": 1,
            "role": "assistant",
            "input_mode": None,
            "content": "Do you have vision changes?",
        },
        {
            "sequence": 2,
            "role": "user",
            "input_mode": "voice",
            "content": "Yes, I cannot see clearly",
        },
    ]


@pytest.mark.asyncio
async def test_live_finalization_passes_segmented_messages_to_triage_service():
    captured = {}

    class CapturingTriageService:
        async def finalize_live_assessment(self, **kwargs):
            captured.update(kwargs)
            return TriageResult(
                reply="done",
                severity_level="urgent",
                severity_explanation=None,
                severity_confidence=None,
                department_id=None,
                department_reason=None,
                department_confidence=None,
                emergency_trigger_id=None,
                emergency_alert_message=None,
                detected_symptoms=[],
                follow_up_question=None,
                follow_up_reason=None,
                model_name=None,
                latency_ms=0,
                alert_sent=False,
                raw_text="",
                pain_score=None,
                pain_location=None,
                distress_score=None,
                distress_type=None,
                red_flags=[],
                contact={},
            ), {}

    service = LiveVoiceService(triage_service=CapturingTriageService())
    session_id = "finalize-segmented-session"
    service._sessions[session_id] = _minimal_live_session(
        transcript=["I have a headache"],
        agent_transcript=["Please go to emergency."],
        conversation_events=[
            {
                "sequence": 0,
                "role": "user",
                "input_mode": "voice",
                "content": "I have a headache",
            },
            {
                "sequence": 1,
                "role": "assistant",
                "input_mode": None,
                "content": "Please go to emergency.",
            },
        ],
        classification={"classified": True, "level": 2},
    )

    await service._complete_call_assessment(session_id)

    assert captured["content"] == "I have a headache"
    assert captured["reply"] == "Please go to emergency."
    assert (
        captured["live_messages"]
        == service._sessions[session_id]["conversation_events"]
    )


@pytest.mark.asyncio
async def test_contact_yes_without_phone_forces_phone_followup(monkeypatch):
    service = LiveVoiceService(triage_service=DummyTriageService())
    session_id = "test-session"
    session = {
        "queue": None,
        "transcript": ["yes please"],
        "agent_transcript": [],
        "muted": False,
        "activity_open": False,
        "language": "en",
        "db_connection": None,
        "db_pool": None,
        "transcript_cb": None,
        "emergency_cb": None,
        "assessment_cb": None,
        "classification": {"classified": True, "level": 3},
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

    spoken_prompt = None

    async def fake_complete_call_assessment(session_id_arg):
        raise AssertionError("should not finalize before phone number is known")

    def fake_send_agent_instruction(session_arg, text):
        nonlocal spoken_prompt
        assert session_arg is session
        spoken_prompt = text

    monkeypatch.setattr(service, "_complete_call_assessment", fake_complete_call_assessment)
    monkeypatch.setattr(service, "_send_agent_instruction", fake_send_agent_instruction)

    await service._handle_contact_preference_turn(session_id)
    for _ in range(3):
        await asyncio.sleep(0)

    assert session["contact_flow"] == "awaiting_phone"
    assert session["contact_preference"]["requested"] is True
    assert session["contact_preference"]["phone"] is None
    assert session["contact_preference"]["needs_followup"] is True
    assert session.get("contact_completion_started") is None
    assert spoken_prompt is not None
    assert "phone number" in spoken_prompt
    assert "Goodbye" not in spoken_prompt


@pytest.mark.asyncio
async def test_contact_yes_uses_local_parse_before_assessment(monkeypatch):
    service = LiveVoiceService(triage_service=DummyTriageService())
    session_id = "test-session"
    session = {
        "queue": None,
        "transcript": ["yes"],
        "agent_transcript": [],
        "muted": False,
        "activity_open": False,
        "language": "en",
        "db_connection": None,
        "db_pool": None,
        "transcript_cb": None,
        "emergency_cb": None,
        "assessment_cb": None,
        "classification": {"classified": True, "level": 3},
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

    spoken_prompt = None

    async def fake_complete_call_assessment(session_id_arg):
        raise AssertionError("should not finalize before phone number is known")

    def fake_send_agent_instruction(session_arg, text):
        nonlocal spoken_prompt
        spoken_prompt = text

    monkeypatch.setattr(service, "_complete_call_assessment", fake_complete_call_assessment)
    monkeypatch.setattr(service, "_send_agent_instruction", fake_send_agent_instruction)

    await service._handle_contact_preference_turn(session_id)
    for _ in range(3):
        await asyncio.sleep(0)

    assert session["contact_flow"] == "awaiting_phone"
    assert session["contact_preference"]["requested"] is True
    assert session["contact_preference"]["phone"] is None
    assert session.get("contact_completion_started") is None
    assert spoken_prompt is not None
    assert "phone number" in spoken_prompt


@pytest.mark.asyncio
async def test_contact_turn_waits_for_delayed_transcript(monkeypatch):
    service = LiveVoiceService(triage_service=DummyTriageService())
    session_id = "test-session"
    session = {
        "queue": None,
        "transcript": ["cough"],
        "agent_transcript": [],
        "muted": False,
        "activity_open": False,
        "language": "en",
        "db_connection": None,
        "db_pool": None,
        "transcript_cb": None,
        "emergency_cb": None,
        "assessment_cb": None,
        "classification": {"classified": True, "level": 3},
        "contact_preference": {},
        "contact_flow": "awaiting_consent",
        "contact_transcript_index": 1,
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

    spoken_prompt = None

    def fake_send_agent_instruction(session_arg, text):
        nonlocal spoken_prompt
        spoken_prompt = text

    monkeypatch.setattr(live_service_module, "_CONTACT_REPLY_WAIT_SECONDS", 1)
    monkeypatch.setattr(live_service_module, "_CONTACT_REPLY_POLL_SECONDS", 0.01)
    monkeypatch.setattr(service, "_send_agent_instruction", fake_send_agent_instruction)

    task = asyncio.create_task(service._handle_contact_preference_turn(session_id))
    await asyncio.sleep(0.45)
    session["transcript"].append("yes please")
    await task

    assert session["contact_flow"] == "awaiting_phone"
    assert spoken_prompt is not None
    assert "phone number" in spoken_prompt


@pytest.mark.asyncio
async def test_contact_thai_yes_without_phone_forces_phone_followup(monkeypatch):
    service = LiveVoiceService(triage_service=DummyTriageService())
    session_id = "test-session"
    session = {
        "queue": None,
        "transcript": ["ได้ค่ะ"],
        "agent_transcript": [],
        "muted": False,
        "activity_open": False,
        "language": "th",
        "db_connection": None,
        "db_pool": None,
        "transcript_cb": None,
        "emergency_cb": None,
        "assessment_cb": None,
        "classification": {"classified": True, "level": 3},
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

    spoken_prompt = None

    def fake_send_agent_instruction(session_arg, text):
        nonlocal spoken_prompt
        spoken_prompt = text

    monkeypatch.setattr(service, "_send_agent_instruction", fake_send_agent_instruction)

    await service._handle_contact_preference_turn(session_id)

    assert session["contact_flow"] == "awaiting_phone"
    assert session["contact_preference"]["requested"] is True
    assert session["contact_preference"]["phone"] is None
    assert spoken_prompt is not None
    assert "หมายเลขโทรศัพท์" in spoken_prompt


@pytest.mark.asyncio
async def test_contact_thai_yes_with_phone_completes_from_live_transcript(monkeypatch):
    service = LiveVoiceService(triage_service=DummyTriageService())
    session_id = "test-session"
    session = {
        "queue": None,
        "transcript": ["ต้องการค่ะ เบอร์ 0812345678"],
        "agent_transcript": [],
        "muted": False,
        "activity_open": False,
        "language": "th",
        "db_connection": None,
        "db_pool": None,
        "transcript_cb": None,
        "emergency_cb": None,
        "assessment_cb": None,
        "classification": {"classified": True, "level": 3},
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
        assert session_arg["contact_preference"]["requested"] is True
        assert session_arg["contact_preference"]["phone"] == "0812345678"
        persist_called = True

    async def fake_complete_call_assessment(session_id_arg):
        nonlocal complete_called
        complete_called = True

    monkeypatch.setattr(live_service_module, "_CONTACT_GOODBYE_DELAY_SECONDS", 0)
    monkeypatch.setattr(service, "_persist_contact_preference", fake_persist_contact_preference)
    monkeypatch.setattr(service, "_complete_call_assessment", fake_complete_call_assessment)
    monkeypatch.setattr(service, "_send_agent_instruction", lambda *args: None)

    await service._handle_contact_preference_turn(session_id)
    for _ in range(3):
        await asyncio.sleep(0)

    assert session["contact_flow"] == "done"
    assert persist_called is True
    assert complete_called is True


@pytest.mark.asyncio
async def test_contact_thai_decline_does_not_match_yes_inside_no(monkeypatch):
    service = LiveVoiceService(triage_service=DummyTriageService())
    session_id = "test-session"
    session = {
        "queue": None,
        "transcript": ["ไม่ใช่ค่ะ ไม่ต้อง"],
        "agent_transcript": [],
        "muted": False,
        "activity_open": False,
        "language": "th",
        "db_connection": None,
        "db_pool": None,
        "transcript_cb": None,
        "emergency_cb": None,
        "assessment_cb": None,
        "classification": {"classified": True, "level": 3},
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
        assert session_arg["contact_preference"]["requested"] is False
        assert session_arg["contact_preference"]["phone"] is None
        persist_called = True

    async def fake_complete_call_assessment(session_id_arg):
        nonlocal complete_called
        complete_called = True

    monkeypatch.setattr(live_service_module, "_CONTACT_GOODBYE_DELAY_SECONDS", 0)
    monkeypatch.setattr(service, "_persist_contact_preference", fake_persist_contact_preference)
    monkeypatch.setattr(service, "_complete_call_assessment", fake_complete_call_assessment)
    monkeypatch.setattr(service, "_send_agent_instruction", lambda *args: None)

    await service._handle_contact_preference_turn(session_id)
    for _ in range(3):
        await asyncio.sleep(0)

    assert session["contact_flow"] == "done"
    assert persist_called is True
    assert complete_called is True


@pytest.mark.asyncio
async def test_contact_phone_turn_completes_from_live_transcript(monkeypatch):
    service = LiveVoiceService(triage_service=DummyTriageService())
    session_id = "test-session"
    session = {
        "queue": None,
        "transcript": ["yes please", "0985579960"],
        "agent_transcript": [],
        "muted": False,
        "activity_open": False,
        "language": "en",
        "db_connection": None,
        "db_pool": None,
        "transcript_cb": None,
        "emergency_cb": None,
        "assessment_cb": None,
        "classification": {"classified": True, "level": 3},
        "contact_preference": {},
        "contact_flow": "awaiting_phone",
        "contact_transcript_index": 1,
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
        assert session_arg["contact_preference"]["requested"] is True
        assert session_arg["contact_preference"]["phone"] == "0985579960"
        persist_called = True

    async def fake_complete_call_assessment(session_id_arg):
        nonlocal complete_called
        complete_called = True

    monkeypatch.setattr(live_service_module, "_CONTACT_GOODBYE_DELAY_SECONDS", 0)
    monkeypatch.setattr(service, "_persist_contact_preference", fake_persist_contact_preference)
    monkeypatch.setattr(service, "_complete_call_assessment", fake_complete_call_assessment)
    monkeypatch.setattr(service, "_send_agent_instruction", lambda *args: None)

    await service._handle_contact_preference_turn(session_id)
    for _ in range(3):
        await asyncio.sleep(0)

    assert session["contact_flow"] == "done"
    assert session["contact_completion_started"] is True
    assert persist_called is True
    assert complete_called is True


@pytest.mark.asyncio
async def test_contact_decline_says_goodbye_then_completes_assessment(monkeypatch):
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
    goodbye_prompt = None

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

    def fake_send_agent_instruction(session_arg, text):
        nonlocal goodbye_prompt
        assert session_arg is session
        goodbye_prompt = text

    monkeypatch.setattr(live_service_module, "_CONTACT_GOODBYE_DELAY_SECONDS", 0)
    monkeypatch.setattr(service, "_persist_contact_preference", fake_persist_contact_preference)
    monkeypatch.setattr(service, "_complete_call_assessment", fake_complete_call_assessment)
    monkeypatch.setattr(service, "_send_agent_instruction", fake_send_agent_instruction)

    await service._handle_contact_preference_turn(session_id)
    for _ in range(3):
        await asyncio.sleep(0)

    assert session["contact_preference"]["requested"] is False
    assert session["contact_preference"]["phone"] is None
    assert session["contact_preference"]["confidence"] == 1.0
    assert session["contact_flow"] == "done"
    assert session["contact_completion_started"] is True
    assert "patient ID" in goodbye_prompt
    assert persist_called is True
    assert complete_called is True


@pytest.mark.asyncio
async def test_contact_tool_finalization_does_not_queue_duplicate_goodbye(monkeypatch):
    service = LiveVoiceService(triage_service=DummyTriageService())
    session_id = "tool-contact-session"
    session = _minimal_live_session(
        contact_flow="awaiting_consent",
        contact_preference={},
    )
    service._sessions[session_id] = session

    persist_called = False
    complete_called = False
    queued_prompts = []

    async def fake_persist_contact_preference(session_id_arg, session_arg):
        nonlocal persist_called
        assert session_id_arg == session_id
        assert session_arg["contact_preference"]["requested"] is False
        persist_called = True

    async def fake_complete_call_assessment(session_id_arg):
        nonlocal complete_called
        assert session_id_arg == session_id
        complete_called = True

    def fake_send_agent_instruction(session_arg, text):
        queued_prompts.append(text)

    monkeypatch.setattr(live_service_module, "_CONTACT_GOODBYE_DELAY_SECONDS", 0)
    monkeypatch.setattr(service, "_persist_contact_preference", fake_persist_contact_preference)
    monkeypatch.setattr(service, "_complete_call_assessment", fake_complete_call_assessment)
    monkeypatch.setattr(service, "_send_agent_instruction", fake_send_agent_instruction)

    await service._handle_tool_response(
        session_id,
        {
            "contact_preference_recorded": True,
            "requested": False,
            "needs_followup": False,
        },
        None,
    )
    for _ in range(3):
        await asyncio.sleep(0)

    assert session["contact_flow"] == "done"
    assert session["contact_completion_started"] is True
    assert persist_called is True
    assert complete_called is True
    assert queued_prompts == []


@pytest.mark.asyncio
async def test_assessment_completion_defers_while_contact_is_pending():
    class FailingTriageService:
        async def finalize_live_assessment(self, **kwargs):
            raise AssertionError("should not finalize before contact flow is done")

    service = LiveVoiceService(triage_service=FailingTriageService())
    session_id = "pending-contact-session"
    service._sessions[session_id] = {
        "classification": {"classified": True, "level": 3},
        "assessment_finalized": False,
        "contact_flow": "awaiting_consent",
        "transcript": ["cough"],
        "agent_transcript": ["Would you like the hospital to contact you?"],
    }

    await service._complete_call_assessment(session_id)

    assert service._sessions[session_id]["assessment_finalized"] is False
