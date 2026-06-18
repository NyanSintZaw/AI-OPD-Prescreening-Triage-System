"""Gemini Live API voice-call lifecycle manager.

Bridges a frontend WebSocket to ADK's bidirectional ``Runner.run_live``
streaming. Per call:

Debug knobs:
    LIVE_DEBUG_EVENTS=true  Dumps every ADK live event's interesting
                            attributes to the logger. Use to discover
                            the exact shape of new event types (tool
                            calls, transcripts, audio frames) when
                            something downstream isn't firing.


* Validates the hotline ``session_id`` against Postgres.
* Opens a ``LiveRequestQueue`` and binds it to the live ADK runner.
* Sends a kickoff prompt so the agent greets the caller immediately
  (Gemini Live waits for input before producing output otherwise).
* Streams audio bytes back to the caller as the agent speaks.
* Surfaces live caller / agent transcripts and emergency tool calls
  through user-supplied callbacks so the WebSocket route can forward
  them to the frontend.
* Persists the accumulated caller transcript into the normal triage
  assessment pipeline so DB rows and the staff summary stay consistent
  with text mode.

The Gemini Live API itself emits audio + transcription events; we do
not run STT ourselves. The text-mode chat path is left untouched —
this service only adds a new entry point for voice.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import asyncpg
from google.adk.agents import LiveRequestQueue
from google.genai import types as genai_types

from app.services.ai.live_audio import (
    _DEBUG_AUDIO,
    _DEBUG_EVENTS,
    _INPUT_AUDIO_MIME_TYPE,
)
from app.services.ai.live_events import (
    _smart_append,
    _strip_meta_markers,
    extract_response_payload,
    log_event_shape,
)
from app.services.ai.live_runner import HotlineADKLiveRunner
from app.services.ai.triage_payloads import _triage_result_to_payload
from app.services.triage_service import TriageService

logger = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")
_YES_PHRASES = ("yes", "yeah", "yep", "sure", "ok", "okay", "please")
_YES_THAI_PHRASES = (
    "ใช่",
    "ใช่ค่ะ",
    "ใช่ครับ",
    "ได้",
    "ได้ค่ะ",
    "ได้ครับ",
    "ตกลง",
    "ต้องการ",
    "ติดต่อกลับ",
    "โทรกลับ",
    "โทรมา",
    "โทรได้",
    "เอาค่ะ",
    "เอาครับ",
)
_NO_PHRASES = ("no", "nope", "not now", "don't", "do not")
_NO_THAI_PHRASES = (
    "ไม่ต้อง",
    "ไม่ต้องการ",
    "ไม่เอา",
    "ไม่สะดวก",
    "ไม่เป็นไร",
    "ยังไม่",
    "ไม่ใช่",
    "ไม่",
)
_CONTACT_GOODBYE_DELAY_SECONDS = 1.2
_CONTACT_REPLY_WAIT_SECONDS = 3.0
_CONTACT_REPLY_POLL_SECONDS = 0.1

# Transcript callback: receives ("user"|"agent", text). Called from the
# live event loop so should be cheap and non-blocking — typically just
# pushes a JSON frame onto the WebSocket.
TranscriptCallback = Callable[[str, str], Awaitable[None]]


# Emergency callback: receives a payload dict shaped like the
# ChatEmergencyOut schema (severity / alert_message / detected_symptoms /
# level / department_name). Used by the WS route to push a banner trigger
# to the frontend without waiting for disconnect.
EmergencyCallback = Callable[[dict[str, Any]], Awaitable[None]]

# Assessment callback: receives the same payload shape as the REST
# ``/sessions/{id}/chat`` response once triage is complete. The WS
# route forwards it to the browser so the patient sees their result
# and the frontend can auto-end the call.
AssessmentCallback = Callable[[dict[str, Any]], Awaitable[None]]


def _kickoff_prompt(language: str) -> str:
    """Build the synthetic content the live runner sends into its own queue
    on connect.

    Gemini Live API only generates output after it receives a user turn,
    so without this kickoff the caller hears silence until they speak.
    We keep the text deliberately short and natural: the agent's
    system instruction already tells it to greet first, this content
    just gives the live API a user turn to respond to. Wrapping it in
    brackets makes clear it's a stage direction rather than a literal
    caller utterance so the agent doesn't try to echo it back.
    """

    lang_code = language if language in {"en", "th"} else "en"
    lang_name = "English" if lang_code == "en" else "Thai"
    hospital_name = (
        "โรงพยาบาลแม่ฟ้าหลวง" if lang_code == "th"
        else "Mae Fah Luang Hospital"
    )
    return (
        "[MODE: voice — reply in short spoken sentences, no formatting]\n"
        f"[LANG: {lang_code} — reply EXCLUSIVELY in {lang_name}. "
        "This is the session language and it does not change.]\n"
        f"[CALL_START] The caller has just connected. Greet them warmly in {lang_name} "
        f"as the {hospital_name} hotline AI nurse and ask how you can help "
        "them today. Keep it to one or two short spoken sentences."
    )


def _normalize_language(language: str) -> str:
    return language if language in {"en", "th"} else "en"


def _contains_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def _has_yes(text: str) -> bool:
    if any(phrase in text for phrase in ("ไม่ใช่",)):
        thai_text = text.replace("ไม่ใช่", "")
    else:
        thai_text = text
    return _contains_phrase(text, _YES_PHRASES) or any(
        phrase in thai_text for phrase in _YES_THAI_PHRASES
    )


def _has_no(text: str) -> bool:
    return _contains_phrase(text, _NO_PHRASES) or any(
        phrase in text for phrase in _NO_THAI_PHRASES
    )


class LiveVoiceService:
    """Per-session orchestrator for live voice calls.

    Holds a single :class:`HotlineADKLiveRunner` and an in-memory map of
    active sessions. Each entry tracks the live queue (so we can push
    inbound audio), the running transcript (so we can replay it into
    the text pipeline for DB persistence),
    the mute flag, the caller's language, the DB pool used for short
    persistence writes, and the user-supplied transcript /
    emergency callbacks.
    """

    def __init__(self, triage_service: TriageService) -> None:
        self.triage_service: TriageService = triage_service
        self.live_runner: HotlineADKLiveRunner = HotlineADKLiveRunner()
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
    ) -> None:
        """Validate the session, prep the ADK side, register state.

        Raises ``ValueError`` if the session is unknown — callers
        (the WebSocket route) should translate that into a 1008 close.

        ``transcript_callback`` and ``emergency_callback`` are invoked
        from the live event loop. They run inside the same async task
        that drives :meth:`run_live_pipeline`, so they should be cheap
        (typically a single ``websocket.send_json``).
        """

        row = await db_connection.fetchrow(
            "SELECT id FROM sessions WHERE id = $1", session_id
        )
        if row is None:
            raise ValueError("Session not found")

        await self.live_runner.ensure_live_session(session_id, language)

        queue = LiveRequestQueue()
        self._sessions[session_id] = {
            "queue": queue,
            "transcript": [],         # accumulates caller speech (input transcription)
            "agent_transcript": [],   # accumulates agent speech (output transcription)
            "muted": False,
            "activity_open": False,
            "language": language,
            "db_connection": db_connection,
            "db_pool": db_pool,
            "transcript_cb": transcript_callback,
            "emergency_cb": emergency_callback,
            "assessment_cb": assessment_callback,
            "classification": {},
            "contact_preference": {},
            "contact_flow": "idle",
            "contact_transcript_index": 0,
            "assessment_finalized": False,
            "pipeline_failed": False,
            # Tracks whether we have already replayed the live transcript
            # into ``process_chat`` for a given trigger so we don't
            # double-fire notifications on the same emergency.
            "emergency_announced": False,
            # Last severity emitted to the emergency callback. Lets us
            # avoid re-emitting the same banner on every subsequent tool
            # event during an active emergency.
            "last_emergency_severity": None,
            # Audio-flow audit counters (populated only when
            # LIVE_DEBUG_AUDIO is on). One-shot ``first_*_logged`` flags
            # gate the structural-shape log line; the running counts
            # log every 50th chunk so a quiet steady state stays quiet.
            "audio_in_chunks": 0,
            "audio_in_bytes": 0,
            "audio_out_chunks": 0,
            "audio_out_bytes": 0,
            "first_audio_in_logged": False,
            "first_audio_out_logged": False,
        }

        # Kickoff goes into the queue SYNCHRONOUSLY before we return from
        # connect(). This is the critical ordering invariant: the
        # frontend's first microphone blobs only start arriving after
        # the WebSocket route schedules its pump tasks, so by enqueuing
        # the kickoff content here we guarantee it sits at the head of
        # ADK's LiveRequestQueue and gets forwarded to Gemini Live with
        # ``turn_complete=True`` (ADK's send_content sets that flag for
        # non-3.1 models) before any user audio. Without this ordering
        # the inbound mic stream looks like a fresh user turn and
        # interrupts the greeting before it can play.
        try:
            kickoff_content = genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=_kickoff_prompt(language))],
            )
            queue.send_content(content=kickoff_content)
            logger.info("Live kickoff queued for %s", session_id)
        except Exception:  # noqa: BLE001 — kickoff failure shouldn't tear the call down
            logger.exception("Live kickoff failed for %s", session_id)

        logger.info(
            "Live voice session connected: %s language=%s", session_id, language
        )

    async def disconnect(self, session_id: str) -> None:
        """Close the live queue and flush the call into the text pipeline.

        Idempotent: silently no-ops if the session was never registered or
        has already been cleaned up. Errors during the final ``process_chat``
        flush are logged but never raised — they must not block WebSocket
        teardown.
        """

        session = self._sessions.pop(session_id, None)
        if session is None:
            return

        queue: LiveRequestQueue = session["queue"]
        try:
            queue.close()
        except Exception:  # noqa: BLE001 - defensive against ADK API drift
            logger.exception("Failed to close LiveRequestQueue for %s", session_id)

        # Final assessment sync — if the call ended before the auto-complete
        # path fired (user hung up early, network drop, etc.), still persist
        # whatever classification we captured from tool responses.
        if (
            not session.get("assessment_finalized")
            and session.get("contact_flow") in {"idle", "done"}
        ):
            await self._complete_call_assessment(session_id, session=session)

        logger.info("Live voice session disconnected: %s", session_id)

    def should_keep_pipeline_open(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if session.get("pipeline_failed"):
            return False
        if session.get("assessment_finalized"):
            return False
        return session.get("contact_flow") in {
            "idle",
            "awaiting_consent",
            "awaiting_phone",
        }

    # ------------------------------------------------------------------
    # Inbound audio (browser → Gemini Live)
    # ------------------------------------------------------------------

    async def send_audio(self, session_id: str, audio_chunk: bytes) -> None:
        """Forward a microphone chunk to the live queue.

        Drops the chunk silently if the call is muted — the pipeline
        stays open so the agent's existing speech / queued response
        continues unaffected; only fresh microphone input is suppressed.
        """

        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        if session["muted"]:
            return

        queue: LiveRequestQueue = session["queue"]
        if not session.get("activity_open"):
            queue.send_activity_start()
            session["activity_open"] = True
            logger.info("Session %s user activity started", session_id)

        blob = genai_types.Blob(
            data=audio_chunk,
            mime_type=_INPUT_AUDIO_MIME_TYPE,
        )
        # LiveRequestQueue.send_realtime is the standard channel for
        # real-time PCM blobs and is intentionally synchronous (it just
        # puts an item onto an internal asyncio.Queue under the hood).
        queue.send_realtime(blob)

        if _DEBUG_AUDIO:
            session["audio_in_chunks"] += 1
            session["audio_in_bytes"] += len(audio_chunk)
            if not session["first_audio_in_logged"]:
                session["first_audio_in_logged"] = True
                logger.info(
                    "[audio-audit %s] client → Gemini: first chunk %d bytes "
                    "mime=%s (expected 1280 bytes = 40ms @ 16kHz mono Int16)",
                    session_id,
                    len(audio_chunk),
                    _INPUT_AUDIO_MIME_TYPE,
                )
            elif session["audio_in_chunks"] % 50 == 0:
                logger.info(
                    "[audio-audit %s] client → Gemini: %d chunks, %d bytes total",
                    session_id,
                    session["audio_in_chunks"],
                    session["audio_in_bytes"],
                )

    def set_mute(self, session_id: str, muted: bool) -> None:
        """Toggle the server-side microphone gate.

        Muting only stops forwarding fresh microphone chunks. The Send
        button calls :meth:`end_user_turn` to close the activity and
        trigger the model response.
        """

        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        session["muted"] = muted
        logger.info("Session %s mute=%s", session_id, muted)

    def end_user_turn(self, session_id: str) -> None:
        """Tell Gemini Live the caller finished speaking."""

        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        session["muted"] = True
        if not session.get("activity_open"):
            logger.info(
                "Session %s user turn ended with no open activity", session_id
            )
            return
        try:
            session["queue"].send_activity_end()
            session["activity_open"] = False
            logger.info("Session %s user turn ended (activity_end)", session_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to end user turn for %s", session_id)

    # ------------------------------------------------------------------
    # Outbound pipeline (Gemini Live → browser)
    # ------------------------------------------------------------------

    async def run_live_pipeline(self, session_id: str) -> AsyncIterator[bytes]:
        """Drive ``Runner.run_live`` and yield audio chunks for the WebSocket.

        For each event from ADK:
        * If it carries inline audio, yield the raw bytes.
        * If it carries an input transcription (caller speech), append
          to the running transcript and forward to the transcript
          callback.
        * If it carries an output transcription (agent speech), record
          it and forward to the transcript callback.
        * If it carries a ``function_response`` with ``classified: True``
          and the level is 1 or 2, fire the emergency callback and
          immediately replay the transcript into the text pipeline so
          the notifier fires without waiting for the call to end (real
          emergencies cannot wait).
        """

        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")

        runner = await self.live_runner.get_live_session_handler(
            session_id, session["language"]
        )
        run_config = self.live_runner.build_run_config(session["language"])
        queue: LiveRequestQueue = session["queue"]

        try:
            async for event in runner.run_live(
                user_id=session_id,
                session_id=session_id,
                live_request_queue=queue,
                run_config=run_config,
            ):
                async for audio_chunk in self._handle_live_event(session_id, event):
                    yield audio_chunk
        except asyncio.CancelledError:
            # WebSocket route cancels the pipeline task on disconnect;
            # let the cancel propagate after we clean up.
            raise
        except Exception:
            session["pipeline_failed"] = True
            logger.exception(
                "Live pipeline crashed for session %s", session_id
            )
            return

    async def _handle_live_event(
        self, session_id: str, event: Any
    ) -> AsyncIterator[bytes]:
        """Pull audio + transcripts + tool calls out of a single ADK event.

        Uses ADK's own ``get_function_responses()`` accessor (rather than
        hand-rolling part inspection) so we stay aligned with whatever
        shape ADK exposes — past versions have shifted between
        ``part.function_response.response`` and ``part.function_response``
        directly carrying the dict, and the accessor abstracts that.
        """

        session = self._sessions.get(session_id)
        if session is None:
            return

        transcript_cb: TranscriptCallback | None = session.get("transcript_cb")
        emergency_cb: EmergencyCallback | None = session.get("emergency_cb")

        if _DEBUG_EVENTS:
            log_event_shape(session_id, event)

        # 1) Audio bytes — Gemini Live wraps PCM chunks in event.content.parts
        #    as inline_data with mime_type "audio/pcm;rate=24000".
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if inline_data is not None:
                data = getattr(inline_data, "data", None)
                if isinstance(data, (bytes, bytearray)) and data:
                    if _DEBUG_AUDIO:
                        session["audio_out_chunks"] += 1
                        session["audio_out_bytes"] += len(data)
                        if not session["first_audio_out_logged"]:
                            session["first_audio_out_logged"] = True
                            mime = (
                                getattr(inline_data, "mime_type", None)
                                or "audio/pcm;rate=24000?"
                            )
                            logger.info(
                                "[audio-audit %s] Gemini → client: first chunk "
                                "%d bytes mime=%s (expected audio/pcm;rate=24000)",
                                session_id,
                                len(data),
                                mime,
                            )
                        elif session["audio_out_chunks"] % 50 == 0:
                            logger.info(
                                "[audio-audit %s] Gemini → client: %d chunks, "
                                "%d bytes total",
                                session_id,
                                session["audio_out_chunks"],
                                session["audio_out_bytes"],
                            )
                    yield bytes(data)

        # 2) Tool-call outputs — use ADK's official accessor. Each
        #    FunctionResponse carries a ``response`` dict (when ADK
        #    constructs the part) OR the response may already be a dict
        #    we passed back from the FunctionTool wrapper. Handle both.
        get_responses = getattr(event, "get_function_responses", None)
        if callable(get_responses):
            for func_response in get_responses() or []:
                payload = extract_response_payload(func_response)
                if payload is not None:
                    await self._handle_tool_response(
                        session_id, payload, emergency_cb
                    )

        # 3) Live transcriptions — Gemini Live emits these as top-level
        #    attributes on the event. Both fields are optional; check
        #    each defensively. We route through ``_smart_append`` so the
        #    accumulated text on the session AND the per-event delta
        #    forwarded to the WebSocket are both deduped against
        #    Gemini Live's interim/final/snapshot stream behaviour.
        input_tx = getattr(event, "input_transcription", None)
        if input_tx is not None:
            text = getattr(input_tx, "text", None)
            if text:
                delta = _smart_append(session["transcript"], str(text))
                if delta and transcript_cb is not None:
                    try:
                        await transcript_cb("user", delta)
                    except Exception:
                        logger.exception(
                            "transcript_cb(user) failed for %s", session_id
                        )

        output_tx = getattr(event, "output_transcription", None)
        if output_tx is not None:
            text = getattr(output_tx, "text", None)
            if text:
                # Strip any echoed `[MODE: ...]` / `[LANG: ...]` / `[CALL_START]`
                # markers BEFORE deduplication so the caption shown to the
                # caller stays clean even if the model momentarily echoes
                # our kickoff envelope.
                cleaned = _strip_meta_markers(str(text))
                if not cleaned:
                    cleaned = ""
                delta = _smart_append(session["agent_transcript"], cleaned) if cleaned else None
                if delta and transcript_cb is not None:
                    try:
                        await transcript_cb("agent", delta)
                    except Exception:
                        logger.exception(
                            "transcript_cb(agent) failed for %s", session_id
                        )

    async def _handle_tool_response(
        self,
        session_id: str,
        payload: dict[str, Any],
        emergency_cb: EmergencyCallback | None,
    ) -> None:
        """React to a single function_response payload from the live event stream.

        Handles both classification results (from classify_triage_level) and
        contact preference results (from record_contact_preference). The
        contact flow is driven entirely by tool calls from the live model —
        no side-channel transcript polling.
        """

        session = self._sessions.get(session_id)
        if session is None:
            return

        classified = payload.get("classified") is True
        level = payload.get("level") if isinstance(payload.get("level"), int) else None

        if classified:
            session["classification"] = payload

        if classified and level in (1, 2) and not session["emergency_announced"]:
            session["emergency_announced"] = True
            if emergency_cb is not None:
                banner_payload: dict[str, Any] = {
                    "severity": "emergency",
                    "level": level,
                    "alert_message": (
                        payload.get("key_reason")
                        or "Emergency triage match"
                    ),
                    "department_code": payload.get("department_code"),
                    "color": payload.get("color"),
                    "label": payload.get("label"),
                    "detected_symptoms": (
                        [payload["symptoms_summary"]]
                        if isinstance(payload.get("symptoms_summary"), str)
                        else []
                    ),
                }
                session["last_emergency_severity"] = "emergency"
                try:
                    await emergency_cb(banner_payload)
                except Exception:
                    logger.exception(
                        "emergency_cb (classify) failed for %s", session_id
                    )

        if classified and session.get("contact_flow") == "idle":
            session["contact_flow"] = "awaiting_consent"
            session["contact_transcript_index"] = len(session["transcript"])
            session["contact_preference"] = {"requested": None, "phone": None}

        # --- Contact preference tool response handling ---
        # The live model calls record_contact_preference directly; we react
        # to its result here instead of polling transcripts on the side.
        contact_recorded = payload.get("contact_preference_recorded") is True
        if contact_recorded and session.get("contact_flow") in {
            "awaiting_consent",
            "awaiting_phone",
        }:
            preference = self._contact_preference_from_payload(payload)
            session["contact_preference"] = preference
            requested = payload.get("requested")
            phone = (payload.get("phone_number") or "").strip()
            needs_followup = payload.get("needs_followup") is True

            logger.info(
                "Contact preference recorded for %s: requested=%s phone=%s "
                "needs_followup=%s flow=%s",
                session_id,
                requested,
                bool(phone),
                needs_followup,
                session.get("contact_flow"),
            )

            if needs_followup:
                # Model will ask the follow-up naturally (phone number or
                # clarification). Update flow state so we know what to
                # expect on the next tool call.
                if requested is True:
                    session["contact_flow"] = "awaiting_phone"
                # else: stay in awaiting_consent for clarification
            else:
                # Final preference recorded — proceed to assessment.
                session["contact_flow"] = "done"
                asyncio.create_task(
                    self._finish_contact_flow(session_id, session)
                )

    # ------------------------------------------------------------------
    # Assessment completion + auto-end
    # ------------------------------------------------------------------

    def _contact_reply_text(self, session: dict[str, Any]) -> str:
        chunks = session.get("transcript", [])
        start = int(session.get("contact_transcript_index") or 0)
        return " ".join(str(chunk).strip() for chunk in chunks[start:] if chunk).strip()

    async def _wait_for_contact_reply_text(self, session: dict[str, Any]) -> str:
        deadline = asyncio.get_running_loop().time() + _CONTACT_REPLY_WAIT_SECONDS
        while True:
            text = self._contact_reply_text(session)
            if text:
                return text
            if asyncio.get_running_loop().time() >= deadline:
                return ""
            await asyncio.sleep(_CONTACT_REPLY_POLL_SECONDS)

    def _send_agent_instruction(self, session: dict[str, Any], text: str) -> None:
        lang_code = _normalize_language(str(session.get("language", "en")))
        lang_name = "English" if lang_code == "en" else "Thai"
        content = genai_types.Content(
            role="user",
            parts=[
                genai_types.Part(
                    text=(
                        "[SYSTEM_ACTION]\n"
                        "[MODE: voice — reply in short spoken sentences, no formatting]\n"
                        f"[LANG: {lang_code} — reply EXCLUSIVELY in {lang_name}.]\n"
                        f"{text}"
                    )
                )
            ],
        )
        session["queue"].send_content(content=content)

    def _contact_goodbye_prompt(self, session: dict[str, Any]) -> str:
        preference = session.get("contact_preference") or {}
        lang = _normalize_language(str(session.get("language", "en")))
        if preference.get("requested"):
            return (
                "Thank the patient, say the hospital will contact them at that number, "
                "tell them their triage result and patient ID will be shown now, and say goodbye. "
                "Use one short natural sentence."
                if lang == "en"
                else "ขอบคุณผู้ป่วย แจ้งว่าโรงพยาบาลจะติดต่อกลับตามหมายเลขนั้น บอกว่าจะแสดงผลคัดกรองและรหัสผู้ป่วยตอนนี้ แล้วกล่าวลา ให้พูดเป็นประโยคสั้น ๆ เป็นธรรมชาติหนึ่งประโยค"
            )
        return (
            "Acknowledge that they do not want hospital contact, tell them their triage result "
            "and patient ID will be shown now, and say goodbye. Use one short natural sentence."
            if lang == "en"
            else "รับทราบว่าผู้ป่วยไม่ต้องการให้โรงพยาบาลติดต่อกลับ บอกว่าจะแสดงผลคัดกรองและรหัสผู้ป่วยตอนนี้ แล้วกล่าวลา ให้พูดเป็นประโยคสั้น ๆ เป็นธรรมชาติหนึ่งประโยค"
        )

    def _phone_followup_question(self, session: dict[str, Any]) -> str:
        lang = _normalize_language(str(session.get("language", "en")))
        return (
            "Please tell me your phone number so the hospital can contact you."
            if lang == "en"
            else "กรุณาบอกหมายเลขโทรศัพท์ของคุณ เพื่อให้โรงพยาบาลติดต่อกลับได้ค่ะ"
        )

    def _contact_clarification_question(self, session: dict[str, Any]) -> str:
        lang = _normalize_language(str(session.get("language", "en")))
        return (
            "Would you like the hospital to contact you?"
            if lang == "en"
            else "คุณต้องการให้โรงพยาบาลติดต่อกลับไหมคะ"
        )

    def _speak_contact_agent_reply(
        self,
        session: dict[str, Any],
        reply: str,
    ) -> None:
        text = reply.strip()
        if not text:
            return
        lang = _normalize_language(str(session.get("language", "en")))
        prompt = (
            f"Say this exact message to the patient, naturally and without adding anything: {text}"
            if lang == "en"
            else f"พูดข้อความนี้กับผู้ป่วยตามนี้อย่างเป็นธรรมชาติ โดยไม่เพิ่มข้อความอื่น: {text}"
        )
        self._send_agent_instruction(session, prompt)

    async def _finish_contact_flow(
        self,
        session_id: str,
        session: dict[str, Any],
        *,
        goodbye_reply: str = "",
    ) -> None:
        if session.get("contact_completion_started"):
            return
        session["contact_completion_started"] = True
        await self._persist_contact_preference(session_id, session)
        try:
            if goodbye_reply.strip():
                self._speak_contact_agent_reply(session, goodbye_reply)
            else:
                self._send_agent_instruction(session, self._contact_goodbye_prompt(session))
        except Exception:
            logger.exception("Failed to queue contact goodbye for %s", session_id)
        await asyncio.sleep(_CONTACT_GOODBYE_DELAY_SECONDS)
        await self._complete_call_assessment(session_id)

    def _contact_preference_from_payload(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "requested": payload.get("requested"),
            "phone": payload.get("phone_number"),
            "preferred_time": payload.get("preferred_time"),
            "relation": payload.get("relation"),
            "confidence": payload.get("confidence"),
            "needs_followup": payload.get("needs_followup"),
            "followup_question": payload.get("followup_question"),
        }

    def _contact_preference_from_live_text(
        self,
        flow: str,
        text: str,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        phone_match = _PHONE_RE.search(text)
        phone_number = phone_match.group(0).strip() if phone_match else None

        if flow == "awaiting_phone":
            return {
                "requested": True,
                "phone_number": phone_number,
                "preferred_time": None,
                "relation": None,
                "confidence": 1.0 if phone_number else 0.0,
                "needs_followup": phone_number is None,
                "followup_question": (
                    None if phone_number else self._phone_followup_question(session)
                ),
            }

        wants_contact = _has_yes(text)
        declines_contact = _has_no(text)
        if declines_contact and not wants_contact:
            return {
                "requested": False,
                "phone_number": None,
                "preferred_time": None,
                "relation": None,
                "confidence": 1.0,
                "needs_followup": False,
                "followup_question": None,
            }

        if wants_contact:
            return {
                "requested": True,
                "phone_number": phone_number,
                "preferred_time": None,
                "relation": None,
                "confidence": 1.0,
                "needs_followup": phone_number is None,
                "followup_question": (
                    None if phone_number else self._phone_followup_question(session)
                ),
            }

        return {
            "requested": None,
            "phone_number": None,
            "preferred_time": None,
            "relation": None,
            "confidence": 0.0,
            "needs_followup": True,
            "followup_question": self._contact_clarification_question(session),
        }

    async def _persist_contact_preference(
        self,
        session_id: str,
        session: dict[str, Any],
    ) -> None:
        preference = session.get("contact_preference") or {}
        try:
            db_pool: asyncpg.Pool | None = session.get("db_pool")
            if db_pool is not None:
                async with db_pool.acquire() as connection:
                    await self._write_contact_preference(connection, session_id, preference)
            else:
                await self._write_contact_preference(
                    session["db_connection"], session_id, preference
                )
        except Exception:
            logger.exception("Failed to persist contact preference for %s", session_id)

    async def _write_contact_preference(
        self,
        connection: asyncpg.Connection,
        session_id: str,
        preference: dict[str, Any],
    ) -> None:
        await connection.execute(
            """
            UPDATE sessions
            SET metadata = metadata || $2::jsonb
            WHERE id = $1
            """,
            session_id,
            {
                "patient_contact_requested": preference.get("requested"),
                "patient_contact_phone": preference.get("phone"),
                "patient_contact_preferred_time": preference.get("preferred_time"),
                "patient_contact_relation": preference.get("relation"),
                "patient_contact_updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _handle_contact_preference_turn(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.get("assessment_finalized"):
            return
        if session.get("contact_turn_handler_running"):
            return
        session["contact_turn_handler_running"] = True
        try:
            await self._handle_contact_preference_turn_inner(session_id, session)
        finally:
            session["contact_turn_handler_running"] = False

    async def _handle_contact_preference_turn_inner(
        self,
        session_id: str,
        session: dict[str, Any],
    ) -> None:
        if session.get("assessment_finalized"):
            return

        flow = session.get("contact_flow")
        text = await self._wait_for_contact_reply_text(session)
        if not text:
            logger.info(
                "No contact preference transcript received for %s while flow=%s",
                session_id,
                flow,
            )
            return

        logger.debug(
            "Live contact preference turn: %s flow=%s text=%r",
            session_id,
            flow,
            text,
        )

        payload = self._contact_preference_from_live_text(str(flow), text, session)
        phone_number = str(payload.get("phone_number") or "").strip()
        session["contact_preference"] = self._contact_preference_from_payload(payload)
        requested = payload.get("requested")
        needs_followup = payload.get("needs_followup") is True
        followup_question = str(payload.get("followup_question") or "").strip()

        if requested is True and not phone_number:
            session["contact_preference"]["needs_followup"] = True
            session["contact_flow"] = "awaiting_phone"
            session["contact_transcript_index"] = len(session["transcript"])
            self._speak_contact_agent_reply(
                session,
                self._phone_followup_question(session),
            )
            return

        if needs_followup:
            session["contact_flow"] = "awaiting_consent"
            session["contact_transcript_index"] = len(session["transcript"])
            clarification = followup_question or self._contact_clarification_question(session)
            self._speak_contact_agent_reply(
                session,
                clarification,
            )
            return

        session["contact_flow"] = "done"
        asyncio.create_task(
            self._finish_contact_flow(session_id, session)
        )

    async def _complete_call_assessment(
        self,
        session_id: str,
        *,
        session: dict[str, Any] | None = None,
    ) -> None:
        """Persist the final assessment and notify patient + staff.

        Idempotent — safe to call from tool handlers and disconnect cleanup.
        """

        if session is None:
            session = self._sessions.get(session_id)
        if session is None or session.get("assessment_finalized"):
            return

        if session.get("contact_flow") not in {"idle", "done"}:
            logger.info(
                "Deferring live assessment completion for %s while contact_flow=%s",
                session_id,
                session.get("contact_flow"),
            )
            return

        classification: dict[str, Any] = session.get("classification") or {}
        if not classification.get("classified"):
            return

        session["assessment_finalized"] = True

        transcript_chunks: list[str] = session["transcript"]
        full_text = " ".join(
            chunk.strip() for chunk in transcript_chunks if chunk
        ).strip()
        agent_reply = " ".join(
            chunk.strip() for chunk in session.get("agent_transcript", []) if chunk
        ).strip()

        try:
            db_pool: asyncpg.Pool | None = session.get("db_pool")
            if db_pool is not None:
                async with db_pool.acquire() as connection:
                    result, _ = await self.triage_service.finalize_live_assessment(
                        connection=connection,
                        session_id=session_id,
                        language=session["language"],
                        input_mode="voice",
                        content=full_text or "[voice call]",
                        classification=classification,
                        contact=session.get("contact_preference") or {},
                        reply=agent_reply or None,
                    )
            else:
                result, _ = await self.triage_service.finalize_live_assessment(
                    connection=session["db_connection"],
                    session_id=session_id,
                    language=session["language"],
                    input_mode="voice",
                    content=full_text or "[voice call]",
                    classification=classification,
                    contact=session.get("contact_preference") or {},
                    reply=agent_reply or None,
                )
        except Exception:
            logger.exception(
                "Failed to finalize live assessment for %s", session_id
            )
            session["assessment_finalized"] = False
            return

        payload = _triage_result_to_payload(result)
        payload["auto_end"] = True

        assessment_cb: AssessmentCallback | None = session.get("assessment_cb")
        if assessment_cb is not None:
            try:
                await assessment_cb(payload)
            except Exception:
                logger.exception(
                    "assessment_cb failed for %s", session_id
                )

        logger.info(
            "Live assessment complete for %s severity=%s alert_sent=%s",
            session_id,
            result.severity_level,
            result.alert_sent,
        )

    # ------------------------------------------------------------------
    # Mid-call DB sync
    # ------------------------------------------------------------------

    async def _trigger_emergency_check(self, session_id: str) -> None:
        """Replay the live transcript into the text pipeline NOW.

        Legacy helper retained as a no-op compatibility path. Emergency
        cases now finalize through the normal assessment flow.
        """

        return
