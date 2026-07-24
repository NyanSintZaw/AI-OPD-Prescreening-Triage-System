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
    """Stateful sessions row: holds metadata so the identity gate's
    apply_confirm_decision reads/writes something real."""

    def __init__(self, metadata: dict | None = None) -> None:
        self.metadata = dict(metadata or {})

    async def fetchrow(self, query, *args):
        return {"id": args[0], "metadata": dict(self.metadata)}

    async def execute(self, query, *args):
        if "UPDATE sessions" in query:
            self.metadata = dict(args[1])
        return "UPDATE 1"


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
        self.modes: list[str] = []

    async def process_chat_stream(self, *, connection, session_id, language, input_mode, content):
        assert input_mode in ("voice", "text", "button")
        self.contents.append(content)
        self.modes.append(input_mode)
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
                "flow_complete": True,
                "severity": {"level": "unknown"},
            },
            "assistant_message": {"content": reply},
        },
    ]


class FakeHisAdapter:
    """Records history write-backs from the spoken intake gate."""

    def __init__(self) -> None:
        self.pushes: list[tuple[str, dict]] = []

    async def push_patient_history(self, hn: str, payload: dict) -> bool:
        self.pushes.append((hn, dict(payload)))
        return True


class Harness:
    def __init__(
        self,
        language: str = "en",
        metadata: dict | None = None,
        resume_prompt: str | None = None,
    ) -> None:
        self.resume_prompt = resume_prompt
        self.language = language
        self.stt = FakeStt()
        self.tts = FakeTts()
        self.triage = FakeTriageService()
        self.conn = FakeConn(metadata)
        self.his_adapter = FakeHisAdapter()
        self.service = TurnVoiceService(
            triage_service=self.triage,  # duck-typed
            stt_client=self.stt,
            tts_client=self.tts,
            his_adapter_getter=lambda: self.his_adapter,
        )
        self.transcripts: list[tuple[str, str]] = []
        self.emergencies: list[dict] = []
        self.assessments: list[dict] = []
        self.identities: list[dict] = []
        self.resumes: list[dict] = []
        self.options: list[dict] = []
        self.chunks: list[bytes] = []
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        async def on_transcript(role: str, text: str) -> None:
            self.transcripts.append((role, text))

        async def on_emergency(payload: dict) -> None:
            self.emergencies.append(payload)

        async def on_assessment(payload: dict) -> None:
            self.assessments.append(payload)

        async def on_identity(payload: dict) -> None:
            self.identities.append(payload)

        async def on_resume(payload: dict) -> None:
            self.resumes.append(payload)

        async def on_options(payload: dict) -> None:
            self.options.append(payload)

        await self.service.connect(
            SESSION_ID,
            self.language,
            self.conn,
            transcript_callback=on_transcript,
            emergency_callback=on_emergency,
            assessment_callback=on_assessment,
            options_callback=on_options,
            identity_callback=on_identity,
            resume_callback=on_resume,
            resume_prompt=self.resume_prompt,
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

    async def speak_turn(self, n_loud_chunks: int = 15) -> None:
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


async def test_quiet_first_utterance_triggers_turn(harness):
    """AGC-quiet speech (amp ~320 — below the old fixed 600 gate) must still
    end the turn in a quiet booth: the adaptive gate sits at the configured
    minimum when the noise floor is low. Regression for 'my voice only
    registered after a while' on live calls."""
    quiet_speech = b"\x40\x01" * 640  # 40 ms @16 kHz of amplitude 320
    harness.stt.transcripts.append("sore throat")
    harness.triage.turns.append(interview_turn("Since when?"))
    await harness.wait_until(lambda: harness.chunks)

    # a moment of near-silence first (like the greeting playing)
    for _ in range(10):
        await harness.service.send_audio(SESSION_ID, SILENT_CHUNK)
    for _ in range(10):
        await harness.service.send_audio(SESSION_ID, quiet_speech)
    n_silence = int(SILENCE_HANG_MS / 40) + 1
    for _ in range(n_silence):
        await harness.service.send_audio(SESSION_ID, SILENT_CHUNK)

    await harness.wait_until(lambda: ("user", "sore throat") in harness.transcripts)


async def test_noisy_room_raises_gate():
    """Constant room noise must lift the adaptive gate above the minimum so
    noise alone never counts as speech."""
    from app.services.screening.voice_bridge import (
        NOISE_FLOOR_INITIAL,
        NOISE_GATE_FACTOR,
        SPEECH_AMPLITUDE_THRESHOLD,
    )

    # After sustained noise at amplitude 300, the EMA floor approaches 300 and
    # the gate approaches 300 × factor — so 300-level input stays "noise".
    floor = NOISE_FLOOR_INITIAL
    for _ in range(200):
        gate = max(SPEECH_AMPLITUDE_THRESHOLD, floor * NOISE_GATE_FACTOR)
        assert 300 < gate  # noise never crosses the gate while it adapts
        floor = floor * 0.95 + 300 * 0.05
    assert floor * NOISE_GATE_FACTOR > 900  # settled gate ≈ 3.5× the noise


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
    # After disposition the socket stays OPEN (disposed, not ended): the client
    # finishes the spoken reply, reveals the slip, then hangs up (end_call).
    # Closing here would cut the audio and race the slip reveal.
    assert harness.service._sessions[SESSION_ID]["disposed"] is True
    assert harness.service.should_keep_pipeline_open(SESSION_ID)


async def test_disposed_ignores_further_audio(harness):
    # Once disposed, extra captured audio must not start another triage turn.
    harness.stt.transcripts.append("no thanks")
    harness.triage.turns.append(final_turn("Take care."))
    await harness.wait_until(lambda: harness.chunks)
    await harness.speak_turn()
    await harness.wait_until(lambda: harness.assessments)

    turns_before = len(harness.triage.contents)
    await harness.speak_turn()  # patient says something after disposition
    # Give the pipeline a moment; it must ignore the post-disposition audio.
    await harness.wait_until(
        lambda: not harness.service._sessions[SESSION_ID]["processing"]
    )
    assert len(harness.triage.contents) == turns_before
    assert harness.service.should_keep_pipeline_open(SESSION_ID)


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
    # First empty turn stays silent (the patient is still gathering their
    # thoughts); only a second consecutive empty prompts "couldn't hear you".
    harness.stt.transcripts.append("")
    harness.stt.transcripts.append("")
    await harness.wait_until(lambda: harness.chunks)

    await harness.speak_turn()
    await harness.wait_until(lambda: len(harness.stt.calls) >= 1)
    assert ("agent", templates.VOICE_DIDNT_HEAR["en"]) not in harness.transcripts

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


# ── bilingual voice ─────────────────────────────────────────────────────────────

async def test_injected_turns_carry_input_mode(harness):
    # Spoken turn -> "voice"; tapped quick reply -> "button";
    # measurement popup submission -> default "text".
    harness.stt.transcripts.append("I have a cough")
    harness.triage.turns.append(interview_turn("How long?"))
    await harness.wait_until(lambda: harness.chunks)  # greeting done
    await harness.speak_turn()
    await harness.wait_until(lambda: len(harness.triage.contents) == 1)

    harness.triage.turns.append(interview_turn("Anything else?"))
    harness.service.inject_text_turn(SESSION_ID, "2–3 days", input_mode="button")
    await harness.wait_until(lambda: len(harness.triage.contents) == 2)

    harness.triage.turns.append(interview_turn("Thanks."))
    harness.service.inject_text_turn(SESSION_ID, "37.2°C")
    await harness.wait_until(lambda: len(harness.triage.contents) == 3)

    assert harness.triage.modes == ["voice", "button", "text"]
    assert harness.triage.contents[1] == "2–3 days"


async def test_thai_voice_turn_uses_thai_language_end_to_end():
    """A Thai voice session must greet in Thai and pass language='th' into
    STT (th-TH), the triage engine, and TTS (Thai voice) — proving the
    deterministic engine drives voice in Thai, not just English."""
    harness = Harness(language="th")
    await harness.start()
    try:
        # greeting is the Thai template, TTS asked to speak Thai
        await harness.wait_until(lambda: harness.chunks)
        assert harness.transcripts[0] == ("agent", templates.VOICE_GREETING["th"])
        assert harness.tts.calls[0]["language"] == "th"

        harness.stt.transcripts.append("เจ็บแน่นหน้าอก")
        harness.triage.turns.append(interview_turn("เป็นมานานแค่ไหนคะ"))
        await harness.speak_turn()
        await harness.wait_until(
            lambda: ("agent", "เป็นมานานแค่ไหนคะ") in harness.transcripts
        )

        # STT transcribed with Thai locale
        assert harness.stt.calls[0]["language"] == "th"
        # engine turn ran in Thai
        assert harness.triage.contents == ["เจ็บแน่นหน้าอก"]
        # every TTS call for this session spoke Thai
        assert all(call["language"] == "th" for call in harness.tts.calls)
    finally:
        await harness.stop()


# ── spoken VN identity gate ───────────────────────────────────────────────────

PATIENT = "Waraporn Srisuk"


def identity_harness(language: str = "en", *, first_time: bool = False) -> Harness:
    metadata: dict = {
        "visit": {
            "visit_id": "990000000000000004",
            "patient_name": PATIENT,
            "hn": "09900004",
        },
    }
    if first_time:
        metadata["patient_history"] = {"is_first_time": True}
    return Harness(language=language, metadata=metadata)


async def test_identity_gate_greets_with_confirm_ask_and_chips():
    harness = identity_harness()
    await harness.start()
    try:
        await harness.wait_until(lambda: harness.chunks and harness.options)
        assert harness.transcripts[0] == (
            "agent",
            templates.confirm_name_ask(PATIENT, "en"),
        )
        labels = [o["label"] for o in harness.options[0]["options"]]
        assert labels == ["Yes", "No"]
    finally:
        await harness.stop()


async def test_identity_yes_confirms_and_continues_into_intake():
    harness = identity_harness()
    await harness.start()
    try:
        await harness.wait_until(lambda: harness.chunks)
        harness.stt.transcripts.append("yes that's me")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.identities)

        assert harness.identities == [{"kind": "confirmed", "needs_history": False}]
        assert harness.conn.metadata["visit"]["name_confirmed"] is True
        # Same call continues straight into the intake greeting.
        assert (
            "agent",
            templates.greeting_line(PATIENT, "en"),
        ) in harness.transcripts
        # The clinical pipeline never ran for the identity turn.
        assert harness.triage.contents == []
    finally:
        await harness.stop()


async def test_identity_no_unlinks_and_signals_rejected_thai():
    harness = identity_harness(language="th")
    await harness.start()
    try:
        await harness.wait_until(lambda: harness.chunks)
        harness.stt.transcripts.append("ไม่ใช่ค่ะ คนละคน")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.identities)

        assert harness.identities == [{"kind": "rejected"}]
        assert "visit" not in harness.conn.metadata
        assert (
            "agent",
            templates.CONFIRM_NAME_REJECTED["th"],
        ) in harness.transcripts

        # Rejected → further audio is ignored, no clinical turn ever runs.
        harness.stt.transcripts.append("มีไข้ค่ะ")
        await harness.speak_turn()
        await asyncio.sleep(0.1)
        assert harness.triage.contents == []
    finally:
        await harness.stop()


async def test_identity_chip_tap_no_via_injected_button_turn():
    harness = identity_harness(language="th")
    await harness.start()
    try:
        await harness.wait_until(lambda: harness.chunks)
        harness.service.inject_text_turn(SESSION_ID, "ไม่", "button")
        await harness.wait_until(lambda: harness.identities)
        assert harness.identities == [{"kind": "rejected"}]
        assert "visit" not in harness.conn.metadata
    finally:
        await harness.stop()


async def test_identity_unclear_retries_once_then_rejects():
    harness = identity_harness()
    await harness.start()
    try:
        await harness.wait_until(lambda: harness.chunks)
        harness.stt.transcripts.append("banana banana")
        await harness.speak_turn()
        await harness.wait_until(
            lambda: (
                "agent",
                templates.confirm_name_ask(PATIENT, "en", retry=True),
            )
            in harness.transcripts
        )
        # Link still intact after one unclear answer.
        assert "visit" in harness.conn.metadata

        harness.stt.transcripts.append("what is the weather")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.identities)
        assert harness.identities == [{"kind": "rejected"}]
        assert "visit" not in harness.conn.metadata
    finally:
        await harness.stop()


async def test_identity_yes_first_time_starts_history_intake():
    harness = identity_harness(first_time=True)
    await harness.start()
    try:
        await harness.wait_until(lambda: harness.chunks)
        harness.stt.transcripts.append("yes")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.identities)

        assert harness.identities == [{"kind": "confirmed", "needs_history": True}]
        assert harness.conn.metadata["visit"]["name_confirmed"] is True
        # Same call: spoken intro + first history question, with chips.
        first_q = (
            f"{templates.HISTORY_INTRO['en']} {templates.history_question(0, 'en')}"
        )
        assert ("agent", first_q) in harness.transcripts
        labels = [o["label"] for o in harness.options[-1]["options"]]
        assert labels == [
            o["label"] for o in templates.history_options(0, "en")
        ]
        # No form hand-off, no clinical turn.
        assert harness.triage.contents == []
    finally:
        await harness.stop()


# ── spoken first-time history intake ─────────────────────────────────────────


async def test_history_intake_full_flow_persists_and_continues():
    harness = identity_harness(first_time=True)
    await harness.start()
    try:
        await harness.wait_until(lambda: harness.chunks)
        harness.stt.transcripts.append("yes")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.identities)

        # Q1 spoken by voice, Q3 by chip tap — both rails feed the gate.
        answers = [
            ("I smoke sometimes", "voice"),
            ("None", "chip"),
            ("Diabetes", "chip"),
            ("appendix surgery years ago", "voice"),
            ("None", "chip"),
        ]
        for index, (answer, rail) in enumerate(answers):
            if rail == "voice":
                harness.stt.transcripts.append(answer)
                await harness.speak_turn()
            else:
                await harness.wait_until(
                    lambda: not harness.service._sessions[SESSION_ID]["processing"]
                )
                harness.service.inject_text_turn(SESSION_ID, answer, "button")
            if index < len(answers) - 1:
                next_q = templates.history_question(index + 1, "en")
                await harness.wait_until(
                    lambda: ("agent", next_q) in harness.transcripts
                )

        await harness.wait_until(
            lambda: ("agent", templates.HISTORY_DONE_ASK["en"]) in harness.transcripts
        )
        history = harness.conn.metadata["patient_history"]
        assert history["intake_complete"] is True
        assert history["is_first_time"] is False
        assert history["smoking_alcohol"] == "I smoke sometimes"
        assert history["chronic_conditions"] == "Diabetes"
        assert history["past_surgeries"] == "appendix surgery years ago"
        # Written back to the HIS HN as well.
        assert harness.his_adapter.pushes
        hn, payload = harness.his_adapter.pushes[0]
        assert hn == "09900004"
        assert payload["chronic_conditions"] == "Diabetes"
        # Intake answers never touched the clinical pipeline…
        assert harness.triage.contents == []

        # …but the very next utterance does.
        harness.triage.turns.append(interview_turn())
        harness.stt.transcripts.append("I have a fever")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.triage.contents)
        assert harness.triage.contents == ["I have a fever"]
    finally:
        await harness.stop()


async def test_history_gate_restarts_at_greeting_after_call_drop():
    # Identity was confirmed in a previous call but the intake never finished:
    # a reconnect opens straight on the history questions.
    harness = Harness(
        metadata={
            "visit": {
                "visit_id": "990000000000000004",
                "patient_name": PATIENT,
                "hn": "09900004",
                "name_confirmed": True,
            },
            "patient_history": {"is_first_time": True},
        },
    )
    await harness.start()
    try:
        await harness.wait_until(lambda: harness.chunks and harness.options)
        first_q = (
            f"{templates.HISTORY_INTRO['en']} {templates.history_question(0, 'en')}"
        )
        assert harness.transcripts[0] == ("agent", first_q)
    finally:
        await harness.stop()


async def test_history_blank_answer_reasks_same_question():
    harness = identity_harness(first_time=True)
    await harness.start()
    try:
        await harness.wait_until(lambda: harness.chunks)
        harness.stt.transcripts.append("yes")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.identities)

        await harness.wait_until(
            lambda: not harness.service._sessions[SESSION_ID]["processing"]
        )
        harness.service.inject_text_turn(SESSION_ID, "   ", "button")
        await harness.wait_until(
            lambda: ("agent", templates.HISTORY_RETRY["en"]) in harness.transcripts
        )
        # Still on question 1; a real answer advances to question 2.
        harness.stt.transcripts.append("Neither")
        await harness.speak_turn()
        await harness.wait_until(
            lambda: ("agent", templates.history_question(1, "en"))
            in harness.transcripts
        )
    finally:
        await harness.stop()


# ── spoken resume gate (continue vs start over) ───────────────────────────────


def resume_harness(status: str = "active", *, confirmed: bool = True,
                   language: str = "th") -> Harness:
    return Harness(
        language=language,
        metadata={
            "visit": {
                "visit_id": "990000000000000007",
                "patient_name": "มาลี วงศ์สว่าง",
                "name_confirmed": confirmed,
            },
        },
        resume_prompt=status,
    )


async def confirm_identity_yes(harness: Harness, answer: str = "ใช่ค่ะ") -> None:
    """Pass the identity gate that now opens every resume call."""
    await harness.wait_until(lambda: harness.chunks)
    harness.stt.transcripts.append(answer)
    await harness.speak_turn()
    await harness.wait_until(lambda: harness.identities)
    assert harness.identities[0]["kind"] == "confirmed"


async def test_resume_call_confirms_identity_before_resume_question():
    harness = resume_harness()
    await harness.start()
    try:
        await harness.wait_until(lambda: harness.chunks and harness.options)
        # Even though the previous call confirmed the name, a resume call
        # re-confirms — someone else may have typed the VN.
        assert harness.transcripts[0] == (
            "agent",
            templates.confirm_name_ask("มาลี วงศ์สว่าง", "th"),
        )
        harness.stt.transcripts.append("ใช่ค่ะ")
        await harness.speak_turn()
        await harness.wait_until(
            lambda: ("agent", templates.resume_ask("มาลี วงศ์สว่าง", "th", "active"))
            in harness.transcripts
        )
        assert harness.resumes == []  # question asked, not yet answered
    finally:
        await harness.stop()


async def test_resume_identity_no_keeps_old_session_intact():
    harness = resume_harness()
    await harness.start()
    try:
        await harness.wait_until(lambda: harness.chunks)
        harness.stt.transcripts.append("ไม่ใช่ค่ะ คนละคน")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.identities)
        assert harness.identities == [{"kind": "rejected"}]
        # The REAL patient's session must survive a stranger's "no":
        # still linked, still confirmed.
        assert harness.conn.metadata["visit"]["visit_id"] == "990000000000000007"
        assert harness.conn.metadata["visit"]["name_confirmed"] is True
        assert harness.resumes == []
    finally:
        await harness.stop()


async def test_resume_continue_flows_into_intake():
    harness = resume_harness()
    await harness.start()
    try:
        await confirm_identity_yes(harness)
        harness.stt.transcripts.append("ทำต่อค่ะ")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.resumes)
        assert harness.resumes == [{"kind": "continue", "needs_history": False}]
        # ack + the normal intake greeting followed in the SAME call
        assert (
            "agent",
            templates.RESUME_ACK_CONTINUE["th"],
        ) in harness.transcripts
        assert (
            "agent",
            templates.greeting_line("มาลี วงศ์สว่าง", "th"),
        ) in harness.transcripts
        assert harness.triage.contents == []
    finally:
        await harness.stop()


async def test_resume_continue_first_time_flows_into_history_intake():
    harness = Harness(
        language="en",
        metadata={
            "visit": {
                "visit_id": "990000000000000004",
                "patient_name": PATIENT,
                "hn": "09900004",
                "name_confirmed": True,
            },
            "patient_history": {"is_first_time": True},
        },
        resume_prompt="active",
    )
    await harness.start()
    try:
        await confirm_identity_yes(harness, answer="yes")
        harness.stt.transcripts.append("continue")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.resumes)
        assert harness.resumes == [{"kind": "continue", "needs_history": True}]
        first_q = (
            f"{templates.HISTORY_INTRO['en']} {templates.history_question(0, 'en')}"
        )
        assert ("agent", first_q) in harness.transcripts
    finally:
        await harness.stop()


async def test_resume_start_over_signals_kiosk():
    harness = resume_harness()
    await harness.start()
    try:
        await confirm_identity_yes(harness)
        harness.stt.transcripts.append("เริ่มใหม่ค่ะ")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.resumes)
        assert harness.resumes == [{"kind": "start_over"}]
        # further audio ignored while the kiosk relinks
        harness.stt.transcripts.append("มีไข้ค่ะ")
        await harness.speak_turn()
        await asyncio.sleep(0.1)
        assert harness.triage.contents == []
    finally:
        await harness.stop()


async def test_resume_completed_yes_no_variant():
    harness = resume_harness(status="completed")
    await harness.start()
    try:
        await confirm_identity_yes(harness)
        await harness.wait_until(
            lambda: (
                "agent",
                templates.resume_ask("มาลี วงศ์สว่าง", "th", "completed"),
            )
            in harness.transcripts
        )
        harness.stt.transcripts.append("ไม่ค่ะ")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.resumes)
        assert harness.resumes == [{"kind": "decline"}]
    finally:
        await harness.stop()


async def test_resume_unclear_twice_falls_back_to_buttons():
    harness = resume_harness()
    await harness.start()
    try:
        await confirm_identity_yes(harness)
        harness.stt.transcripts.append("อากาศดีนะ")
        await harness.speak_turn()
        await harness.wait_until(
            lambda: ("agent", templates.RESUME_RETRY["th"]) in harness.transcripts
        )
        harness.stt.transcripts.append("หิวข้าว")
        await harness.speak_turn()
        await harness.wait_until(lambda: harness.resumes)
        assert harness.resumes == [{"kind": "decline"}]
    finally:
        await harness.stop()
