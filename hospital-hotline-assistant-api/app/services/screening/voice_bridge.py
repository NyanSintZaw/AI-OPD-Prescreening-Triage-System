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
import json
import logging
import struct
import time
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
OptionsCallback = Callable[[dict], Awaitable[None]]
IdentityCallback = Callable[[dict], Awaitable[None]]

# Unclear identity answers tolerated before we treat the confirm as rejected
# (safe default: never start a clinical interview on an unverified identity).
MAX_IDENTITY_RETRIES = 2

INPUT_SAMPLE_RATE = 16_000   # browser worklet sends 16 kHz mono Int16
OUTPUT_SAMPLE_RATE = 24_000  # frontend playback scheduler expects 24 kHz
_BYTES_PER_MS = INPUT_SAMPLE_RATE * 2 // 1000

# Endpointing thresholds are env-tunable (app.config) so the booth can be
# balanced on-site without a code change — restart to apply. Defaults:
#   amplitude 250  : MINIMUM mic level counted as speech; the effective gate
#                    is max(this, noise_gate_factor × rolling noise floor).
#                    Browser auto-gain starts low and ramps over the first
#                    seconds of a call, so a high fixed gate silently drops
#                    the caller's first utterance (observed live: "my voice
#                    only registered after a while"). A missed-quiet-speech
#                    turn is dead air; a false trigger is just an empty STT
#                    turn we already discard — keep the minimum low.
#   silence   2500 : ms of silence after speech that ends the caller's turn
#                    (higher = fewer mid-thought cut-offs but slower)
#   min_turn  500  : ms; drop blips shorter than this
from app.config import settings as _settings

SPEECH_AMPLITUDE_THRESHOLD = getattr(_settings, "voice_speech_amplitude_threshold", 250)
NOISE_GATE_FACTOR = getattr(_settings, "voice_noise_gate_factor", 3.5)
SILENCE_HANG_MS = getattr(_settings, "voice_silence_hang_ms", 2500)
MIN_TURN_AUDIO_MS = getattr(_settings, "voice_min_turn_audio_ms", 500)
# Rolling noise-floor EMA: starting estimate and smoothing per 40 ms chunk.
# Start LOW so the cold-start gate sits near the minimum — the greeting gives
# the EMA ~5 s of room audio to adapt upward before the caller first speaks.
NOISE_FLOOR_INITIAL = 100.0
NOISE_FLOOR_ALPHA = 0.05
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
        options_callback: OptionsCallback | None = None,
        identity_callback: IdentityCallback | None = None,
    ) -> None:
        from app.services.visit_confirm import needs_history_intake

        row = await db_connection.fetchrow(
            "SELECT id, metadata FROM sessions WHERE id = $1", session_id
        )
        if row is None:
            raise ValueError("Session not found")
        metadata = row["metadata"] or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        visit_meta = metadata.get("visit") or {}
        patient_name = visit_meta.get("patient_name")

        self._sessions[session_id] = {
            "language": language,
            # From the linked HIS visit; personalizes the spoken greeting.
            "patient_name": patient_name,
            # Spoken identity gate: a linked, not-yet-confirmed name means the
            # call opens with "you are {name}, right?" and no clinical turn
            # runs until the patient confirms (or the kiosk falls back).
            "awaiting_identity": bool(patient_name)
            and not bool(visit_meta.get("name_confirmed")),
            "identity_attempts": 0,
            "needs_history": needs_history_intake(metadata),
            "identity_cb": identity_callback,
            "db_connection": db_connection,
            "db_pool": db_pool,
            "transcript_cb": transcript_callback,
            "emergency_cb": emergency_callback,
            "assessment_cb": assessment_callback,
            "measurement_cb": measurement_callback,
            "options_cb": options_callback,
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
            # Rolling room-noise estimate feeding the adaptive speech gate.
            "noise_floor": NOISE_FLOOR_INITIAL,
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

        # Adaptive speech gate: a quiet booth lowers it toward the configured
        # minimum so AGC-quiet first utterances still register; a noisy booth
        # raises it so room noise doesn't count as speech.
        amplitude = mean_abs_amplitude(audio_chunk)
        floor = session.get("noise_floor", NOISE_FLOOR_INITIAL)
        gate = max(SPEECH_AMPLITUDE_THRESHOLD, floor * NOISE_GATE_FACTOR)
        if amplitude >= gate:
            session["speech_seen"] = True
            session["trailing_silence_ms"] = 0.0
        else:
            session["noise_floor"] = (
                floor * (1 - NOISE_FLOOR_ALPHA) + amplitude * NOISE_FLOOR_ALPHA
            )
            if session["speech_seen"]:
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

    def inject_text_turn(
        self, session_id: str, content: str, input_mode: str = "text"
    ) -> None:
        """Queue a text turn to run as if the patient had spoken it. Used by
        the measurement popups (input_mode "text") and quick-reply taps
        (input_mode "button"); the mode is persisted on the message so the
        nurse transcript shows how the answer was given."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        session["injected_text"] = (content, input_mode)
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
            if session.get("awaiting_identity"):
                ask = templates.confirm_name_ask(
                    session["patient_name"], session["language"]
                )
                async for chunk in self._speak_line(session_id, session, ask):
                    yield chunk
                await self._push_identity_options(session_id, session)
            else:
                greeting = templates.greeting_line(
                    session.get("patient_name"), session["language"]
                )
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
                    # A client-submitted reading or tapped quick reply: run it
                    # as a text/button turn, bypassing STT and the audio buffer.
                    injected_text, injected_mode = injected
                    async for chunk in self._process_transcript(
                        session_id, session, injected_text, input_mode=injected_mode
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
        stt_started = time.monotonic()
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
        session["last_stt_ms"] = int((time.monotonic() - stt_started) * 1000)

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
        self,
        session_id: str,
        session: dict[str, Any],
        transcript: str,
        input_mode: str = "voice",
    ) -> AsyncIterator[bytes]:
        """Run one turn from an already-decoded utterance: persist it, drive
        the triage pipeline, speak the reply, and fire measurement/assessment
        callbacks. Shared by the audio path (input_mode "voice") and injected
        turns (measurement popup "text", quick-reply tap "button")."""

        language = session["language"]
        await self._push_transcript(session, "user", transcript)

        # Identity gate: while unconfirmed, answers (spoken or tapped chips)
        # are classified as yes/no — the triage pipeline never runs.
        if session.get("awaiting_identity"):
            async for chunk in self._handle_identity_turn(
                session_id, session, transcript
            ):
                yield chunk
            return

        turn_started = time.monotonic()
        try:
            reply, final_payload = await self._run_turn(
                session_id, session, transcript, input_mode
            )
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
        pipeline_ms = int((time.monotonic() - turn_started) * 1000)

        tts_started = time.monotonic()
        if reply:
            async for chunk in self._speak_line(session_id, session, reply):
                yield chunk
        tts_ms = int((time.monotonic() - tts_started) * 1000)
        # Per-stage turn timing: the answer to "why did the reply take so
        # long?" — pipeline is STT->reply latency the caller actually feels.
        logger.info(
            "voice turn timing %s: stt=%sms pipeline=%sms tts+stream=%sms",
            session_id,
            session.pop("last_stt_ms", None),
            pipeline_ms,
            tts_ms,
        )

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

        # Tappable quick-replies for the spoken question (after TTS).
        reply_options = session.pop("reply_options", None) or []
        if reply_options:
            options_cb: OptionsCallback | None = session.get("options_cb")
            if options_cb is not None:
                try:
                    await options_cb({"options": reply_options})
                except Exception:
                    logger.exception("options_cb failed for %s", session_id)

        if final_payload is not None:
            # Flow is complete (incl. follow-up). Keep the socket open so the
            # client can finish speaking, reveal the slip, then hang up.
            # Further audio turns are ignored while disposed.
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

    # ------------------------------------------------------------------
    # Spoken VN identity gate
    # ------------------------------------------------------------------

    async def _push_identity_options(
        self, session_id: str, session: dict[str, Any]
    ) -> None:
        """Tappable ใช่/ไม่ใช่ chips under the spoken confirm question."""
        options_cb: OptionsCallback | None = session.get("options_cb")
        if options_cb is None:
            return
        options = templates.YES_NO_OPTIONS.get(
            session["language"], templates.YES_NO_OPTIONS["en"]
        )
        try:
            await options_cb({"options": [dict(o) for o in options]})
        except Exception:
            logger.exception("identity options_cb failed for %s", session_id)

    async def _apply_identity_decision(
        self, session: dict[str, Any], session_id: str, decision: str
    ):
        from app.services.visit_confirm import apply_confirm_decision

        db_pool = session.get("db_pool")
        if db_pool is not None:
            async with db_pool.acquire() as connection:
                return await apply_confirm_decision(connection, session_id, decision)
        return await apply_confirm_decision(
            session["db_connection"], session_id, decision
        )

    async def _fire_identity(
        self, session_id: str, session: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        identity_cb: IdentityCallback | None = session.get("identity_cb")
        if identity_cb is None:
            return
        try:
            await identity_cb(payload)
        except Exception:
            logger.exception("identity_cb failed for %s", session_id)

    async def _handle_identity_turn(
        self, session_id: str, session: dict[str, Any], transcript: str
    ) -> AsyncIterator[bytes]:
        """Classify a confirm-name answer and speak/signal the outcome.

        yes → mark confirmed and either continue into the intake greeting
        (same call) or hand off to the history form; no → unlink the visit,
        tell the patient to re-enter their VN, and signal the kiosk to end
        the call; unclear → re-ask up to MAX_IDENTITY_RETRIES times, then
        treat as rejected (never interview an unverified identity).
        """
        from app.services.screening.nlu_yesno import classify_yes_no
        from app.services.visit_confirm import NoVisitLinkedError

        language = session["language"]
        decision = classify_yes_no(transcript)
        if decision in ("uncertain", "other"):
            session["identity_attempts"] += 1
            if session["identity_attempts"] < MAX_IDENTITY_RETRIES:
                retry = templates.confirm_name_ask(
                    session["patient_name"], language, retry=True
                )
                async for chunk in self._speak_line(session_id, session, retry):
                    yield chunk
                await self._push_identity_options(session_id, session)
                return
            decision = "no"

        try:
            outcome = await self._apply_identity_decision(
                session, session_id, decision
            )
        except NoVisitLinkedError:
            # Link vanished mid-confirm (e.g. REST unlink raced us) — treat
            # as rejected so the kiosk returns to VN entry.
            outcome = None
        except Exception:
            logger.exception("identity decision persist failed for %s", session_id)
            outcome = None

        if decision == "yes" and outcome is not None:
            session["awaiting_identity"] = False
            needs_history = bool(session.get("needs_history"))
            if needs_history:
                # The kiosk ends this call and shows the history form; drop
                # any further audio until it does.
                session["disposed"] = True
                line = templates.CONFIRM_NAME_HISTORY_NEXT[language]
            else:
                line = templates.greeting_line(session.get("patient_name"), language)
            async for chunk in self._speak_line(session_id, session, line):
                yield chunk
            await self._fire_identity(
                session_id,
                session,
                {"kind": "confirmed", "needs_history": needs_history},
            )
            return

        # decision == "no", exhausted retries, or persistence failure. The
        # kiosk ends the call and returns to VN entry; ignore further audio.
        session["awaiting_identity"] = False
        session["disposed"] = True
        async for chunk in self._speak_line(
            session_id, session, templates.CONFIRM_NAME_REJECTED[language]
        ):
            yield chunk
        await self._fire_identity(session_id, session, {"kind": "rejected"})

    async def _run_turn(
        self,
        session_id: str,
        session: dict[str, Any],
        content: str,
        input_mode: str = "voice",
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
                    connection, session_id, session, content, input_mode
                )
        return await self._consume_turn_events(
            session["db_connection"], session_id, session, content, input_mode
        )

    async def _consume_turn_events(
        self,
        connection: asyncpg.Connection,
        session_id: str,
        session: dict[str, Any],
        content: str,
        input_mode: str = "voice",
    ) -> tuple[str, dict[str, Any] | None]:
        reply = ""
        final_payload: dict[str, Any] | None = None
        async for event in self.triage_service.process_chat_stream(
            connection=connection,
            session_id=session_id,
            language=session["language"],
            input_mode=input_mode,
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
                if result.get("flow_complete"):
                    final_payload = result
                session["awaiting_measurement"] = result.get("awaiting_measurement")
                session["reply_options"] = result.get("reply_options") or []
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
