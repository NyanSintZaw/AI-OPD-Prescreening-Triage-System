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
* Persists the accumulated caller transcript into the text triage
  pipeline so DB rows and the mock notifier still fire — both
  mid-call (on emergency detection) and on final disconnect.

The Gemini Live API itself emits audio + transcription events; we do
not run STT ourselves. The text-mode chat path is left untouched —
this service only adds a new entry point for voice.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import asyncpg
from google.adk.agents import LiveRequestQueue
from google.genai import types as genai_types

from app.services.adk_agent import HotlineADKLiveRunner, _strip_meta_markers
from app.services.triage_service import TriageService, _triage_result_to_payload

logger = logging.getLogger(__name__)

# Toggle verbose event dumping per call via the env. Useful when wiring
# in a new ADK version where event shapes (function_response paths,
# transcription attribute names) might have shifted.
_DEBUG_EVENTS: bool = os.environ.get("LIVE_DEBUG_EVENTS", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Lightweight audio-flow audit: logs first inbound + outbound chunk
# shapes per session (counts, byte sizes, mime types). Cheap (a handful
# of one-off log lines per call), the single source of truth for
# verifying the server side of the PCM pipeline. Pair with the
# frontend's VITE_VOICE_DEBUG flag to get a complete bidirectional
# audit trail without touching code.
_DEBUG_AUDIO: bool = os.environ.get("LIVE_DEBUG_AUDIO", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


# Gemini Live API expects raw PCM at 16 kHz mono for input. The MIME
# type carries the sample rate so the API can decode without a WAV
# wrapper. Output audio comes back as PCM at 24 kHz mono (Gemini's
# default TTS sample rate) — the frontend should resample as needed.
_INPUT_AUDIO_MIME_TYPE: str = "audio/pcm;rate=16000"

# Kickoff is enqueued synchronously in ``connect()`` so it lands at the
# very front of the LiveRequestQueue. ADK's ``_send_to_model`` loop
# drains the queue in FIFO order, so an immediate send guarantees the
# kickoff content is processed BEFORE the frontend's first microphone
# blobs reach the upstream model. Delaying it (which an earlier
# revision did) caused mic audio to arrive first and interrupted the
# greeting turn before it could play.

# Heuristic safety net. If the function_response detection misses the
# ``contact_collected`` tool result (which happens when ADK's live
# event shapes drift between minor versions), we still want to fire
# the mock notifier when the agent verbally confirms dispatch. These
# phrases run case-insensitive substring matching over the accumulated
# agent transcript.
_DISPATCH_COMPLETION_PHRASES_EN: tuple[str, ...] = (
    "dispatching help",
    "ambulance is on",
    "ambulance has been",
    "help is on the way",
    "we have your information",
    "we've collected your",
    "i've recorded your contact",
    "emergency services are on",
    "dispatch is on the way",
)
_DISPATCH_COMPLETION_PHRASES_TH: tuple[str, ...] = (
    "ส่งความช่วยเหลือ",
    "รถพยาบาลกำลัง",
    "เจ้าหน้าที่กำลัง",
    "เราได้รับข้อมูล",
    "ดำเนินการส่ง",
)


# Transcript callback: receives ("user"|"agent", text). Called from the
# live event loop so should be cheap and non-blocking — typically just
# pushes a JSON frame onto the WebSocket.
TranscriptCallback = Callable[[str, str], Awaitable[None]]


def _smart_append(chunks: list[str], fragment: str) -> str | None:
    """Append ``fragment`` to ``chunks`` while suppressing Gemini Live's
    common duplication patterns.

    Gemini Live's audio transcription streams emit a mix of partial and
    final events. Depending on the codec path, the API may emit:

    * the same final text twice (interim → final, both carrying the
      complete phrase),
    * a cumulative snapshot that grows on each event (each fragment
      contains everything seen so far for the utterance), or
    * true incremental deltas (each fragment is only the new portion).

    A naive ``chunks.append`` produces ``X X`` for the first two cases.
    This helper unifies them by:

    1. Skipping empty / whitespace-only fragments.
    2. Returning early when the new fragment already lives at the tail
       of the accumulated string (exact duplicate).
    3. Replacing the entire list when the new fragment is a strict
       superset of what's already accumulated (cumulative snapshot).
    4. Otherwise treating the fragment as a real delta and appending.

    Returns the fragment that should be forwarded to the WebSocket
    callback (i.e. the *new* portion), or ``None`` if the fragment was
    suppressed and nothing should be pushed to the client.
    """

    f = fragment.strip()
    if not f:
        return None
    existing = " ".join(c.strip() for c in chunks if c.strip()).strip()
    if not existing:
        chunks.append(f)
        return f
    # Case 2 — duplicate final event, suppress.
    if existing.endswith(f):
        return None
    # Case 3 — cumulative snapshot. Replace and forward only the delta so
    # the frontend caption doesn't get rewritten with the whole sentence
    # on every event.
    if f.startswith(existing):
        delta = f[len(existing):].strip()
        chunks.clear()
        chunks.append(f)
        return delta or None
    # Case 4 — true incremental delta.
    chunks.append(f)
    return f

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
    return (
        f"[The caller has just connected. Greet them warmly in {lang_name} "
        "as the Mae Fah Luang hotline AI nurse and ask how you can help "
        "them today. Keep it to one or two short spoken sentences.]"
    )


class LiveVoiceService:
    """Per-session orchestrator for live voice calls.

    Holds a single :class:`HotlineADKLiveRunner` and an in-memory map of
    active sessions. Each entry tracks the live queue (so we can push
    inbound audio), the running transcript (so we can replay it into
    the text pipeline for DB persistence and notification dispatch),
    the mute flag, the caller's language, the DB connection borrowed
    from the WebSocket route, and the user-supplied transcript /
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
            "language": language,
            "db_connection": db_connection,
            "transcript_cb": transcript_callback,
            "emergency_cb": emergency_callback,
            "assessment_cb": assessment_callback,
            "classification": {},
            "contact": {},
            "assessment_finalized": False,
            # Tracks whether we have already replayed the live transcript
            # into ``process_chat`` for a given trigger so we don't
            # double-fire notifications on the same emergency.
            "emergency_dispatched": False,
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
        # whatever classification/contact we captured from tool responses.
        if not session.get("assessment_finalized"):
            await self._complete_call_assessment(session_id, session=session)

        logger.info("Live voice session disconnected: %s", session_id)

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

        blob = genai_types.Blob(
            data=audio_chunk,
            mime_type=_INPUT_AUDIO_MIME_TYPE,
        )
        # LiveRequestQueue.send_realtime is the standard channel for
        # real-time PCM blobs and is intentionally synchronous (it just
        # puts an item onto an internal asyncio.Queue under the hood).
        session["queue"].send_realtime(blob)

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
        """Toggle mute and signal turn boundaries to Gemini Live.

        Muting stops forwarding microphone audio **and** sends
        ``activity_end`` so the model stops waiting for more speech and
        responds to what it already heard. Unmuting resumes forwarding
        and sends ``activity_start`` so the next utterance is a fresh
        user turn.
        """

        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        session["muted"] = muted
        queue: LiveRequestQueue = session["queue"]
        try:
            if muted:
                queue.send_activity_end()
                logger.info(
                    "Session %s muted; activity_end sent", session_id
                )
            else:
                queue.send_activity_start()
                logger.info(
                    "Session %s unmuted; activity_start sent", session_id
                )
        except Exception:  # noqa: BLE001 — must not break the WS control plane
            logger.exception(
                "Failed to send activity signal for %s (muted=%s)",
                session_id,
                muted,
            )
        logger.info("Session %s mute=%s", session_id, muted)

    def end_user_turn(self, session_id: str) -> None:
        """Tell Gemini Live the caller finished speaking (push-to-talk end)."""

        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Session not found")
        try:
            session["queue"].send_activity_end()
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
            self._log_event_shape(session_id, event)

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
                payload = self._extract_response_payload(func_response)
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
                # Heuristic safety net: if the agent says something that
                # sounds like dispatch confirmation but our tool-response
                # detection above never fired, replay the transcript into
                # the text pipeline anyway. Protects against ADK live
                # event-shape drift where function_response parts don't
                # surface in the live event stream.
                if not session["emergency_dispatched"]:
                    if self._agent_transcript_signals_dispatch(session):
                        logger.info(
                            "Heuristic dispatch detection fired for %s "
                            "(no function_response observed but agent "
                            "transcript mentioned dispatch)",
                            session_id,
                        )
                        session["emergency_dispatched"] = True
                        asyncio.create_task(
                            self._trigger_emergency_check(session_id)
                        )

    def _log_event_shape(self, session_id: str, event: Any) -> None:
        """Dump a one-line summary of an event's interesting attributes.

        Triggered when ``LIVE_DEBUG_EVENTS=true`` in the environment.
        Designed to make it obvious from the uvicorn log what the live
        event stream looks like — usually the difference between "tool
        responses surface as event.content.parts" and "tool responses
        come on a separate event with no content at all".
        """

        try:
            content = getattr(event, "content", None)
            parts = getattr(content, "parts", None) or []
            part_kinds: list[str] = []
            for p in parts:
                kinds = []
                if getattr(p, "inline_data", None) is not None:
                    kinds.append("audio")
                if getattr(p, "text", None):
                    kinds.append("text")
                if getattr(p, "function_call", None) is not None:
                    kinds.append("fn_call")
                if getattr(p, "function_response", None) is not None:
                    kinds.append("fn_resp")
                part_kinds.append("+".join(kinds) if kinds else "empty")
            calls = (
                event.get_function_calls()
                if callable(getattr(event, "get_function_calls", None))
                else []
            )
            responses = (
                event.get_function_responses()
                if callable(getattr(event, "get_function_responses", None))
                else []
            )
            logger.info(
                "[LIVE_DEBUG %s] author=%s partial=%s final=%s "
                "parts=%s calls=%d resps=%d in_tx=%s out_tx=%s",
                session_id,
                getattr(event, "author", "?"),
                getattr(event, "partial", None),
                callable(getattr(event, "is_final_response", None))
                and event.is_final_response(),
                part_kinds,
                len(calls),
                len(responses),
                bool(getattr(event, "input_transcription", None)),
                bool(getattr(event, "output_transcription", None)),
            )
            if responses:
                for r in responses:
                    logger.info(
                        "[LIVE_DEBUG %s] fn_resp name=%s response=%r",
                        session_id,
                        getattr(r, "name", "?"),
                        getattr(r, "response", None),
                    )
        except Exception:  # noqa: BLE001 — debug logging must never crash the pipeline
            logger.exception(
                "Debug event dump failed for %s", session_id
            )

    @staticmethod
    def _extract_response_payload(func_response: Any) -> dict[str, Any] | None:
        """Coerce a FunctionResponse into the plain dict our tools return.

        ADK 2.x typically wraps tool returns in
        ``FunctionResponse(response={...})``, but in some live event
        paths the response field has already been unwrapped. Try both.
        """

        if func_response is None:
            return None
        response = getattr(func_response, "response", None)
        if isinstance(response, dict):
            return response
        # Some live wrappers set ``response`` to None and put the dict
        # on the FunctionResponse itself via `parts` / `output`. Cover
        # the common fallbacks defensively.
        out = getattr(func_response, "output", None)
        if isinstance(out, dict):
            return out
        return None

    @staticmethod
    def _agent_transcript_signals_dispatch(session: dict[str, Any]) -> bool:
        """Heuristic match against accumulated agent speech.

        Returns ``True`` if the agent appears to have verbally confirmed
        emergency dispatch, even though no function_response was seen.
        Case-insensitive substring match — phrases live above as
        ``_DISPATCH_COMPLETION_PHRASES_*``.
        """

        text = " ".join(c for c in session.get("agent_transcript", []) if c)
        if not text:
            return False
        lowered = text.lower()
        language = session.get("language", "en")
        phrases = (
            _DISPATCH_COMPLETION_PHRASES_TH
            if language == "th"
            else _DISPATCH_COMPLETION_PHRASES_EN
        )
        return any(phrase in lowered for phrase in phrases)

    async def _handle_tool_response(
        self,
        session_id: str,
        payload: dict[str, Any],
        emergency_cb: EmergencyCallback | None,
    ) -> None:
        """React to a single function_response payload from the live event stream.

        Emergency classifications and contact-collection completions both
        cascade into the text pipeline via ``_trigger_emergency_check`` so
        ``process_chat`` writes the same DB rows it would in text mode.
        The frontend banner gets an immediate push via ``emergency_cb``.
        """

        session = self._sessions.get(session_id)
        if session is None:
            return

        classified = payload.get("classified") is True
        contact_collected = payload.get("contact_collected") is True
        level = payload.get("level") if isinstance(payload.get("level"), int) else None
        needs_contact = payload.get("needs_emergency_contact") is True

        if classified:
            session["classification"] = payload

        if contact_collected:
            session["contact"] = payload

        if classified and level in (1, 2) and not session["emergency_dispatched"]:
            session["emergency_dispatched"] = True
            asyncio.create_task(self._trigger_emergency_check(session_id))
            if emergency_cb is not None:
                banner_payload: dict[str, Any] = {
                    "severity": "emergency",
                    "level": level,
                    "alert_message": (
                        payload.get("key_reason")
                        or "Emergency triage match — dispatch in progress"
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

        if contact_collected:
            asyncio.create_task(self._trigger_emergency_check(session_id))
            if emergency_cb is not None:
                # Contact-complete event — let the frontend banner update
                # with the dispatch confirmation copy if it wants to.
                try:
                    await emergency_cb(
                        {
                            "severity": "emergency",
                            "contact_collected": True,
                            "patient_name": payload.get("patient_name"),
                            "phone_number": payload.get("phone_number"),
                            "address": payload.get("address"),
                        }
                    )
                except Exception:
                    logger.exception(
                        "emergency_cb (contact) failed for %s", session_id
                    )
            # All emergency info collected — finalize and auto-end.
            asyncio.create_task(self._complete_call_assessment(session_id))

        elif classified and not needs_contact and not session.get("assessment_finalized"):
            # Non-emergency triage complete (Levels 3–5). Finalize once
            # the agent has delivered the spoken summary.
            asyncio.create_task(self._complete_call_assessment(session_id))

    # ------------------------------------------------------------------
    # Assessment completion + auto-end
    # ------------------------------------------------------------------

    async def _complete_call_assessment(
        self,
        session_id: str,
        *,
        session: dict[str, Any] | None = None,
    ) -> None:
        """Persist the final assessment and notify patient + staff.

        Idempotent — safe to call from tool handlers, heuristic dispatch
        detection, and disconnect cleanup.
        """

        if session is None:
            session = self._sessions.get(session_id)
        if session is None or session.get("assessment_finalized"):
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
            result, _ = await self.triage_service.finalize_live_assessment(
                connection=session["db_connection"],
                session_id=session_id,
                language=session["language"],
                input_mode="voice",
                content=full_text or "[voice call]",
                classification=classification,
                contact=session.get("contact") or {},
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

        Runs while the call is still active so the EMS dispatch path
        (``MockNotificationService.send_alert``) fires without waiting
        for the caller to hang up. Failures are logged but never
        propagated — the live pipeline must keep running even if the
        secondary DB / notifier path fails.
        """

        session = self._sessions.get(session_id)
        if session is None:
            return
        transcript_chunks: list[str] = session["transcript"]
        full_text = " ".join(chunk.strip() for chunk in transcript_chunks if chunk).strip()
        if not full_text:
            # Nothing transcribed yet (early classification on a button
            # press, say). Skip — disconnect() will catch the final flush.
            return

        try:
            await self.triage_service.process_chat(
                connection=session["db_connection"],
                session_id=session_id,
                language=session["language"],
                input_mode="voice",
                content=full_text,
            )
        except Exception:
            logger.exception(
                "Mid-call emergency check failed for %s", session_id
            )
