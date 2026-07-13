"""Turn-based voice bridge (``VOICE_ENGINE=turn``).

Drives live calls through the same per-turn triage pipeline as text chat
(``TriageService.process_chat_stream``), so the deterministic screening
engine controls voice conversations too. Speech I/O uses the existing
one-shot Google STT/TTS clients instead of Gemini Live:

    mic PCM 16 kHz → buffer → (client ``end_of_turn`` | server silence
    fallback ~1.2 s) → STT → process_chat_stream → TTS LINEAR16 24 kHz
    → binary WS frames

``TurnVoiceService`` mirrors ``LiveVoiceService``'s surface exactly, so the
``/ws/voice/{session_id}`` route and the frontend protocol stay unchanged.
Persistence happens per turn inside ``process_chat_stream`` — there is no
end-of-call transcript replay. Known trade-off vs Gemini Live: per-turn
latency instead of full-duplex; acceptable for the demo workstation.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from array import array
from typing import Any, AsyncIterator, Awaitable, Callable

import asyncpg

from app.services.triage_service import TriageService

from . import templates

logger = logging.getLogger(__name__)

TranscriptCallback = Callable[[str, str], Awaitable[None]]
EmergencyCallback = Callable[[dict], Awaitable[None]]
AssessmentCallback = Callable[[dict], Awaitable[None]]
MeasurementCallback = Callable[[dict], Awaitable[None]]

INPUT_SAMPLE_RATE = 16_000   # browser worklet sends 16 kHz mono Int16
OUTPUT_SAMPLE_RATE = 24_000  # frontend playback scheduler expects 24 kHz
_BYTES_PER_MS = INPUT_SAMPLE_RATE * 2 // 1000

# Endpointing thresholds are env-tunable (app.config) so the booth can be
# balanced on-site without a code change — restart to apply. Defaults:
#   amplitude 600  : mic level counted as speech (higher ignores room noise)
#   silence   2500 : ms of silence after speech that ends the caller's turn
#                    (higher = fewer mid-thought cut-offs but slower)
#   min_turn  500  : ms; drop blips shorter than this
from app.config import settings as _settings

SPEECH_AMPLITUDE_THRESHOLD = getattr(_settings, "voice_speech_amplitude_threshold", 600)
SILENCE_HANG_MS = getattr(_settings, "voice_silence_hang_ms", 2500)
MIN_TURN_AUDIO_MS = getattr(_settings, "voice_min_turn_audio_ms", 500)
# Hard cap so a stuck-open mic cannot buffer unbounded audio (~60 s).
MAX_TURN_BUFFER_BYTES = 60 * INPUT_SAMPLE_RATE * 2
# One outbound WS frame ≈ 200 ms of 24 kHz Int16 audio.
TTS_CHUNK_BYTES = OUTPUT_SAMPLE_RATE * 2 // 5
# Consecutive failed turns before the pipeline gives up and the route
# tears the call down.
MAX_TURN_ERRORS = 3


def mean_abs_amplitude(chunk: bytes) -> float:
    """Mean |sample| of an Int16 little-endian PCM chunk."""

    usable = len(chunk) - (len(chunk) % 2)
    if usable <= 0:
        return 0.0
    samples = array("h")
    samples.frombytes(chunk[:usable])
    return sum(abs(s) for s in samples) / len(samples)


def pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw mono Int16 PCM in a WAV container.

    Cloud STT reads the sample rate from the WAV header, which spares the
    shared ``GoogleSttClient`` from growing a raw-PCM-specific parameter.
    """

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", len(pcm),
    )
    return header + pcm


class TurnVoiceService:
    """Per-session orchestrator for turn-based voice calls.

    Duck-types ``LiveVoiceService``: connect / disconnect /
    should_keep_pipeline_open / send_audio / set_mute / end_user_turn /
    run_live_pipeline. State is a per-session dict holding the audio
    buffer, the turn boundary event, and the WS callbacks.
    """

    def __init__(
        self,
        *,
        triage_service: TriageService,
        stt_client,
        tts_client,
    ) -> None:
        self.triage_service = triage_service
        self.stt_client = stt_client
        self.tts_client = tts_client
        self._sessions: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(
        self,
        session_id: str,
        language: str,
        db_connection: asyncpg.Connection,
        *,
        db_pool: asyncpg.Pool | None = None,
        transcript_callback: TranscriptCallback | None = None,
        emergency_callback: EmergencyCallback | None = None,
        assessment_callback: AssessmentCallback | None = None,
        measurement_callback: MeasurementCallback | None = None,
    ) -> None:
        row = await db_connection.fetchrow(
            "SELECT id FROM sessions WHERE id = $1", session_id
        )
        if row is None:
            raise ValueError("Session not found")

        self._sessions[session_id] = {
            "language": language,
            "db_connection": db_connection,
            "db_pool": db_pool,
            "transcript_cb": transcript_callback,
            "emergency_cb": emergency_callback,
            "assessment_cb": assessment_callback,
            "measurement_cb": measurement_callback,
            "buffer": bytearray(),
            "turn_event": asyncio.Event(),
            # Client-driven mic gate (mute / unmute / end_of_turn — the
            # client mirrors this flag and auto-unmutes after playback).
            "muted": False,
            # Internal gate while a turn is being transcribed/processed;
            # separate from ``muted`` because silence-fallback turns must
            # not leave the server muted with the client unaware.
            "processing": False,
            "speech_seen": False,
            "trailing_silence_ms": 0.0,
            "greeted": False,
            "ended": False,
            "disposed": False,
            "pipeline_failed": False,
            "emergency_announced": False,
            "consecutive_errors": 0,
            # Consecutive empty/inaudible turns; used to suppress the
            # "sorry, I couldn't hear you" line on the first miss.
            "empty_turns": 0,
        }
        logger.info(
            "Turn voice session connected: %s language=%s", session_id, language
        )

    async def disconnect(self, session_id: str) -> None:
        """Drop session state. Idempotent.

        Unlike the live path there is nothing to flush: every completed
        turn already persisted its messages and assessment rows through
        ``process_chat_stream``.
        """

        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        session["ended"] = True
        session["turn_event"].set()
        logger.info("Turn voice session disconnected: %s", session_id)

    def should_keep_pipeline_open(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        return not session["ended"] and not session["pipeline_failed"]

    # ------------------------------------------------------------------
    # Inbound audio (browser → turn buffer)
    # ------------------------------------------------------------------

    async def send_audio(self, session_id: str, audio_chunk: bytes) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        if session["muted"] or session["processing"] or not audio_chunk:
            return

        session["buffer"].extend(audio_chunk)

        if mean_abs_amplitude(audio_chunk) >= SPEECH_AMPLITUDE_THRESHOLD:
            session["speech_seen"] = True
            session["trailing_silence_ms"] = 0.0
        elif session["speech_seen"]:
            session["trailing_silence_ms"] += len(audio_chunk) / _BYTES_PER_MS
            if session["trailing_silence_ms"] >= SILENCE_HANG_MS:
                session["turn_event"].set()
                return

        if len(session["buffer"]) >= MAX_TURN_BUFFER_BYTES:
            session["turn_event"].set()

    def set_mute(self, session_id: str, muted: bool) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        session["muted"] = muted
        logger.info("Session %s mute=%s", session_id, muted)

    def end_user_turn(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        # Mirrors the live protocol: the Send button muted the client
        # already; it auto-unmutes once the agent's reply finishes playing.
        session["muted"] = True
        session["turn_event"].set()

    def inject_text_turn(self, session_id: str, content: str) -> None:
        """Queue a text turn to run as if the patient had spoken it. Used by
        the temperature-on-demand popup: the client submits the reading and we
        drive a turn (whose turn_context now carries the measured value) so the
        engine proceeds without waiting for the patient to speak again."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        session["injected_text"] = content
        session["muted"] = True
        session["turn_event"].set()

    # ------------------------------------------------------------------
    # Outbound pipeline (turn loop → browser)
    # ------------------------------------------------------------------

    async def run_live_pipeline(self, session_id: str) -> AsyncIterator[bytes]:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")

        if not session["greeted"]:
            session["greeted"] = True
            greeting = templates.VOICE_GREETING[session["language"]]
            async for chunk in self._speak_line(session_id, session, greeting):
                yield chunk

        while not session["ended"] and not session["pipeline_failed"]:
            await session["turn_event"].wait()
            session["turn_event"].clear()
            if session["ended"]:
                return
            # After disposition the interview is over — the socket stays open
            # only so the client can play the final reply, show the slip, and
            # hang up. Ignore any further captured audio.
            if session.get("disposed"):
                session["buffer"].clear()
                session["speech_seen"] = False
                session["trailing_silence_ms"] = 0.0
                continue

            session["processing"] = True
            injected = session.pop("injected_text", None)
            pcm = bytes(session["buffer"])
            try:
                if injected:
                    # A client-submitted reading (e.g. temperature): run it as
                    # a text turn, bypassing STT and the audio buffer.
                    async for chunk in self._process_transcript(
                        session_id, session, injected
                    ):
                        yield chunk
                else:
                    async for chunk in self._process_turn(session_id, session, pcm):
                        yield chunk
            finally:
                session["processing"] = False
                session["buffer"].clear()
                session["speech_seen"] = False
                session["trailing_silence_ms"] = 0.0

    async def _process_turn(
        self, session_id: str, session: dict[str, Any], pcm: bytes
    ) -> AsyncIterator[bytes]:
        language = session["language"]
        if len(pcm) < MIN_TURN_AUDIO_MS * _BYTES_PER_MS:
            return

        transcript: str | None
        try:
            stt = await self.stt_client.transcribe(
                audio_bytes=pcm16_to_wav(pcm, INPUT_SAMPLE_RATE),
                language=language,
                mime_type="audio/wav",
            )
            transcript = (stt.transcript or "").strip()
        except Exception:
            logger.exception("STT failed for %s", session_id)
            transcript = None

        if transcript is None:
            async for chunk in self._speak_line(
                session_id, session, templates.VOICE_ERROR[language]
            ):
                yield chunk
            return
        if not transcript:
            # A patient still gathering their thoughts produces an empty
            # turn. Stay silent on the first miss and just keep listening;
            # only prompt "sorry, I couldn't hear you" after two in a row.
            session["empty_turns"] = session.get("empty_turns", 0) + 1
            if session["empty_turns"] >= 2:
                session["empty_turns"] = 0
                async for chunk in self._speak_line(
                    session_id, session, templates.VOICE_DIDNT_HEAR[language]
                ):
                    yield chunk
            return
        session["empty_turns"] = 0

        async for chunk in self._process_transcript(session_id, session, transcript):
            yield chunk

    async def _process_transcript(
        self, session_id: str, session: dict[str, Any], transcript: str
    ) -> AsyncIterator[bytes]:
        """Run one turn from an already-decoded utterance: persist it, drive
        the triage pipeline, speak the reply, and fire measurement/assessment
        callbacks. Shared by the audio path and injected text turns (e.g. a
        temperature entered into the client's numeric popup)."""

        language = session["language"]
        await self._push_transcript(session, "user", transcript)

        try:
            reply, final_payload = await self._run_turn(session_id, session, transcript)
        except Exception:
            logger.exception("Voice turn pipeline failed for %s", session_id)
            session["consecutive_errors"] += 1
            if session["consecutive_errors"] >= MAX_TURN_ERRORS:
                session["pipeline_failed"] = True
                return
            async for chunk in self._speak_line(
                session_id, session, templates.VOICE_ERROR[language]
            ):
                yield chunk
            return
        session["consecutive_errors"] = 0

        if reply:
            async for chunk in self._speak_line(session_id, session, reply):
                yield chunk

        # The engine asked the booth to take a reading (e.g. temperature).
        # Pop the numeric input on the client once the spoken prompt is out.
        awaiting = session.pop("awaiting_measurement", None)
        if awaiting:
            measurement_cb: MeasurementCallback | None = session.get("measurement_cb")
            if measurement_cb is not None:
                try:
                    await measurement_cb({"vital": awaiting})
                except Exception:
                    logger.exception("measurement_cb failed for %s", session_id)

        if final_payload is not None:
            # Interview is done, but DON'T close the socket yet: keep it open so
            # the client can finish speaking the disposition, reveal the slip
            # once its audio drains, then hang up gracefully (end_call). Closing
            # here would cut the audio and race the slip reveal. Further audio
            # turns are ignored while disposed.
            session["disposed"] = True
            assessment_cb: AssessmentCallback | None = session.get("assessment_cb")
            if assessment_cb is not None:
                payload = dict(final_payload)
                payload["auto_end"] = True
                try:
                    await assessment_cb(payload)
                except Exception:
                    logger.exception("assessment_cb failed for %s", session_id)
            logger.info("Turn voice assessment complete for %s", session_id)

    async def _run_turn(
        self, session_id: str, session: dict[str, Any], content: str
    ) -> tuple[str, dict[str, Any] | None]:
        """One triage turn. Returns (reply_text, final_payload_or_None).

        ``final_payload`` is set only on the terminal ``complete`` event
        whose result says the assessment finished (interview turns also
        emit ``complete`` — with ``assessment_status="in_progress"``).
        """

        db_pool: asyncpg.Pool | None = session.get("db_pool")
        if db_pool is not None:
            async with db_pool.acquire() as connection:
                return await self._consume_turn_events(
                    connection, session_id, session, content
                )
        return await self._consume_turn_events(
            session["db_connection"], session_id, session, content
        )

    async def _consume_turn_events(
        self,
        connection: asyncpg.Connection,
        session_id: str,
        session: dict[str, Any],
        content: str,
    ) -> tuple[str, dict[str, Any] | None]:
        reply = ""
        final_payload: dict[str, Any] | None = None
        async for event in self.triage_service.process_chat_stream(
            connection=connection,
            session_id=session_id,
            language=session["language"],
            input_mode="voice",
            content=content,
        ):
            event_type = event.get("type")
            if event_type == "classified":
                await self._maybe_announce_emergency(
                    session_id, session, event.get("classification") or {}
                )
            elif event_type == "turn_complete":
                reply = (event.get("assistant_message") or {}).get("content") or ""
            elif event_type == "complete":
                result = event.get("result") or {}
                reply = (
                    (event.get("assistant_message") or {}).get("content")
                    or result.get("reply")
                    or ""
                )
                if result.get("assessment_status") == "complete":
                    final_payload = result
                session["awaiting_measurement"] = result.get("awaiting_measurement")
            elif event_type == "error":
                raise RuntimeError(str(event.get("message")))
        return reply, final_payload

    async def _maybe_announce_emergency(
        self, session_id: str, session: dict[str, Any], classification: dict[str, Any]
    ) -> None:
        level = classification.get("level")
        if not isinstance(level, int) or level not in (1, 2):
            return
        if session["emergency_announced"]:
            return
        session["emergency_announced"] = True
        emergency_cb: EmergencyCallback | None = session.get("emergency_cb")
        if emergency_cb is None:
            return
        banner = {
            "severity": "emergency",
            "level": level,
            "alert_message": classification.get("key_reason") or "Emergency triage match",
            "department_code": classification.get("department_code"),
            "color": classification.get("color"),
            "label": classification.get("label"),
            "detected_symptoms": (
                [classification["symptoms_summary"]]
                if isinstance(classification.get("symptoms_summary"), str)
                else []
            ),
        }
        try:
            await emergency_cb(banner)
        except Exception:
            logger.exception("emergency_cb failed for %s", session_id)

    # ------------------------------------------------------------------
    # Speech out
    # ------------------------------------------------------------------

    async def _speak_line(
        self, session_id: str, session: dict[str, Any], text: str
    ) -> AsyncIterator[bytes]:
        await self._push_transcript(session, "agent", text)
        try:
            audio = await self.tts_client.synthesize(
                text=text,
                language=session["language"],
                audio_encoding="linear16",
                sample_rate_hertz=OUTPUT_SAMPLE_RATE,
            )
        except Exception:
            # Caption already went out on the JSON channel, so the caller
            # still sees the reply even if they can't hear it.
            logger.exception("TTS failed for %s", session_id)
            return
        for offset in range(0, len(audio), TTS_CHUNK_BYTES):
            yield audio[offset:offset + TTS_CHUNK_BYTES]

    async def _push_transcript(
        self, session: dict[str, Any], role: str, text: str
    ) -> None:
        transcript_cb: TranscriptCallback | None = session.get("transcript_cb")
        if transcript_cb is None or not text:
            return
        try:
            await transcript_cb(role, text)
        except Exception:
            logger.debug("transcript_cb failed (likely client closed)")
