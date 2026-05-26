from contextlib import asynccontextmanager
from uuid import UUID
import asyncpg
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from app.config import settings
from app.database import create_pool, get_connection, record_to_dict, records_to_dicts
from app.services import TriageService
from app.services.google_stt import GoogleSttClient
from app.services.google_tts import GoogleTtsClient
from app.services.notification_service import MockNotificationService
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
