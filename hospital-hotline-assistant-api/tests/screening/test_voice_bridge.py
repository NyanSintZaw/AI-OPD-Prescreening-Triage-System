"""Turn-based voice bridge tests — fake STT/TTS/triage, no Google calls."""

from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace

import pytest

from app.services.google_tts import strip_wav_header
from app.services.screening import templates
from app.services.screening.voice_bridge import (
    SILENCE_HANG_MS,
    TurnVoiceService,
    mean_abs_amplitude,
    pcm16_to_wav,
)

SESSION_ID = "11111111-1111-1111-1111-111111111111"

LOUD_CHUNK = b"\x00\x40" * 640    # 40 ms @16 kHz of amplitude 16384
SILENT_CHUNK = b"\x00\x00" * 640  # 40 ms of digital silence


# ── fakes ─────────────────────────────────────────────────────────────────────

class FakeConn:
    async def fetchrow(self, query, *args):
        return {"id": args[0]}


class FakeStt:
    def __init__(self) -> None:
        self.transcripts: deque[str | Exception] = deque()
        self.calls: list[dict] = []

    async def transcribe(self, **kwargs):
        self.calls.append(kwargs)
        result = self.transcripts.popleft() if self.transcripts else ""
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(transcript=result, confidence=0.9, language_code="en-US")


class FakeTts:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def synthesize(self, **kwargs):
        self.calls.append(kwargs)
        return b"\x01\x02" * 100  # 200 bytes of fake PCM


class FakeTriageService:
    """Scripted process_chat_stream: one list of events per turn."""

    def __init__(self) -> None:
        self.turns: deque[list[dict]] = deque()
        self.contents: list[str] = []

    async def process_chat_stream(self, *, connection, session_id, language, input_mode, content):
        assert input_mode == "voice"
        self.contents.append(content)
        events = self.turns.popleft() if self.turns else []
        for event in events:
            yield event


def interview_turn(reply: str = "How long has this been going on?") -> list[dict]:
    return [
        {"type": "user_message", "message": {}},
        {
            "type": "complete",
            "result": {"reply": reply, "assessment_status": "in_progress"},
            "assistant_message": {"content": reply},
        },
    ]


def final_turn(reply: str = "Please proceed to the Emergency Department.") -> list[dict]:
    return [
        {
            "type": "complete",
            "result": {
                "reply": reply,
                "assessment_status": "complete",
                "severity": {"level": "unknown"},
            },
            "assistant_message": {"content": reply},
        },
    ]


class Harness:
    def __init__(self) -> None:
        self.stt = FakeStt()
        self.tts = FakeTts()
        self.triage = FakeTriageService()
        self.service = TurnVoiceService(
            triage_service=self.triage,  # duck-typed
            stt_client=self.stt,
            tts_client=self.tts,
        )
        self.transcripts: list[tuple[str, str]] = []
        self.emergencies: list[dict] = []
        self.assessments: list[dict] = []
        self.chunks: list[bytes] = []
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        async def on_transcript(role: str, text: str) -> None:
            self.transcripts.append((role, text))

        async def on_emergency(payload: dict) -> None:
            self.emergencies.append(payload)

        async def on_assessment(payload: dict) -> None:
            self.assessments.append(payload)

        await self.service.connect(
            SESSION_ID,
            "en",
            FakeConn(),
            transcript_callback=on_transcript,
            emergency_callback=on_emergency,
            assessment_callback=on_assessment,
        )

        async def consume() -> None:
            async for chunk in self.service.run_live_pipeline(SESSION_ID):
                self.chunks.append(chunk)

        self._task = asyncio.create_task(consume())

    async def wait_until(self, predicate, timeout: float = 2.0) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while not predicate():
            if asyncio.get_event_loop().time() > deadline:
                raise AssertionError("condition not reached in time")
            await asyncio.sleep(0.01)

    async def speak_turn(self, n_loud_chunks: int = 10) -> None:
        """Feed audio and end the turn explicitly (Send button path).

        Mirrors the real client: waits for the previous turn to finish and
        unmutes (the browser auto-unmutes once agent playback drains) before
        streaming fresh microphone audio.
        """
        await self.wait_until(
            lambda: not self.service._sessions[SESSION_ID]["processing"]
        )
        self.service.set_mute(SESSION_ID, False)
        for _ in range(n_loud_chunks):
            await self.service.send_audio(SESSION_ID, LOUD_CHUNK)
        self.service.end_user_turn(SESSION_ID)

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.service.disconnect(SESSION_ID)


@pytest.fixture()
async def harness():
    h = Harness()
    await h.start()
    yield h
    await h.stop()


# ── pure helpers ──────────────────────────────────────────────────────────────

def test_pcm16_to_wav_header():
    pcm = b"\x01\x02" * 8
    wav = pcm16_to_wav(pcm, 16_000)
    assert wav.startswith(b"RIFF")
    assert b"WAVE" in wav and b"data" in wav
    assert wav.endswith(pcm)


def test_strip_wav_header_round_trip():
    pcm = b"\x0a\x0b" * 32
    assert strip_wav_header(pcm16_to_wav(pcm, 24_000)) == pcm


def test_strip_wav_header_passthrough_for_raw():
    assert strip_wav_header(b"\x01\x02\x03\x04") == b"\x01\x02\x03\x04"


def test_mean_abs_amplitude():
    assert mean_abs_amplitude(SILENT_CHUNK) == 0.0
    assert mean_abs_amplitude(LOUD_CHUNK) > 10_000
    assert mean_abs_amplitude(b"") == 0.0


# ── turn flow ─────────────────────────────────────────────────────────────────

async def test_greeting_spoken_first(harness):
    await harness.wait_until(lambda: harness.chunks)
    assert harness.transcripts[0] == ("agent", templates.VOICE_GREETING["en"])
    # LINEAR16 at 24 kHz requested from TTS
    assert harness.tts.calls[0]["audio_encoding"] == "linear16"
    assert harness.tts.calls[0]["sample_rate_hertz"] == 24_000


async def test_explicit_end_of_turn_runs_pipeline(harness):
    harness.stt.transcripts.append("I have a cough")
    harness.triage.turns.append(interview_turn("How long?"))
    await harness.wait_until(lambda: harness.chunks)  # greeting done

    await harness.speak_turn()
    await harness.wait_until(lambda: ("agent", "How long?") in harness.transcripts)

    assert ("user", "I have a cough") in harness.transcripts
    assert harness.triage.contents == ["I have a cough"]
    # STT received WAV-wrapped PCM
    assert harness.stt.calls[0]["mime_type"] == "audio/wav"
    assert harness.stt.calls[0]["audio_bytes"].startswith(b"RIFF")
    # explicit turn end mutes the server-side gate (client mirrors it)
    assert harness.service._sessions[SESSION_ID]["muted"] is True


async def test_silence_fallback_ends_turn(harness):
    harness.stt.transcripts.append("chest pain")
    harness.triage.turns.append(interview_turn("Since when?"))
    await harness.wait_until(lambda: harness.chunks)

    await harness.service.send_audio(SESSION_ID, LOUD_CHUNK)
    n_silence = int(SILENCE_HANG_MS / 40) + 1
    for _ in range(n_silence):
        await harness.service.send_audio(SESSION_ID, SILENT_CHUNK)

    await harness.wait_until(lambda: ("user", "chest pain") in harness.transcripts)
    # silence fallback must NOT mute — the client never muted itself
    assert harness.service._sessions[SESSION_ID]["muted"] is False


async def test_short_buffer_ignored(harness):
    await harness.wait_until(lambda: harness.chunks)
    await harness.service.send_audio(SESSION_ID, LOUD_CHUNK)  # 40 ms < minimum
    harness.service.end_user_turn(SESSION_ID)
    await asyncio.sleep(0.05)
    assert harness.stt.calls == []
    assert all(role == "agent" for role, _ in harness.transcripts)


async def test_muted_audio_dropped(harness):
    await harness.wait_until(lambda: harness.chunks)
    harness.service.set_mute(SESSION_ID, True)
    await harness.service.send_audio(SESSION_ID, LOUD_CHUNK)
    assert len(harness.service._sessions[SESSION_ID]["buffer"]) == 0
    harness.service.set_mute(SESSION_ID, False)
    await harness.service.send_audio(SESSION_ID, LOUD_CHUNK)
    assert len(harness.service._sessions[SESSION_ID]["buffer"]) == len(LOUD_CHUNK)


async def test_emergency_callback_on_level_1(harness):
    harness.stt.transcripts.append("crushing chest pain and sweating")
    harness.triage.turns.append([
        {
            "type": "classified",
            "classification": {
                "classified": True,
                "level": 1,
                "color": "red",
                "label": "Resuscitation",
                "key_reason": "Suspected MI",
                "department_code": "emergency",
                "symptoms_summary": "chest pain; sweating",
            },
        },
        {
            "type": "turn_complete",
            "assistant_message": {"content": "Please go to the ER now."},
            "awaiting_contact": True,
        },
    ])
    await harness.wait_until(lambda: harness.chunks)

    await harness.speak_turn()
    await harness.wait_until(lambda: harness.emergencies)

    banner = harness.emergencies[0]
    assert banner["severity"] == "emergency"
    assert banner["level"] == 1
    assert banner["department_code"] == "emergency"
    assert banner["detected_symptoms"] == ["chest pain; sweating"]
    assert ("agent", "Please go to the ER now.") in harness.transcripts
    # still mid contact flow — call stays open
    assert harness.service.should_keep_pipeline_open(SESSION_ID)


async def test_complete_assessment_auto_ends(harness):
    harness.stt.transcripts.append("no thanks")
    harness.triage.turns.append(final_turn("Take care."))
    await harness.wait_until(lambda: harness.chunks)

    await harness.speak_turn()
    await harness.wait_until(lambda: harness.assessments)

    payload = harness.assessments[0]
    assert payload["auto_end"] is True
    assert payload["assessment_status"] == "complete"
    assert ("agent", "Take care.") in harness.transcripts
    assert not harness.service.should_keep_pipeline_open(SESSION_ID)
    await harness.wait_until(lambda: harness._task.done())


async def test_interview_turn_keeps_call_open(harness):
    harness.stt.transcripts.append("I have a headache")
    harness.triage.turns.append(interview_turn("Where does it hurt?"))
    await harness.wait_until(lambda: harness.chunks)

    await harness.speak_turn()
    await harness.wait_until(
        lambda: ("agent", "Where does it hurt?") in harness.transcripts
    )
    assert harness.assessments == []
    assert harness.service.should_keep_pipeline_open(SESSION_ID)


async def test_empty_transcript_speaks_didnt_hear(harness):
    harness.stt.transcripts.append("")
    await harness.wait_until(lambda: harness.chunks)

    await harness.speak_turn()
    await harness.wait_until(
        lambda: ("agent", templates.VOICE_DIDNT_HEAR["en"]) in harness.transcripts
    )
    assert harness.triage.contents == []


async def test_stream_error_speaks_fallback_and_recovers(harness):
    harness.stt.transcripts.append("hello")
    harness.triage.turns.append([{"type": "error", "message": "boom"}])
    await harness.wait_until(lambda: harness.chunks)

    await harness.speak_turn()
    await harness.wait_until(
        lambda: ("agent", templates.VOICE_ERROR["en"]) in harness.transcripts
    )
    assert harness.service.should_keep_pipeline_open(SESSION_ID)

    # next turn works again and resets the error counter
    harness.stt.transcripts.append("hello again")
    harness.triage.turns.append(interview_turn("Go on."))
    await harness.speak_turn()
    await harness.wait_until(lambda: ("agent", "Go on.") in harness.transcripts)
    assert harness.service._sessions[SESSION_ID]["consecutive_errors"] == 0


async def test_repeated_errors_fail_pipeline(harness):
    await harness.wait_until(lambda: harness.chunks)
    for i in range(3):
        harness.stt.transcripts.append("hello")
        harness.triage.turns.append([{"type": "error", "message": "boom"}])
        await harness.speak_turn()
        await harness.wait_until(
            lambda i=i: len(harness.triage.contents) == i + 1
        )
    await harness.wait_until(
        lambda: not harness.service.should_keep_pipeline_open(SESSION_ID)
    )
    await harness.wait_until(lambda: harness._task.done())


async def test_unknown_session_rejected():
    service = TurnVoiceService(
        triage_service=FakeTriageService(),  # duck-typed
        stt_client=FakeStt(),
        tts_client=FakeTts(),
    )

    class NoSessionConn:
        async def fetchrow(self, query, *args):
            return None

    with pytest.raises(ValueError):
        await service.connect(SESSION_ID, "en", NoSessionConn())
    assert not service.should_keep_pipeline_open(SESSION_ID)
