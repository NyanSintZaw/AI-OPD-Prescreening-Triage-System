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
from .viseme_track import build_viseme_track

logger = logging.getLogger(__name__)

TranscriptCallback = Callable[[str, str], Awaitable[None]]
EmergencyCallback = Callable[[dict], Awaitable[None]]
AssessmentCallback = Callable[[dict], Awaitable[None]]
MeasurementCallback = Callable[[dict], Awaitable[None]]
OptionsCallback = Callable[[dict], Awaitable[None]]
IdentityCallback = Callable[[dict], Awaitable[None]]
ResumeCallback = Callable[[dict], Awaitable[None]]
VisemeCallback = Callable[[dict], Awaitable[None]]

# Unclear identity answers tolerated before we treat the confirm as rejected
# (safe default: never start a clinical interview on an unverified identity).
MAX_IDENTITY_RETRIES = 2
# Unclear resume answers tolerated before falling back to the on-screen
# buttons (kind "decline" — the kiosk keeps its chooser visible).
MAX_RESUME_RETRIES = 2

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
# Sliding turn window: keep only the most recent audio. Two constraints:
# Google's synchronous recognize hard-rejects ≥1 min of audio, and the
# amplitude gate must NEVER decide what gets transcribed — quiet real-mic
# speech sits below the gate, so an amplitude-gated trim silently discarded
# whole answers (live regression 2026-07-27: the browser caption heard the
# patient, STT got an empty tail). The gate only drives the silence
# fallback; the buffer itself is amplitude-blind.
TURN_BUFFER_KEEP_BYTES = 45 * INPUT_SAMPLE_RATE * 2
TURN_BUFFER_TRIM_AT_BYTES = 50 * INPUT_SAMPLE_RATE * 2
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
        his_adapter_getter: Callable[[], Any] | None = None,
    ) -> None:
        self.triage_service = triage_service
        self.stt_client = stt_client
        self.tts_client = tts_client
        # Getter, not a reference: the admin HIS-connection endpoints swap
        # ``app.state.his_adapter`` at runtime and the spoken history gate
        # must write to whichever adapter is current.
        self.his_adapter_getter = his_adapter_getter
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
        resume_callback: ResumeCallback | None = None,
        viseme_callback: VisemeCallback | None = None,
        resume_prompt: str | None = None,
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

        is_resume_call = resume_prompt in ("active", "completed")
        self._sessions[session_id] = {
            "language": language,
            # From the linked HIS visit; personalizes the spoken greeting.
            "patient_name": patient_name,
            # Spoken identity gate: a linked, not-yet-confirmed name means the
            # call opens with "you are {name}, right?" and no clinical turn
            # runs until the patient confirms (or the kiosk falls back).
            # A resume call ALWAYS re-confirms, even though the previous call
            # stamped name_confirmed — someone else may have typed the VN.
            "awaiting_identity": bool(patient_name)
            and (is_resume_call or not bool(visit_meta.get("name_confirmed"))),
            "identity_attempts": 0,
            # Re-confirming on a resumed session: a "no" must NOT unlink or
            # strip the real patient's session — the wrong person is simply
            # sent back to VN entry.
            "resume_reconfirm": is_resume_call,
            "needs_history": needs_history_intake(metadata),
            "identity_cb": identity_callback,
            # Spoken resume gate: the kiosk found a same-day session for this
            # VN and asks continue-vs-start-over (after the identity confirm).
            "awaiting_resume": is_resume_call,
            "resume_status": resume_prompt or "",
            "resume_attempts": 0,
            "resume_cb": resume_callback,
            # Spoken first-time history intake, one question per turn; armed
            # by needs_history and started once identity/resume are resolved.
            "awaiting_history": False,
            "history_index": 0,
            "history_answers": {},
            "db_connection": db_connection,
            "db_pool": db_pool,
            "transcript_cb": transcript_callback,
            "emergency_cb": emergency_callback,
            "assessment_cb": assessment_callback,
            "measurement_cb": measurement_callback,
            "options_cb": options_callback,
            "viseme_cb": viseme_callback,
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
        buf = session["buffer"]
        if len(buf) > TURN_BUFFER_TRIM_AT_BYTES:
            del buf[: len(buf) - TURN_BUFFER_KEEP_BYTES]

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


    def set_mute(self, session_id: str, muted: bool) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        session["muted"] = muted
        logger.info("Session %s mute=%s", session_id, muted)

    def end_user_turn(self, session_id: str, caption: str = "") -> None:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        # Browser live-caption text for this turn: the STT fallback when the
        # captured audio transcribes empty (AGC-quiet first utterances) —
        # what streamed on the patient's screen is always honored.
        session["turn_caption"] = caption.strip()
        # Mirrors the live protocol: the Send button muted the client
        # already; it auto-unmutes once the agent's reply finishes playing.
        session["muted"] = True
        # An explicit "Done" tap must ALWAYS produce a spoken reply: the
        # client sits muted in "thinking" until reply audio drains, so the
        # silent first-miss grace (meant for the passive silence fallback)
        # would wedge the kiosk if no audio reached us this turn.
        # EXCEPT when a turn is already mid-flight: a tap racing the silence
        # fallback is a redundant ack of the answer being processed — flag
        # it explicit and the follow-up empty pass would announce "didn't
        # hear" for a turn that WAS heard (live report 2026-07-27).
        session["explicit_turn"] = not session["processing"]
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
                # Identity first — resume/history questions only make sense
                # once we know the right person is standing at the kiosk.
                ask = templates.confirm_name_ask(
                    session["patient_name"], session["language"]
                )
                async for chunk in self._speak_line(session_id, session, ask):
                    yield chunk
                await self._push_identity_options(session_id, session)
            elif session.get("awaiting_resume"):
                ask = templates.resume_ask(
                    session.get("patient_name"),
                    session["language"],
                    session["resume_status"],
                )
                async for chunk in self._speak_line(session_id, session, ask):
                    yield chunk
            elif session.get("needs_history"):
                # Call (re)opened with identity already confirmed but intake
                # unfinished — e.g. the call dropped mid-intake.
                async for chunk in self._start_history_gate(session_id, session):
                    yield chunk
            else:
                # Fresh sessions get the greeting; a call reopened on a
                # mid-interview session re-speaks its pending question.
                async for chunk in self._speak_pending_point(session_id, session):
                    yield chunk

        while not session["ended"] and not session["pipeline_failed"]:
            await session["turn_event"].wait()
            session["turn_event"].clear()
            explicit = bool(session.pop("explicit_turn", False))
            caption = str(session.pop("turn_caption", "") or "")
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
                    async for chunk in self._process_turn(
                        session_id, session, pcm, explicit=explicit, caption=caption
                    ):
                        yield chunk
            finally:
                session["processing"] = False
                session["buffer"].clear()
                session["speech_seen"] = False
                session["trailing_silence_ms"] = 0.0

    async def _process_turn(
        self,
        session_id: str,
        session: dict[str, Any],
        pcm: bytes,
        explicit: bool = False,
        caption: str = "",
    ) -> AsyncIterator[bytes]:
        language = session["language"]
        if len(pcm) < MIN_TURN_AUDIO_MS * _BYTES_PER_MS:
            if caption:
                # No usable audio, but the browser caption transcribed the
                # patient — honor what streamed on their screen.
                async for chunk in self._process_transcript(
                    session_id, session, caption
                ):
                    yield chunk
                return
            if explicit:
                # Tapped "Done" but no usable audio arrived (dropped mic
                # frames, tap without speaking). Reply audio is what releases
                # the client's muted "thinking" state — going silent here
                # freezes the kiosk.
                async for chunk in self._speak_line(
                    session_id, session, templates.VOICE_DIDNT_HEAR[language]
                ):
                    yield chunk
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

        if not transcript and caption:
            # STT heard nothing in the audio (AGC-quiet first utterance, mic
            # level) but the browser caption transcribed the patient — what
            # streamed on their screen wins over a deaf recording.
            transcript = caption

        if transcript is None:
            async for chunk in self._speak_line(
                session_id, session, templates.VOICE_ERROR[language]
            ):
                yield chunk
            return
        if not transcript:
            # A patient still gathering their thoughts produces an empty
            # turn. On the passive silence fallback, stay silent on the
            # first miss and just keep listening; only prompt after two in
            # a row. An explicit "Done" tap always gets the prompt — the
            # client is muted in "thinking" until reply audio plays.
            session["empty_turns"] = session.get("empty_turns", 0) + 1
            if explicit or session["empty_turns"] >= 2:
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

        # Identity gate first: while unconfirmed, answers (spoken or tapped
        # chips) are classified as yes/no — nothing else runs until the right
        # person is confirmed at the kiosk.
        if session.get("awaiting_identity"):
            async for chunk in self._handle_identity_turn(
                session_id, session, transcript
            ):
                yield chunk
            return

        # Resume gate: continue-vs-start-over decides which session the rest
        # of the call even belongs to.
        if session.get("awaiting_resume"):
            async for chunk in self._handle_resume_turn(
                session_id, session, transcript
            ):
                yield chunk
            return

        # History gate: first-time intake, one question per turn; the triage
        # pipeline starts only after the last answer is stored.
        if session.get("awaiting_history"):
            async for chunk in self._handle_history_turn(
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
    # Spoken resume gate (continue vs start over)
    # ------------------------------------------------------------------

    async def _fire_resume(
        self, session_id: str, session: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        resume_cb: ResumeCallback | None = session.get("resume_cb")
        if resume_cb is None:
            return
        try:
            await resume_cb(payload)
        except Exception:
            logger.exception("resume_cb failed for %s", session_id)

    async def _push_resume_options(
        self, session_id: str, session: dict[str, Any]
    ) -> None:
        """Continue/start-over chips under the spoken resume question. Only
        the unfinished-session variant exists — a finished assessment never
        opens a resume call (the kiosk shows the finished notice instead)."""
        if session.get("resume_status") != "active":
            return
        options_cb: OptionsCallback | None = session.get("options_cb")
        if options_cb is None:
            return
        options = templates.RESUME_OPTIONS.get(
            session["language"], templates.RESUME_OPTIONS["en"]
        )
        try:
            await options_cb({"options": options})
        except Exception:
            logger.exception("options_cb failed for %s", session_id)

    async def _speak_pending_point(
        self, session_id: str, session: dict[str, Any]
    ) -> AsyncIterator[bytes]:
        """Resume the interview at its actual pending point.

        "Continue" on a session that already has turns must re-issue the last
        question (and re-open the measurement card when the engine was
        waiting on a reading) — a fresh "what brings you in today?" greeting
        reads as the assessment starting over, even though the engine state
        was intact all along (live report 2026-07-27, BP-rest return).
        Falls back to the greeting when the interview hasn't started.
        """
        language = session["language"]
        line: str | None = None
        vital: str | None = None
        conn = session.get("db_connection")
        if conn is not None:
            try:
                row = await conn.fetchrow(
                    "SELECT content FROM messages WHERE session_id = $1::uuid"
                    " AND role = 'assistant' ORDER BY created_at DESC LIMIT 1",
                    session_id,
                )
                if row:
                    line = row["content"]
                srow = await conn.fetchrow(
                    "SELECT state FROM screening_sessions WHERE session_id = $1::uuid",
                    session_id,
                )
                if srow:
                    state = srow["state"]
                    if isinstance(state, str):
                        state = json.loads(state)
                    vital = (state or {}).get("awaiting_measurement")
            except Exception:
                logger.exception("pending-point lookup failed for %s", session_id)
                line = None
                vital = None
        if not line:
            line = templates.greeting_line(session.get("patient_name"), language)
        async for chunk in self._speak_line(session_id, session, line):
            yield chunk
        if vital:
            measurement_cb: MeasurementCallback | None = session.get("measurement_cb")
            if measurement_cb is not None:
                try:
                    await measurement_cb({"vital": vital})
                except Exception:
                    logger.exception("measurement_cb failed for %s", session_id)

    async def _gate_backstop(
        self,
        session_id: str,
        session: dict[str, Any],
        kind: str,
        transcript: str,
        regex_verdict: str,
        context: str = "",
    ) -> str:
        """Consult the screening LLM when a regex gate came back unclear.

        Reuses the engine's already-built shared model (no per-call factory);
        without a model (or on any failure) the verdict is "unclear" and the
        caller falls through to today's retry flow. Best-effort audit via the
        engine's store — voice gates run outside the LangGraph turn, so the
        graph_state audit list isn't available here.
        """
        from .nlu_backstop import confirm_gate

        engine = getattr(self.triage_service, "triage_engine", None)
        model = getattr(engine, "_model", None)
        verdict = await confirm_gate(
            model, kind, transcript, session["language"], context=context  # type: ignore[arg-type]
        )
        store = getattr(engine, "_store", None)
        if model is not None and store is not None:
            try:
                await store.write_audit(
                    session_id=session_id,
                    # Gate turns run before the clinical turn counter starts.
                    turn_no=0,
                    entries=[{
                        "call_site": "gate_backstop",
                        "latency_ms": verdict.latency_ms,
                        "ok": verdict.ok,
                        "kind": kind,
                        "regex_verdict": regex_verdict,
                        "llm_verdict": str(verdict),
                    }],
                    model_name=getattr(engine, "_model_label", "screening:unknown"),
                    prompt_version=getattr(engine, "_prompt_version", "v1"),
                    criteria_version_id=None,
                )
            except Exception:
                logger.exception("gate_backstop audit write failed for %s", session_id)
        return str(verdict)

    async def _handle_resume_turn(
        self, session_id: str, session: dict[str, Any], transcript: str
    ) -> AsyncIterator[bytes]:
        """Classify a continue/start-over answer and speak/signal the outcome.

        Runs after the identity gate, so the person is already confirmed.
        Unfinished session: "ทำต่อ" continues in this call (history intake or
        the interview next); "เริ่มใหม่" hands off to the kiosk to retire
        this session and relink fresh. Completed session: a yes/no "start a
        new one?". Unclear twice → kind "decline": the kiosk's on-screen
        buttons stay available — voice never guesses this decision.
        """
        from app.services.screening.nlu_yesno import (
            classify_resume_choice,
            classify_yes_no,
        )

        language = session["language"]
        decision = classify_resume_choice(transcript)
        if decision == "other" and session["resume_status"] == "completed":
            # The done-variant question is a plain yes/no ("start a new one?").
            yn = classify_yes_no(transcript)
            if yn == "yes":
                decision = "start_over"
            elif yn == "no":
                decision = "decline"

        if decision == "other":
            # LLM backstop before burning a retry / falling back to buttons.
            verdict = await self._gate_backstop(
                session_id, session, "resume_choice", transcript, "other",
                context=session.get("resume_status") or "",
            )
            if verdict in ("continue", "start_over"):
                decision = verdict

        if decision == "other":
            session["resume_attempts"] += 1
            if session["resume_attempts"] < MAX_RESUME_RETRIES:
                async for chunk in self._speak_line(
                    session_id, session, templates.RESUME_RETRY[language]
                ):
                    yield chunk
                await self._push_resume_options(session_id, session)
                return
            decision = "decline"

        session["awaiting_resume"] = False

        if decision == "continue":
            await self._clear_options(session_id, session)
            async for chunk in self._speak_line(
                session_id, session, templates.RESUME_ACK_CONTINUE[language]
            ):
                yield chunk
            needs_history = bool(session.get("needs_history"))
            if needs_history:
                # Same call flows straight into the spoken history intake.
                async for chunk in self._start_history_gate(session_id, session):
                    yield chunk
            else:
                # Pick the interview back up at its pending question or
                # measurement — never a fresh greeting mid-assessment.
                async for chunk in self._speak_pending_point(session_id, session):
                    yield chunk
            await self._fire_resume(
                session_id, session,
                {"kind": "continue", "needs_history": needs_history},
            )
            return

        if decision == "start_over":
            # Kiosk retires this session and relinks the VN on a fresh one.
            session["disposed"] = True
            await self._clear_options(session_id, session)
            async for chunk in self._speak_line(
                session_id, session, templates.RESUME_ACK_STARTOVER[language]
            ):
                yield chunk
            await self._fire_resume(session_id, session, {"kind": "start_over"})
            return

        # decline: leave the decision to the on-screen buttons.
        session["disposed"] = True
        await self._clear_options(session_id, session)
        async for chunk in self._speak_line(
            session_id, session, templates.RESUME_ACK_DECLINE[language]
        ):
            yield chunk
        await self._fire_resume(session_id, session, {"kind": "decline"})

    # ------------------------------------------------------------------
    # Spoken VN identity gate
    # ------------------------------------------------------------------

    async def _clear_options(self, session_id: str, session: dict[str, Any]) -> None:
        """Retract quick-reply chips — the next spoken line takes no taps."""
        options_cb: OptionsCallback | None = session.get("options_cb")
        if options_cb is None:
            return
        try:
            await options_cb({"options": []})
        except Exception:
            logger.exception("options clear failed for %s", session_id)

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

        yes → mark confirmed and continue in the same call: the resume
        question (resume calls), the history intake (first-timers), or the
        intake greeting; no → unlink the visit, tell the patient to re-enter
        their VN, and signal the kiosk to end the call; unclear → re-ask up
        to MAX_IDENTITY_RETRIES times, then treat as rejected (never
        interview an unverified identity).
        """
        from app.services.screening.nlu_yesno import classify_yes_no
        from app.services.visit_confirm import NoVisitLinkedError

        language = session["language"]
        decision = classify_yes_no(transcript)
        if decision in ("uncertain", "other"):
            # LLM backstop BEFORE consuming a retry: free-phrased confirms
            # the regex vocabulary misses shouldn't cost the patient a strike.
            verdict = await self._gate_backstop(
                session_id, session, "identity_yesno", transcript, decision,
            )
            if verdict in ("yes", "no"):
                decision = verdict
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

        if decision == "no" and session.get("resume_reconfirm"):
            # Wrong person on a RESUMED session: never unlink or strip the
            # real patient's session — just send this person back to VN entry.
            outcome = None
        else:
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
            if session.get("awaiting_resume"):
                # Resume call: identity is settled, now ask continue vs
                # start over (the kiosk's chooser buttons stay the tap path).
                await self._clear_options(session_id, session)
                ask = templates.resume_ask(
                    session.get("patient_name"), language, session["resume_status"]
                )
                async for chunk in self._speak_line(session_id, session, ask):
                    yield chunk
                await self._push_resume_options(session_id, session)
            elif needs_history:
                # First-time patient: history intake continues in this call.
                async for chunk in self._start_history_gate(session_id, session):
                    yield chunk
            else:
                await self._clear_options(session_id, session)
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

    # ------------------------------------------------------------------
    # Spoken first-time history intake (one question per turn)
    # ------------------------------------------------------------------

    async def _push_history_options(
        self, session_id: str, session: dict[str, Any]
    ) -> None:
        """Suggested-answer chips under the current history question."""
        options_cb: OptionsCallback | None = session.get("options_cb")
        if options_cb is None:
            return
        options = templates.history_options(
            session["history_index"], session["language"]
        )
        try:
            await options_cb({"options": options})
        except Exception:
            logger.exception("history options_cb failed for %s", session_id)

    async def _start_history_gate(
        self, session_id: str, session: dict[str, Any]
    ) -> AsyncIterator[bytes]:
        """Open the intake: intro line, first question, its chips."""
        session["awaiting_history"] = True
        session["history_index"] = 0
        session["history_answers"] = {}
        language = session["language"]
        intro = templates.HISTORY_INTRO[language]
        question = templates.history_question(0, language)
        async for chunk in self._speak_line(
            session_id, session, f"{intro} {question}"
        ):
            yield chunk
        await self._push_history_options(session_id, session)

    async def _handle_history_turn(
        self, session_id: str, session: dict[str, Any], transcript: str
    ) -> AsyncIterator[bytes]:
        """Store one intake answer and ask the next question.

        Answers are free speech or a tapped chip (chip labels are phrases the
        ``history_findings`` keyword mapper understands). After the last
        answer the history is persisted to session metadata + the HIS HN and
        the call flows straight into the symptom interview.
        """
        language = session["language"]
        answer = transcript.strip()
        if not answer:
            async for chunk in self._speak_line(
                session_id, session, templates.HISTORY_RETRY[language]
            ):
                yield chunk
            await self._push_history_options(session_id, session)
            return

        index = session["history_index"]
        field = templates.HISTORY_QUESTIONS[index]["field"]
        session["history_answers"][field] = answer

        index += 1
        if index < len(templates.HISTORY_QUESTIONS):
            session["history_index"] = index
            question = templates.history_question(index, language)
            async for chunk in self._speak_line(session_id, session, question):
                yield chunk
            await self._push_history_options(session_id, session)
            return

        session["awaiting_history"] = False
        session["needs_history"] = False
        try:
            await self._store_history(session_id, session)
        except Exception:
            # The interview must not stall on a persistence hiccup; the nurse
            # still sees conversational answers in the transcript.
            logger.exception("history intake persist failed for %s", session_id)
        await self._clear_options(session_id, session)
        async for chunk in self._speak_line(
            session_id, session, templates.HISTORY_DONE_ASK[language]
        ):
            yield chunk

    async def _store_history(self, session_id: str, session: dict[str, Any]) -> None:
        from app.services.patient_history import store_patient_history

        his_adapter = (
            self.his_adapter_getter() if self.his_adapter_getter is not None else None
        )
        answers = dict(session.get("history_answers") or {})
        db_pool = session.get("db_pool")
        if db_pool is not None:
            async with db_pool.acquire() as connection:
                await store_patient_history(
                    connection, session_id, answers, his_adapter=his_adapter
                )
                return
        await store_patient_history(
            session["db_connection"], session_id, answers, his_adapter=his_adapter
        )

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
        # Vowel timeline for avatar lip sync — sent before the line's audio
        # so the client can anchor it to the first scheduled chunk.
        viseme_cb: VisemeCallback | None = session.get("viseme_cb")
        if viseme_cb is not None and audio:
            duration_s = len(audio) / (OUTPUT_SAMPLE_RATE * 2)
            try:
                await viseme_cb(
                    {
                        "visemes": build_viseme_track(
                            text, duration_s, session["language"]
                        ),
                        "duration": round(duration_s, 3),
                    }
                )
            except Exception:
                logger.debug("viseme_cb failed (likely client closed)")
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
