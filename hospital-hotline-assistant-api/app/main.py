import asyncio
import json
import logging
from contextlib import asynccontextmanager
from uuid import UUID
import asyncpg
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from app.config import settings
from app.database import create_pool, get_connection, record_to_dict, records_to_dicts
from app.services import TriageService
from app.services.google_stt import GoogleSttClient
from app.services.google_tts import GoogleTtsClient
from app.services.live_voice_service import LiveVoiceService
from app.services.notification_service import MockNotificationService

logger = logging.getLogger(__name__)
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationSummaryOut,
    DepartmentOut,
    DepartmentRecommendationCreate,
    EmergencyEventCreate,
    EmergencyEventOut,
    EmergencyTriggerOut,
    FollowUpQuestionAnswerUpdate,
    FollowUpQuestionCreate,
    FollowUpQuestionOut,
    MessageCreate,
    MessageOut,
    RoutingRuleOut,
    SessionCreate,
    SessionOut,
    SessionUpdate,
    SeverityAssessmentCreate,
    SttResponse,
    SymptomEntryCreate,
    TtsRequest,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = await create_pool()
    notifier = MockNotificationService()
    app.state.triage_service = TriageService(notifier=notifier)
    app.state.tts_client = GoogleTtsClient()
    app.state.stt_client = GoogleSttClient()
    # Gemini Live API bridge — owns the per-call WebSocket state for
    # voice mode. Reuses the same TriageService so emergency dispatch
    # paths through MockNotificationService stay identical to text.
    app.state.live_voice_service = LiveVoiceService(
        triage_service=app.state.triage_service
    )
    try:
        yield
    finally:
        await app.state.db_pool.close()

app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(asyncpg.ForeignKeyViolationError)
async def foreign_key_violation_handler(request: Request, exc: asyncpg.ForeignKeyViolationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Referenced record does not exist. Check session_id, message_id, assessment_id, department_id, or trigger_id."},
    )

@app.exception_handler(asyncpg.UniqueViolationError)
async def unique_violation_handler(request: Request, exc: asyncpg.UniqueViolationError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "Record already exists."},
    )

@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "status": "running",
        "docs": "/docs",
    }

@app.get("/health")
async def health(connection: asyncpg.Connection = Depends(get_connection)) -> dict[str, str]:
    await connection.fetchval("SELECT 1")
    return {"status": "ok", "environment": settings.environment}

@app.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate, connection: asyncpg.Connection = Depends(get_connection)):
    record = await connection.fetchrow(
        """
        INSERT INTO sessions (language, user_agent, ip_hash, metadata)
        VALUES ($1, $2, $3, $4::jsonb)
        RETURNING *
        """,
        payload.language,
        payload.user_agent,
        payload.ip_hash,
        payload.metadata,
    )
    return record_to_dict(record)

@app.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: UUID, connection: asyncpg.Connection = Depends(get_connection)):
    record = await connection.fetchrow("SELECT * FROM sessions WHERE id = $1", session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return record_to_dict(record)

@app.patch("/sessions/{session_id}", response_model=SessionOut)
async def update_session(session_id: UUID, payload: SessionUpdate, connection: asyncpg.Connection = Depends(get_connection)):
    ended_sql = "NOW()" if payload.status in {"completed", "reset", "escalated"} else "ended_at"
    record = await connection.fetchrow(
        f"""
        UPDATE sessions
        SET status = $2, ended_at = {ended_sql}
        WHERE id = $1
        RETURNING *
        """,
        session_id,
        payload.status,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return record_to_dict(record)

@app.post("/sessions/{session_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def create_message(session_id: UUID, payload: MessageCreate, connection: asyncpg.Connection = Depends(get_connection)):
    record = await connection.fetchrow(
        """
        INSERT INTO messages (
            session_id, role, input_mode, content, audio_url, transcript_confidence,
            model_name, response_latency_ms, metadata
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
        RETURNING *
        """,
        session_id,
        payload.role,
        payload.input_mode,
        payload.content,
        payload.audio_url,
        payload.transcript_confidence,
        payload.model_name,
        payload.response_latency_ms,
        payload.metadata,
    )
    return record_to_dict(record)

@app.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(session_id: UUID, connection: asyncpg.Connection = Depends(get_connection)):
    records = await connection.fetch(
        "SELECT * FROM messages WHERE session_id = $1 ORDER BY created_at ASC",
        session_id,
    )
    return records_to_dicts(records)

@app.post("/sessions/{session_id}/chat", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def chat(
    session_id: UUID,
    payload: ChatRequest,
    request: Request,
    connection: asyncpg.Connection = Depends(get_connection),
):
    triage_service: TriageService = request.app.state.triage_service
    try:
        result, assistant_message = await triage_service.process_chat(
            connection=connection,
            session_id=str(session_id),
            language=payload.language,
            input_mode=payload.input_mode,
            content=payload.content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ChatResponse(
        reply=result.reply,
        severity={
            "level": result.severity_level,
            "explanation": result.severity_explanation,
            "confidence": result.severity_confidence,
        },
        department={
            "department_id": result.department_id,
            "reason": result.department_reason,
            "confidence": result.department_confidence,
        }
        if result.department_id
        else None,
        emergency={
            "trigger_id": result.emergency_trigger_id,
            "alert_message": result.emergency_alert_message,
            "detected_symptoms": result.detected_symptoms,
        }
        if result.severity_level == "emergency"
        else None,
        symptoms={
            "raw_text": payload.content,
            "body_location": None,
            "duration_text": None,
        },
        follow_up_question=result.follow_up_question,
        follow_up_reason=result.follow_up_reason,
        model_name=result.model_name,
        latency_ms=result.latency_ms,
        alert_sent=result.alert_sent,
        assistant_message_id=assistant_message.get("id"),
    )

@app.post("/sessions/{session_id}/chat/stream")
async def chat_stream(
    session_id: UUID,
    payload: ChatRequest,
    request: Request,
):
    """Server-Sent Events variant of :func:`chat`.

    Streams the agent's response back to the client incrementally so
    the UI can render tokens as they arrive (typewriter effect) and
    kick off per-sentence TTS before the model finishes generating.
    Persistence, rule-engine overrides, and notifier dispatch run
    exactly as in the non-streaming path — only the transport differs.

    The stream emits NDJSON frames inside an SSE ``data:`` line so the
    browser ``EventSource`` (or a fetch + ReadableStream consumer) can
    parse each event with a single ``JSON.parse``. Frame schema is
    defined by :meth:`TriageService.process_chat_stream` (look there
    for the authoritative type list).

    Note we acquire the DB connection INSIDE the generator (rather
    than via ``Depends(get_connection)``) because FastAPI releases the
    dependency connection back to the pool the moment the route
    function returns — and for a StreamingResponse, that happens
    before the generator runs. Acquiring inside keeps the connection
    held for the lifetime of the stream.
    """

    triage_service: TriageService = request.app.state.triage_service
    pool: asyncpg.Pool = request.app.state.db_pool

    async def event_generator():
        async with pool.acquire() as connection:
            try:
                async for event in triage_service.process_chat_stream(
                    connection=connection,
                    session_id=str(session_id),
                    language=payload.language,
                    input_mode=payload.input_mode,
                    content=payload.content,
                ):
                    # SSE framing — one JSON payload per ``data:`` line,
                    # terminated by a blank line. We use ``default=str``
                    # so asyncpg datetimes / UUIDs (which appear in the
                    # ``user_message`` and ``assistant_message`` events)
                    # serialize without an extra coercion step.
                    yield f"data: {json.dumps(event, default=str)}\n\n"
            except Exception as exc:
                logger.exception("chat_stream failed for session %s", session_id)
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            # Disable any intermediate buffering so each frame reaches
            # the client immediately — nginx in particular adds 4 KB
            # of buffering by default which would batch our deltas.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/sessions/{session_id}/symptoms", status_code=status.HTTP_201_CREATED)
async def create_symptom_entry(session_id: UUID, payload: SymptomEntryCreate, connection: asyncpg.Connection = Depends(get_connection)):
    record = await connection.fetchrow(
        """
        INSERT INTO symptom_entries (
            session_id, message_id, raw_text, normalized_symptoms,
            body_location, duration_text, pain_score
        )
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
        RETURNING *
        """,
        session_id,
        payload.message_id,
        payload.raw_text,
        payload.normalized_symptoms,
        payload.body_location,
        payload.duration_text,
        payload.pain_score,
    )
    return record_to_dict(record)

@app.post("/sessions/{session_id}/severity-assessments", status_code=status.HTTP_201_CREATED)
async def create_severity_assessment(
    session_id: UUID,
    payload: SeverityAssessmentCreate,
    connection: asyncpg.Connection = Depends(get_connection),
    ):
    record = await connection.fetchrow(
        """
        INSERT INTO severity_assessments (
            session_id, source_message_id, severity, confidence, explanation, detected_triggers
        )
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        RETURNING *
        """,
        session_id,
        payload.source_message_id,
        payload.severity,
        payload.confidence,
        payload.explanation,
        payload.detected_triggers,
    )
    return record_to_dict(record)

@app.post("/sessions/{session_id}/follow-up-questions", response_model=FollowUpQuestionOut, status_code=status.HTTP_201_CREATED)
async def create_follow_up_question(
    session_id: UUID,
    payload: FollowUpQuestionCreate,
    connection: asyncpg.Connection = Depends(get_connection),
):
    record = await connection.fetchrow(
        """
        INSERT INTO follow_up_questions (session_id, question_text, reason)
        VALUES ($1, $2, $3)
        RETURNING *
        """,
        session_id,
        payload.question_text,
        payload.reason,
    )
    return record_to_dict(record)

@app.get("/sessions/{session_id}/follow-up-questions", response_model=list[FollowUpQuestionOut])
async def list_follow_up_questions(
    session_id: UUID,
    connection: asyncpg.Connection = Depends(get_connection),
):
    records = await connection.fetch(
        """
        SELECT *
        FROM follow_up_questions
        WHERE session_id = $1
        ORDER BY asked_at ASC
        """,
        session_id,
    )
    return records_to_dicts(records)

@app.patch("/sessions/{session_id}/follow-up-questions/{question_id}/answer", response_model=FollowUpQuestionOut)
async def answer_follow_up_question(
    session_id: UUID,
    question_id: UUID,
    payload: FollowUpQuestionAnswerUpdate,
    connection: asyncpg.Connection = Depends(get_connection),
):
    record = await connection.fetchrow(
        """
        UPDATE follow_up_questions
        SET answer_message_id = $3, answered_at = NOW()
        WHERE id = $1 AND session_id = $2
        RETURNING *
        """,
        question_id,
        session_id,
        payload.answer_message_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Follow-up question not found")
    return record_to_dict(record)

@app.get("/departments", response_model=list[DepartmentOut])
async def list_departments(connection: asyncpg.Connection = Depends(get_connection)):
    records = await connection.fetch(
        "SELECT * FROM departments WHERE is_active = TRUE ORDER BY name_en ASC"
    )
    return records_to_dicts(records)

@app.get("/routing-rules", response_model=list[RoutingRuleOut])
async def list_routing_rules(connection: asyncpg.Connection = Depends(get_connection)):
    records = await connection.fetch(
        "SELECT * FROM routing_rules WHERE is_active = TRUE ORDER BY priority ASC, rule_name ASC"
    )
    return records_to_dicts(records)

@app.get("/emergency-triggers", response_model=list[EmergencyTriggerOut])
async def list_emergency_triggers(connection: asyncpg.Connection = Depends(get_connection)):
    records = await connection.fetch(
        "SELECT * FROM emergency_triggers WHERE is_active = TRUE ORDER BY priority ASC, trigger_name ASC"
    )
    return records_to_dicts(records)

@app.post("/sessions/{session_id}/department-recommendations", status_code=status.HTTP_201_CREATED)
async def create_department_recommendation(
    session_id: UUID,
    payload: DepartmentRecommendationCreate,
    connection: asyncpg.Connection = Depends(get_connection),
):
    record = await connection.fetchrow(
        """
        INSERT INTO department_recommendations (
            session_id, assessment_id, department_id, confidence, reason
        )
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        session_id,
        payload.assessment_id,
        payload.department_id,
        payload.confidence,
        payload.reason,
    )
    return record_to_dict(record)

@app.post("/sessions/{session_id}/emergency-events", status_code=status.HTTP_201_CREATED)
async def create_emergency_event(
    session_id: UUID,
    payload: EmergencyEventCreate,
    connection: asyncpg.Connection = Depends(get_connection),
):
    record = await connection.fetchrow(
        """
        INSERT INTO emergency_events (
            session_id, trigger_id, source_message_id, detected_symptoms, alert_message
        )
        VALUES ($1, $2, $3, $4::jsonb, $5)
        RETURNING *
        """,
        session_id,
        payload.trigger_id,
        payload.source_message_id,
        payload.detected_symptoms,
        payload.alert_message,
    )
    return record_to_dict(record)

@app.get("/sessions/{session_id}/emergency-events", response_model=list[EmergencyEventOut])
async def list_emergency_events(
    session_id: UUID,
    connection: asyncpg.Connection = Depends(get_connection),
):
    records = await connection.fetch(
        """
        SELECT *
        FROM emergency_events
        WHERE session_id = $1
        ORDER BY created_at DESC
        """,
        session_id,
    )
    return records_to_dicts(records)

@app.post("/tts")
async def text_to_speech(payload: TtsRequest, request: Request):
    """Synthesize speech for the given text. Returns audio/mpeg (MP3) bytes."""

    tts_client: GoogleTtsClient = request.app.state.tts_client
    try:
        audio_bytes = await tts_client.synthesize(
            text=payload.text,
            language=payload.language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="speech.mp3"'},
    )


@app.post("/stt", response_model=SttResponse)
async def speech_to_text(
    request: Request,
    audio: UploadFile = File(..., description="Short audio clip from MediaRecorder"),
    language: str = Form("en"),
):
    """Transcribe a short audio clip. Returns the recognized text."""

    if language not in {"en", "th"}:
        raise HTTPException(status_code=400, detail="language must be 'en' or 'th'")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio file is empty")

    stt_client: GoogleSttClient = request.app.state.stt_client
    try:
        result = await stt_client.transcribe(
            audio_bytes=audio_bytes,
            language=language,
            mime_type=audio.content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SttResponse(
        transcript=result.transcript,
        confidence=result.confidence,
        language_code=result.language_code,
    )


@app.get("/conversation-summary", response_model=list[ConversationSummaryOut])
async def conversation_summary(connection: asyncpg.Connection = Depends(get_connection)):
    records = await connection.fetch(
        """
        SELECT
            cs.*,
            COALESCE((s.metadata->>'alert_sent')::boolean, FALSE) AS has_alert,
            s.metadata->>'escalation_reason' AS escalation_reason
        FROM conversation_summary cs
        JOIN sessions s ON s.id = cs.session_id
        ORDER BY cs.started_at DESC
        LIMIT 100
        """
    )
    return records_to_dicts(records)


# ---------------------------------------------------------------------------
# Voice WebSocket — Gemini Live API bridge
# ---------------------------------------------------------------------------
#
# Protocol (see app/services/live_voice_service.py for state details):
#
#   Client → server
#     bytes                          raw PCM 16-bit 16 kHz mono audio chunk
#     {"type": "mute"}               suppress mic forward to the live pipeline
#     {"type": "unmute"}             resume forwarding
#     {"type": "end_of_turn"}        soft hint, currently a no-op
#     {"type": "end_call"}           caller hung up — close gracefully
#
#   Server → client
#     bytes                          raw PCM agent audio (24 kHz mono)
#     {"type": "status", "muted":…}  ack for mute / unmute
#     {"type": "call_ended"}         sent right before the socket closes
#     {"type": "error",   "message"} fatal error before close
#
# The endpoint runs two tasks concurrently: one drives ADK's bidirectional
# stream and forwards audio to the browser, the other listens for inbound
# audio + control messages. When either task finishes (clean disconnect,
# explicit end_call, or a crash) we cancel the sibling task and run
# disconnect() — which flushes the accumulated transcript through the
# normal text triage pipeline so DB rows and the mock notifier still fire.


@app.websocket("/ws/voice/{session_id}")
async def voice_call(websocket: WebSocket, session_id: str):
    await websocket.accept()
    pool: asyncpg.Pool = websocket.app.state.db_pool
    live_voice_service: LiveVoiceService = websocket.app.state.live_voice_service
    language = websocket.query_params.get("language", "en")

    # Callbacks forward live transcripts + emergency banner triggers from
    # the ADK event loop to the frontend over the WS. ``send_*`` may
    # raise if the client closed the socket mid-send; swallow those so a
    # disconnect race doesn't crash the pipeline.
    async def push_transcript(role: str, text: str) -> None:
        try:
            await websocket.send_json(
                {"type": "transcript", "role": role, "text": text}
            )
        except Exception:
            logger.debug(
                "Failed to push transcript to %s (likely client closed)",
                session_id,
            )

    async def push_emergency(payload: dict) -> None:
        try:
            await websocket.send_json({"type": "emergency", **payload})
        except Exception:
            logger.debug(
                "Failed to push emergency to %s (likely client closed)",
                session_id,
            )

    async def push_assessment(payload: dict) -> None:
        try:
            await websocket.send_json({"type": "assessment_complete", **payload})
        except Exception:
            logger.debug(
                "Failed to push assessment to %s (likely client closed)",
                session_id,
            )

    async with pool.acquire() as conn:
        try:
            await live_voice_service.connect(
                session_id,
                language,
                conn,
                transcript_callback=push_transcript,
                emergency_callback=push_emergency,
                assessment_callback=push_assessment,
            )
        except ValueError as exc:
            await websocket.close(code=1008, reason=str(exc))
            return
        except Exception:
            logger.exception("Voice connect failed for %s", session_id)
            try:
                await websocket.send_json({"type": "error", "message": "connect_failed"})
            finally:
                await websocket.close(code=1011)
            return

        async def pump_outbound() -> None:
            """ADK live pipeline → WebSocket audio frames."""
            try:
                async for chunk in live_voice_service.run_live_pipeline(session_id):
                    if chunk:
                        await websocket.send_bytes(chunk)
            except WebSocketDisconnect:
                # Client closed mid-stream; cancellation will tear down
                # the receive task as well.
                pass
            except Exception:
                logger.exception(
                    "Outbound voice pump failed for %s", session_id
                )

        async def pump_inbound() -> None:
            """WebSocket frames → ADK live queue / control plane."""
            while True:
                try:
                    message = await websocket.receive()
                except WebSocketDisconnect:
                    return

                # FastAPI / Starlette gives us either bytes or text in
                # ``message``. Binary is microphone PCM; text is a JSON
                # control envelope. ``message["type"]`` is the wire
                # event (e.g. "websocket.disconnect") — not our payload
                # type — so disambiguate by key.
                if message.get("type") == "websocket.disconnect":
                    return

                if (data := message.get("bytes")) is not None:
                    try:
                        await live_voice_service.send_audio(session_id, data)
                    except ValueError:
                        # Session vanished — bail. The outer cleanup will
                        # close the socket.
                        return
                    except Exception:
                        logger.exception(
                            "send_audio failed for %s", session_id
                        )
                    continue

                text = message.get("text")
                if text is None:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning(
                        "Voice WS %s: discarding non-JSON text frame", session_id
                    )
                    continue

                msg_type = payload.get("type") if isinstance(payload, dict) else None
                if msg_type == "mute":
                    live_voice_service.set_mute(session_id, True)
                    await websocket.send_json({"type": "status", "muted": True})
                elif msg_type == "unmute":
                    live_voice_service.set_mute(session_id, False)
                    await websocket.send_json({"type": "status", "muted": False})
                elif msg_type == "end_of_turn":
                    # ADK's voice activity detection handles turn-end on
                    # its own; the hint is here so the frontend can also
                    # call send_activity_end in the future if needed.
                    continue
                elif msg_type == "end_call":
                    return
                else:
                    logger.debug(
                        "Voice WS %s: unknown control message %r",
                        session_id,
                        msg_type,
                    )

        outbound_task = asyncio.create_task(pump_outbound())
        inbound_task = asyncio.create_task(pump_inbound())
        try:
            done, pending = await asyncio.wait(
                {outbound_task, inbound_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            # Surface any unexpected task exceptions to the log without
            # raising — disconnect() must still run.
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, asyncio.CancelledError):
                    logger.exception(
                        "Voice WS %s task crashed", session_id, exc_info=exc
                    )
            # Wait briefly for cancellations so disconnect() sees no
            # in-flight ADK iteration when it closes the queue.
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            await live_voice_service.disconnect(session_id)
            try:
                await websocket.send_json({"type": "call_ended"})
            except Exception:
                # Socket already closed by the client — fine.
                pass
            try:
                await websocket.close()
            except Exception:
                pass
            logger.info("Voice call ended: %s", session_id)
