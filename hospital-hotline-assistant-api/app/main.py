import asyncio
import json
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from uuid import UUID
import asyncpg
from pydantic import BaseModel
from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.config import settings
from app.database import create_pool, get_connection, record_to_dict, records_to_dicts
from app.services import TriageService
from app.services.surveillance_extractor import extract_and_save as surveillance_extract
from app.services.admin_auth import (
    issue_admin_token,
    validate_admin_token,
    verify_password,
)
from app.services.blood_pressure import (
    BloodPressureFetchError,
    BloodPressureService,
)
from app.services.google_stt import GoogleSttClient
from app.services.google_tts import GoogleTtsClient
from app.services.live_voice_service import LiveVoiceService
from app.services.notification_service import MockNotificationService

logger = logging.getLogger(__name__)
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationSummaryOut,
    AdminLoginRequest,
    AdminLoginResponse,
    AdminUserOut,
    DepartmentOut,
    DepartmentRecommendationCreate,
    DoctorCreate,
    DoctorOut,
    DoctorScheduleCreate,
    DoctorScheduleOut,
    DoctorUpdate,
    DoctorWithSchedulesOut,
    EmergencyEventCreate,
    EmergencyEventOut,
    EmergencyTriggerOut,
    AssessmentReviewApproveRequest,
    AssessmentReviewCorrectRequest,
    AssessmentReviewOut,
    FollowUpQuestionAnswerUpdate,
    FollowUpQuestionCreate,
    FollowUpQuestionOut,
    BloodPressureFetchResponse,
    BpDeviceStatusOut,
    BpFetchRequest,
    BpWatchRequest,
    BpPairRequest,
    BpPairResponse,
    BpScanResponse,
    MessageCreate,
    MessageOut,
    RoutingRuleOut,
    SessionCreate,
    SessionLocationUpdate,
    SessionOut,
    SessionUpdate,
    SessionVitalsUpdate,
    SeverityAssessmentCreate,
    RoutingFeedbackOut,
    SttResponse,
    SurveillanceSummaryOut,
    SymptomEntryCreate,
    TtsRequest,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = await create_pool()
    app.state.admin_tokens = {}
    notifier = MockNotificationService()
    # TRIAGE_ENGINE=adk keeps the legacy free-form ADK engine;
    # TRIAGE_ENGINE=langgraph uses the deterministic screening engine v2.
    from app.services.screening.engine import make_triage_engine

    triage_engine = make_triage_engine(settings, pool=app.state.db_pool)
    app.state.triage_service = TriageService(
        notifier=notifier, triage_engine=triage_engine
    )
    app.state.tts_client = GoogleTtsClient()
    app.state.stt_client = GoogleSttClient()
    # Voice bridge — owns the per-call WebSocket state for voice mode.
    # VOICE_ENGINE=live keeps the Gemini Live full-duplex bridge;
    # VOICE_ENGINE=turn runs calls turn-by-turn through the same
    # TriageService pipeline as text chat (STT → process_chat → TTS),
    # so the deterministic screening engine controls voice too. Both
    # expose the same surface to the /ws/voice route.
    if settings.voice_engine == "turn":
        from app.services.screening.voice_bridge import TurnVoiceService

        app.state.live_voice_service = TurnVoiceService(
            triage_service=app.state.triage_service,
            stt_client=app.state.stt_client,
            tts_client=app.state.tts_client,
        )
    else:
        app.state.live_voice_service = LiveVoiceService(
            triage_service=app.state.triage_service
        )
    app.state.rag_prewarm_task = None
    if settings.rag_query_prewarm_on_startup:
        from app.services.ai.rag_query import start_rag_query_engine_prewarm

        app.state.rag_prewarm_task = start_rag_query_engine_prewarm()
    # Kiosk-side Omron cuff reader (omblepy subprocess wrapper).
    app.state.bp_service = BloodPressureService()
    try:
        yield
    finally:
        prewarm_task = getattr(app.state, "rag_prewarm_task", None)
        if prewarm_task is not None and not prewarm_task.done():
            prewarm_task.cancel()
        await app.state.db_pool.close()

app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
auth_scheme = HTTPBearer(auto_error=False)


async def _serialize_review(
    connection: asyncpg.Connection, assessment_id: UUID
) -> dict:
    row = await connection.fetchrow(
        """
        SELECT
            ar.*,
            reviewer.full_name AS reviewer_name,
            pd.name_en AS proposed_department_name_en,
            pd.name_th AS proposed_department_name_th,
            cd.name_en AS confirmed_department_name_en,
            cd.name_th AS confirmed_department_name_th,
            (s.metadata->>'patient_contact_requested')::boolean AS patient_contact_requested,
            NULLIF(s.metadata->>'patient_contact_phone', '') AS patient_contact_phone,
            NULLIF(s.metadata->>'patient_contact_preferred_time', '') AS patient_contact_preferred_time,
            NULLIF(s.metadata->>'patient_contact_relation', '') AS patient_contact_relation,
            s.metadata->'triage_classification'->'disposition_reasons' AS disposition_reasons
        FROM assessment_reviews ar
        JOIN sessions s ON s.id = ar.session_id
        LEFT JOIN admin_users reviewer ON reviewer.id = ar.reviewer_id
        LEFT JOIN departments pd ON pd.id = ar.proposed_department_id
        LEFT JOIN departments cd ON cd.id = ar.confirmed_department_id
        WHERE ar.assessment_id = $1
        """,
        assessment_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Assessment review not found")
    return dict(row)


async def get_current_admin_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    connection: asyncpg.Connection = Depends(get_connection),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing admin bearer token")
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid auth scheme")

    token_store: dict = request.app.state.admin_tokens
    session = validate_admin_token(token_store, credentials.credentials)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_row = await connection.fetchrow(
        """
        SELECT id, email, full_name, role, is_active
        FROM admin_users
        WHERE id = $1
        """,
        session["admin_user_id"],
    )
    if user_row is None or not user_row["is_active"]:
        raise HTTPException(status_code=401, detail="Admin user is inactive")
    return dict(user_row)


def require_roles(*allowed_roles: str):
    async def _check(admin_user: dict = Depends(get_current_admin_user)) -> dict:
        if admin_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this portal",
            )
        return admin_user

    return _check

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


@app.post("/admin/login", response_model=AdminLoginResponse)
async def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    connection: asyncpg.Connection = Depends(get_connection),
):
    user = await connection.fetchrow(
        """
        SELECT id, email, password_hash, full_name, role, is_active
        FROM admin_users
        WHERE LOWER(email) = LOWER($1)
        """,
        payload.email,
    )
    if user is None or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token, expires_at = issue_admin_token(
        request.app.state.admin_tokens,
        admin_user_id=str(user["id"]),
        email=user["email"],
        role=user["role"],
    )
    await connection.execute(
        "UPDATE admin_users SET last_login_at = NOW() WHERE id = $1",
        user["id"],
    )
    return AdminLoginResponse(
        access_token=token,
        expires_at=expires_at,
        user=AdminUserOut(
            id=user["id"],
            email=user["email"],
            full_name=user["full_name"],
            role=user["role"],
        ),
    )

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
async def update_session(
    session_id: UUID,
    payload: SessionUpdate,
    request: Request,
    connection: asyncpg.Connection = Depends(get_connection),
):
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

    # Fire AI disease-keyword extraction as a background task when a session
    # completes. Uses a fresh connection from the pool so the response is
    # returned immediately without waiting for the Gemini call to finish.
    if payload.status == "completed":
        pool = request.app.state.db_pool
        asyncio.create_task(
            _run_surveillance_extract(pool=pool, session_id=str(session_id))
        )

    return record_to_dict(record)


async def _run_surveillance_extract(
    *, pool: asyncpg.Pool, session_id: str
) -> None:
    """Acquire a fresh connection and run the surveillance extractor."""
    async with pool.acquire() as conn:
        await surveillance_extract(connection=conn, session_id=session_id)

@app.put("/sessions/{session_id}/location")
async def update_session_location(
    session_id: UUID,
    payload: SessionLocationUpdate,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Save the patient-reported area for a session.
    Called by the chat UI after the user answers the location prompt.
    """
    record = await connection.fetchrow(
        """
        UPDATE sessions SET location_area = $2
        WHERE id = $1
        RETURNING id, location_area
        """,
        session_id,
        payload.location_area.strip(),
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": str(record["id"]), "location_area": record["location_area"]}


async def _store_bp_reading(
    connection: asyncpg.Connection,
    *,
    session_id: UUID | None,
    systolic: int,
    diastolic: int,
    pulse_bpm: int | None,
    measured_at: datetime | None,
    irregular_heartbeat: bool | None = None,
    body_movement: bool | None = None,
    source: str = "device",
) -> UUID | None:
    """Insert a reading into ``bp_readings`` and return its id.

    Device readings are deduplicated on (measured_at, systolic, diastolic):
    the kiosk polls the cuff while waiting, so the same measurement arrives
    several times. On a duplicate, the existing row is returned and its
    session link is filled in if it was still missing.
    """
    if measured_at is not None and measured_at.tzinfo is not None:
        # bp_readings.measured_at is the cuff's own (naive, local) clock.
        measured_at = measured_at.astimezone().replace(tzinfo=None)
    row = await connection.fetchrow(
        """
        INSERT INTO bp_readings
            (session_id, systolic, diastolic, pulse_bpm, measured_at,
             irregular_heartbeat, body_movement, source)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (measured_at, systolic, diastolic) WHERE source = 'device'
        DO NOTHING
        RETURNING id
        """,
        session_id,
        systolic,
        diastolic,
        pulse_bpm,
        measured_at,
        irregular_heartbeat,
        body_movement,
        source,
    )
    if row is not None:
        return row["id"]
    # Duplicate device reading from an earlier poll — reuse it and attach
    # the session if this call knows it and the stored row does not yet.
    row = await connection.fetchrow(
        """
        UPDATE bp_readings
        SET session_id = COALESCE(session_id, $4)
        WHERE source = 'device'
          AND measured_at = $1 AND systolic = $2 AND diastolic = $3
        RETURNING id
        """,
        measured_at,
        systolic,
        diastolic,
        session_id,
    )
    return row["id"] if row is not None else None


@app.put("/sessions/{session_id}/vitals")
async def update_session_vitals(
    session_id: UUID,
    payload: SessionVitalsUpdate,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Store a blood-pressure reading on the session so the triage agent
    (text chat and live voice) can factor it into the assessment.
    Called by the vitals gate UI after a cuff fetch or manual entry.
    """
    session_row = await connection.fetchrow(
        "SELECT metadata FROM sessions WHERE id = $1", session_id
    )
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = dict(session_row["metadata"] or {})
    vitals = {
        "systolic": payload.systolic,
        "diastolic": payload.diastolic,
        "pulse_bpm": payload.pulse_bpm,
        "measured_at": payload.measured_at.isoformat() if payload.measured_at else None,
        "source": payload.source,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata["vitals"] = vitals
    await connection.execute(
        "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
        session_id,
        metadata,
    )

    # Keep the durable bp_readings row in sync: link the row created at
    # fetch time when we have its id, otherwise store this (e.g. manual)
    # reading now.
    if payload.reading_id is not None:
        await connection.execute(
            "UPDATE bp_readings SET session_id = $2 WHERE id = $1",
            payload.reading_id,
            session_id,
        )
    else:
        await _store_bp_reading(
            connection,
            session_id=session_id,
            systolic=payload.systolic,
            diastolic=payload.diastolic,
            pulse_bpm=payload.pulse_bpm,
            measured_at=payload.measured_at,
            source=payload.source,
        )
    return {"session_id": str(session_id), "vitals": vitals}


@app.post("/vitals/blood-pressure/fetch", response_model=BloodPressureFetchResponse)
async def fetch_blood_pressure(
    request: Request,
    payload: BpFetchRequest | None = None,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Pull the latest reading from the Omron cuff over Bluetooth.

    Runs omblepy on the API host. Always returns 200 with a ``status``
    field so the kiosk UI can branch on failure modes (device not
    advertising, busy, ...) without an error-handling side channel.

    A fresh reading is persisted to ``bp_readings`` immediately — before
    the patient decides to continue — so the measurement survives even if
    they cancel the voice/chat flow right after measuring.
    """
    bp_service: BloodPressureService = request.app.state.bp_service
    try:
        reading = await bp_service.fetch_latest()
    except BloodPressureFetchError as exc:
        return BloodPressureFetchResponse(status=exc.code, message=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("Unexpected omblepy failure")
        return BloodPressureFetchResponse(status="error", message=str(exc))

    return await _persist_and_build_bp_response(
        bp_service, connection, reading, payload.session_id if payload else None
    )


async def _persist_and_build_bp_response(
    bp_service: BloodPressureService,
    connection: asyncpg.Connection,
    reading,
    session_id: UUID | None,
) -> BloodPressureFetchResponse:
    is_recent = bp_service.is_recent(reading)
    reading_id: UUID | None = None
    if is_recent:
        # Stale cuff history (is_recent=False) is reported to the UI but
        # not stored — only measurements taken at the kiosk go to the DB.
        try:
            reading_id = await _store_bp_reading(
                connection,
                session_id=session_id,
                systolic=reading.systolic,
                diastolic=reading.diastolic,
                pulse_bpm=reading.pulse_bpm,
                measured_at=reading.measured_at,
                irregular_heartbeat=reading.irregular_heartbeat,
                body_movement=reading.body_movement,
                source="device",
            )
        except Exception:  # noqa: BLE001 — reading display must not fail
            logger.exception("Failed to persist bp reading")

    return BloodPressureFetchResponse(
        status="ok",
        systolic=reading.systolic,
        diastolic=reading.diastolic,
        pulse_bpm=reading.pulse_bpm,
        measured_at=reading.measured_at,
        is_recent=is_recent,
        irregular_heartbeat=reading.irregular_heartbeat,
        body_movement=reading.body_movement,
        reading_id=reading_id,
    )


@app.post("/vitals/blood-pressure/watch", response_model=BloodPressureFetchResponse)
async def watch_blood_pressure(
    request: Request,
    payload: BpWatchRequest | None = None,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Long-poll: wait for the cuff's finished-measurement broadcast, then
    fetch and return the reading immediately.

    The cuff is silent while measuring and starts advertising the moment
    it finishes — that advertisement is the real "patient is done" signal,
    so the fetch begins ~1s after the measurement ends. Returns status
    ``not_seen`` when nothing appeared within ``timeout_seconds`` so the
    kiosk can re-arm without any dead time.
    """
    bp_service: BloodPressureService = request.app.state.bp_service
    timeout = payload.timeout_seconds if payload else 25.0
    try:
        reading = await bp_service.watch_and_fetch(timeout)
    except BloodPressureFetchError as exc:
        return BloodPressureFetchResponse(status=exc.code, message=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("Unexpected watch failure")
        return BloodPressureFetchResponse(status="error", message=str(exc))

    return await _persist_and_build_bp_response(
        bp_service, connection, reading, payload.session_id if payload else None
    )


@app.get("/admin/bp-device", response_model=BpDeviceStatusOut)
async def get_bp_device_status(
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "admin", "viewer")),
):
    """Current cuff configuration for the admin portal device manager."""
    bp_service: BloodPressureService = request.app.state.bp_service
    return BpDeviceStatusOut(
        device_name=settings.bp_device_name,
        device_mac=settings.bp_device_mac,
        configured=bool(settings.bp_device_mac),
        busy=bp_service.is_busy,
        supported_models=bp_service.supported_models(),
    )


@app.post("/admin/bp-device/scan", response_model=BpScanResponse)
async def scan_bp_devices(
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "admin")),
):
    """Sweep for nearby BLE devices (~6s) so the admin can pick the cuff.

    Mirrors omblepy's interactive selection table: likely Omron monitors
    are flagged and sorted first.
    """
    bp_service: BloodPressureService = request.app.state.bp_service
    try:
        devices = await bp_service.scan_devices()
    except BloodPressureFetchError as exc:
        return BpScanResponse(status="busy" if exc.code == "busy" else "error", message=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("BLE scan failed")
        return BpScanResponse(status="error", message=str(exc))
    return BpScanResponse(status="ok", devices=devices)


@app.post("/admin/bp-device/pair", response_model=BpPairResponse)
async def pair_bp_device(
    payload: BpPairRequest,
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "admin")),
):
    """Program the pairing key into the selected cuff and make it the
    active kiosk device (persists to .env, effective immediately)."""
    bp_service: BloodPressureService = request.app.state.bp_service
    try:
        await bp_service.pair_device(payload.mac, payload.device_name)
    except BloodPressureFetchError as exc:
        return BpPairResponse(status=exc.code, message=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("Unexpected pairing failure")
        return BpPairResponse(status="error", message=str(exc))
    return BpPairResponse(
        status="ok",
        device_name=settings.bp_device_name,
        device_mac=settings.bp_device_mac,
    )


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

    from app.services.ai.triage_payloads import assessment_status, severity_payload

    return ChatResponse(
        reply=result.reply,
        severity=severity_payload(result),
        assessment_status=assessment_status(result),
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
            "raw_text": result.raw_text,
            "body_location": None,
            "duration_text": None,
            "pain_score": result.pain_score,
            "pain_location": result.pain_location,
            "distress_score": result.distress_score,
            "distress_type": result.distress_type,
            "red_flags": result.red_flags,
        },
        contact=result.contact,
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
    Persistence and rule-engine overrides run
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
            body_location, duration_text, pain_score, pain_location,
            distress_score, distress_type, red_flags
        )
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10, $11::jsonb)
        RETURNING *
        """,
        session_id,
        payload.message_id,
        payload.raw_text,
        payload.normalized_symptoms,
        payload.body_location,
        payload.duration_text,
        payload.pain_score,
        payload.pain_location,
        payload.distress_score,
        payload.distress_type,
        payload.red_flags,
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
async def conversation_summary(
    _admin_user: dict = Depends(require_roles("super_admin", "viewer", "admin")),
    connection: asyncpg.Connection = Depends(get_connection),
):
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


@app.get("/admin/sessions/{session_id}/trace")
async def get_session_trace(
    session_id: UUID,
    _admin_user: dict = Depends(require_roles("admin", "super_admin", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Full AI decision trace for one session (SRS Explainability / F40).

    Returns the screening engine state (findings, slots, disposition with
    fired rules + manual citations) and the per-call ai_inference_audit
    timeline. Only available for sessions run by the screening engine v2.
    """

    state_row = await connection.fetchrow(
        """
        SELECT state, criteria_version_id, prompt_version, updated_at
        FROM screening_sessions WHERE session_id = $1
        """,
        session_id,
    )
    audit_rows = await connection.fetch(
        """
        SELECT turn_no, call_site, model_name, prompt_version, criteria_version_id,
               rules_trace, validator_result, ok, latency_ms, created_at
        FROM ai_inference_audit
        WHERE session_id = $1
        ORDER BY created_at ASC
        """,
        session_id,
    )
    if state_row is None and not audit_rows:
        raise HTTPException(
            status_code=404,
            detail="No screening-engine trace for this session",
        )

    engine_state = state_row["state"] if state_row else None
    if isinstance(engine_state, str):
        import json as _json

        engine_state = _json.loads(engine_state)
    return {
        "session_id": str(session_id),
        "criteria_version_id": (
            str(state_row["criteria_version_id"])
            if state_row and state_row["criteria_version_id"]
            else None
        ),
        "prompt_version": state_row["prompt_version"] if state_row else None,
        "updated_at": state_row["updated_at"] if state_row else None,
        "engine_state": engine_state,
        "audit": records_to_dicts(audit_rows),
    }


@app.get("/admin/reviews", response_model=list[AssessmentReviewOut])
async def list_assessment_reviews(
    status: str = "pending",
    _admin_user: dict = Depends(require_roles("admin", "super_admin")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    rows = await connection.fetch(
        """
        SELECT
            ar.*,
            reviewer.full_name AS reviewer_name,
            pd.name_en AS proposed_department_name_en,
            pd.name_th AS proposed_department_name_th,
            cd.name_en AS confirmed_department_name_en,
            cd.name_th AS confirmed_department_name_th,
            (s.metadata->>'patient_contact_requested')::boolean AS patient_contact_requested,
            NULLIF(s.metadata->>'patient_contact_phone', '') AS patient_contact_phone,
            NULLIF(s.metadata->>'patient_contact_preferred_time', '') AS patient_contact_preferred_time,
            NULLIF(s.metadata->>'patient_contact_relation', '') AS patient_contact_relation,
            s.metadata->'triage_classification'->'disposition_reasons' AS disposition_reasons
        FROM assessment_reviews ar
        JOIN sessions s ON s.id = ar.session_id
        LEFT JOIN admin_users reviewer ON reviewer.id = ar.reviewer_id
        LEFT JOIN departments pd ON pd.id = ar.proposed_department_id
        LEFT JOIN departments cd ON cd.id = ar.confirmed_department_id
        WHERE ($1 = 'all' OR ar.status::text = $1)
        ORDER BY ar.created_at DESC
        LIMIT 200
        """,
        status,
    )
    return records_to_dicts(rows)


@app.post("/admin/reviews/{assessment_id}/approve", response_model=AssessmentReviewOut)
async def approve_assessment_review(
    assessment_id: UUID,
    payload: AssessmentReviewApproveRequest,
    admin_user: dict = Depends(require_roles("admin", "super_admin")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    row = await connection.fetchrow(
        """
        UPDATE assessment_reviews
        SET status = 'approved',
            reviewer_id = $2,
            confirmed_department_id = COALESCE(confirmed_department_id, proposed_department_id),
            notes = $3,
            ai_assessment_score = $4,
            ai_assessment_scale = 10,
            reviewed_at = NOW(),
            updated_at = NOW()
        WHERE assessment_id = $1
        RETURNING session_id, confirmed_department_id
        """,
        assessment_id,
        admin_user["id"],
        payload.notes,
        payload.ai_assessment_score,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Assessment review not found")

    if row["confirmed_department_id"]:
        await connection.execute(
            """
            INSERT INTO department_recommendations (
                session_id, assessment_id, department_id, confidence, reason
            )
            VALUES ($1, $2, $3, $4, $5)
            """,
            row["session_id"],
            assessment_id,
            row["confirmed_department_id"],
            1.0,
            "Approved by OPD nurse review",
        )

    return await _serialize_review(connection, assessment_id)


@app.post("/admin/reviews/{assessment_id}/correct", response_model=AssessmentReviewOut)
async def correct_assessment_review(
    assessment_id: UUID,
    payload: AssessmentReviewCorrectRequest,
    admin_user: dict = Depends(require_roles("admin", "super_admin")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    review_before = await connection.fetchrow(
        """
        SELECT session_id, proposed_department_id
        FROM assessment_reviews
        WHERE assessment_id = $1
        """,
        assessment_id,
    )
    if review_before is None:
        raise HTTPException(status_code=404, detail="Assessment review not found")

    await connection.execute(
        """
        UPDATE assessment_reviews
        SET status = 'corrected',
            reviewer_id = $2,
            confirmed_department_id = $3,
            notes = $4,
            ai_assessment_score = $5,
            ai_assessment_scale = 10,
            reviewed_at = NOW(),
            updated_at = NOW()
        WHERE assessment_id = $1
        """,
        assessment_id,
        admin_user["id"],
        payload.confirmed_department_id,
        payload.reason,
        payload.ai_assessment_score,
    )

    await connection.execute(
        """
        INSERT INTO department_recommendations (
            session_id, assessment_id, department_id, confidence, reason
        )
        VALUES ($1, $2, $3, $4, $5)
        """,
        review_before["session_id"],
        assessment_id,
        payload.confirmed_department_id,
        1.0,
        "Corrected by OPD nurse review",
    )

    await connection.execute(
        """
        INSERT INTO routing_feedback (
            session_id,
            assessment_id,
            assessment_result_id,
            original_department_id,
            corrected_department_id,
            reported_by,
            nurse_user_id,
            reason,
            feedback_text
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        review_before["session_id"],
        assessment_id,
        None,
        review_before["proposed_department_id"],
        payload.confirmed_department_id,
        admin_user["id"],
        None,
        payload.reason,
        payload.reason,
    )

    return await _serialize_review(connection, assessment_id)


@app.get("/admin/feedback", response_model=list[RoutingFeedbackOut])
async def list_routing_feedback(
    _admin_user: dict = Depends(require_roles("admin", "super_admin")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    rows = await connection.fetch(
        """
        SELECT
            rf.*,
            corrected.name_en AS corrected_department_name_en,
            corrected.name_th AS corrected_department_name_th,
            reporter.full_name AS reporter_name
        FROM routing_feedback rf
        LEFT JOIN departments corrected ON corrected.id = rf.corrected_department_id
        LEFT JOIN admin_users reporter ON reporter.id = rf.reported_by
        ORDER BY rf.created_at DESC
        LIMIT 200
        """
    )
    return records_to_dicts(rows)


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
#     {"type": "end_of_turn"}        force end of caller turn (activity_end)
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
    requested_language = websocket.query_params.get("language", "en")
    language = requested_language if requested_language in {"en", "th"} else "en"

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
                db_pool=pool,
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
            while live_voice_service.should_keep_pipeline_open(session_id):
                try:
                    async for chunk in live_voice_service.run_live_pipeline(session_id):
                        if chunk:
                            await websocket.send_bytes(chunk)
                except WebSocketDisconnect:
                    # Client closed mid-stream; cancellation will tear down
                    # the receive task as well.
                    return
                except Exception:
                    logger.exception(
                        "Outbound voice pump failed for %s", session_id
                    )
                    return

                if live_voice_service.should_keep_pipeline_open(session_id):
                    await asyncio.sleep(0.05)

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
                    live_voice_service.end_user_turn(session_id)
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


# ── Doctor schedule endpoints ────────────────────────────────────────────────

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _doctor_row_to_out(row: dict, dept_row: dict | None = None) -> dict:
    return {
        **row,
        "department_name_en": dept_row["name_en"] if dept_row else None,
        "department_name_th": dept_row["name_th"] if dept_row else None,
    }


@app.get("/doctors", response_model=list[DoctorOut])
async def list_doctors(
    active_only: bool = True,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """List all doctors, optionally filtering by active status."""
    rows = await connection.fetch(
        """
        SELECT d.*, dept.name_en AS department_name_en, dept.name_th AS department_name_th
        FROM doctors d
        LEFT JOIN departments dept ON dept.id = d.department_id
        WHERE ($1 = FALSE OR d.is_active = TRUE)
        ORDER BY d.full_name ASC
        """,
        active_only,
    )
    return [dict(r) for r in rows]


@app.post("/doctors", response_model=DoctorOut, status_code=status.HTTP_201_CREATED)
async def create_doctor(
    payload: DoctorCreate,
    connection: asyncpg.Connection = Depends(get_connection),
    admin_user: dict = Depends(require_roles("super_admin", "admin")),
):
    """Create a new doctor profile. Requires admin or nurse role."""
    row = await connection.fetchrow(
        """
        INSERT INTO doctors (full_name, title, specialization, department_id, phone_ext, notes, is_active, created_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        payload.full_name,
        payload.title,
        payload.specialization,
        payload.department_id,
        payload.phone_ext,
        payload.notes,
        payload.is_active,
        admin_user["id"],
    )
    dept_row = None
    if row["department_id"]:
        dept_row = await connection.fetchrow(
            "SELECT name_en, name_th FROM departments WHERE id = $1", row["department_id"]
        )
    return {**dict(row), "department_name_en": dept_row["name_en"] if dept_row else None,
            "department_name_th": dept_row["name_th"] if dept_row else None}


@app.get("/doctors/{doctor_id}", response_model=DoctorWithSchedulesOut)
async def get_doctor(
    doctor_id: UUID,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Get a doctor with their full weekly schedule."""
    row = await connection.fetchrow(
        """
        SELECT d.*, dept.name_en AS department_name_en, dept.name_th AS department_name_th
        FROM doctors d
        LEFT JOIN departments dept ON dept.id = d.department_id
        WHERE d.id = $1
        """,
        doctor_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Doctor not found")
    schedules = await connection.fetch(
        "SELECT * FROM doctor_schedules WHERE doctor_id = $1 ORDER BY schedule_date, start_time",
        doctor_id,
    )
    return {**dict(row), "schedules": [dict(s) for s in schedules]}


@app.patch("/doctors/{doctor_id}", response_model=DoctorOut)
async def update_doctor(
    doctor_id: UUID,
    payload: DoctorUpdate,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin", "admin")),
):
    """Update a doctor profile. Requires admin or nurse role."""
    existing = await connection.fetchrow("SELECT * FROM doctors WHERE id = $1", doctor_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Doctor not found")
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    set_clauses = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(updates))
    values = list(updates.values())
    row = await connection.fetchrow(
        f"UPDATE doctors SET {set_clauses} WHERE id = $1 RETURNING *",
        doctor_id, *values,
    )
    dept_row = None
    if row["department_id"]:
        dept_row = await connection.fetchrow(
            "SELECT name_en, name_th FROM departments WHERE id = $1", row["department_id"]
        )
    return {**dict(row), "department_name_en": dept_row["name_en"] if dept_row else None,
            "department_name_th": dept_row["name_th"] if dept_row else None}


@app.get("/doctors/{doctor_id}/schedules", response_model=list[DoctorScheduleOut])
async def list_doctor_schedules(
    doctor_id: UUID,
    from_date: str | None = None,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """List schedule entries for a doctor, optionally from a start date."""
    from datetime import date as date_type
    parsed_from: date_type | None = None
    if from_date:
        try:
            parsed_from = date_type.fromisoformat(from_date)
        except ValueError:
            pass
    rows = await connection.fetch(
        """
        SELECT * FROM doctor_schedules
        WHERE doctor_id = $1
          AND ($2::date IS NULL OR schedule_date >= $2)
        ORDER BY schedule_date, start_time
        """,
        doctor_id,
        parsed_from,
    )
    return [dict(r) for r in rows]


@app.post(
    "/doctors/{doctor_id}/schedules",
    response_model=DoctorScheduleOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_doctor_schedule(
    doctor_id: UUID,
    payload: DoctorScheduleCreate,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin", "admin")),
):
    """Add a date-specific schedule entry for a doctor."""
    doctor = await connection.fetchrow("SELECT id FROM doctors WHERE id = $1", doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    try:
        row = await connection.fetchrow(
            """
            INSERT INTO doctor_schedules
                (doctor_id, schedule_date, start_time, end_time,
                 break_start, break_end, room, slot_label, is_available, notes)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (doctor_id, schedule_date, start_time)
            DO UPDATE SET
                end_time     = EXCLUDED.end_time,
                break_start  = EXCLUDED.break_start,
                break_end    = EXCLUDED.break_end,
                room         = EXCLUDED.room,
                slot_label   = EXCLUDED.slot_label,
                is_available = EXCLUDED.is_available,
                notes        = EXCLUDED.notes,
                updated_at   = NOW()
            RETURNING *
            """,
            doctor_id,
            payload.schedule_date,
            payload.start_time,
            payload.end_time,
            payload.break_start,
            payload.break_end,
            payload.room,
            payload.slot_label,
            payload.is_available,
            payload.notes,
        )
    except asyncpg.CheckViolationError as exc:
        raise HTTPException(status_code=400, detail="end_time must be after start_time") from exc
    return dict(row)


@app.patch("/doctors/{doctor_id}/schedules/{schedule_id}", response_model=DoctorScheduleOut)
async def update_doctor_schedule(
    doctor_id: UUID,
    schedule_id: UUID,
    payload: DoctorScheduleCreate,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin", "admin")),
):
    """Update an existing schedule entry."""
    row = await connection.fetchrow(
        "SELECT id FROM doctor_schedules WHERE id = $1 AND doctor_id = $2",
        schedule_id, doctor_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Schedule entry not found")
    updated = await connection.fetchrow(
        """
        UPDATE doctor_schedules
        SET schedule_date=$2, start_time=$3, end_time=$4,
            break_start=$5, break_end=$6, room=$7,
            slot_label=$8, is_available=$9, notes=$10
        WHERE id = $1
        RETURNING *
        """,
        schedule_id,
        payload.schedule_date,
        payload.start_time,
        payload.end_time,
        payload.break_start,
        payload.break_end,
        payload.room,
        payload.slot_label,
        payload.is_available,
        payload.notes,
    )
    return dict(updated)


@app.delete("/doctors/{doctor_id}/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doctor_schedule(
    doctor_id: UUID,
    schedule_id: UUID,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin", "admin")),
):
    """Delete a schedule entry."""
    result = await connection.execute(
        "DELETE FROM doctor_schedules WHERE id = $1 AND doctor_id = $2",
        schedule_id, doctor_id,
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Schedule entry not found")


@app.get("/schedules/available", response_model=list[DoctorWithSchedulesOut])
async def get_available_doctors(
    schedule_date: str | None = None,
    department_id: UUID | None = None,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """
    Return doctors with their available schedule entries for a given date
    (defaults to today). Old entries are never deleted — only today's are surfaced.
    Used by the AI to answer patient availability queries.
    """
    from datetime import date as date_type
    if schedule_date:
        try:
            target_date = date_type.fromisoformat(schedule_date)
        except ValueError:
            target_date = date_type.today()
    else:
        target_date = date_type.today()

    rows = await connection.fetch(
        """
        SELECT d.*, dept.name_en AS department_name_en, dept.name_th AS department_name_th
        FROM doctors d
        LEFT JOIN departments dept ON dept.id = d.department_id
        WHERE d.is_active = TRUE
          AND ($1::uuid IS NULL OR d.department_id = $1)
          AND EXISTS (
              SELECT 1 FROM doctor_schedules s
              WHERE s.doctor_id = d.id
                AND s.schedule_date = $2
                AND s.is_available = TRUE
          )
        ORDER BY d.full_name ASC
        """,
        department_id,
        target_date,
    )
    result = []
    for doctor in rows:
        schedules = await connection.fetch(
            """
            SELECT * FROM doctor_schedules
            WHERE doctor_id = $1 AND schedule_date = $2 AND is_available = TRUE
            ORDER BY start_time
            """,
            doctor["id"],
            target_date,
        )
        result.append({**dict(doctor), "schedules": [dict(s) for s in schedules]})
    return result


# ── Disease Surveillance ──────────────────────────────────────────────────────

@app.get("/admin/surveillance", response_model=SurveillanceSummaryOut)
async def get_surveillance_summary(
    days: int = 7,
    _admin_user: dict = Depends(require_roles("super_admin", "admin", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Aggregate disease-surveillance data for the admin outbreak dashboard."""

    # Total classification events in the window
    total = await connection.fetchval(
        "SELECT COUNT(*) FROM disease_surveillance WHERE reported_at >= NOW() - INTERVAL '1 day' * $1",
        days,
    ) or 0

    # Top symptom keywords (unnested from the array)
    top_rows = await connection.fetch(
        """
        SELECT keyword, COUNT(*) AS count
        FROM disease_surveillance, UNNEST(symptom_keywords) AS keyword
        WHERE reported_at >= NOW() - INTERVAL '1 day' * $1
          AND keyword <> ''
        GROUP BY keyword
        ORDER BY count DESC
        LIMIT 20
        """,
        days,
    )

    # Symptoms by area
    area_rows = await connection.fetch(
        """
        SELECT COALESCE(location_area, 'Unknown') AS area, keyword, COUNT(*) AS count
        FROM disease_surveillance, UNNEST(symptom_keywords) AS keyword
        WHERE reported_at >= NOW() - INTERVAL '1 day' * $1
          AND keyword <> ''
        GROUP BY area, keyword
        ORDER BY area, count DESC
        """,
        days,
    )

    # Daily case counts
    trend_rows = await connection.fetch(
        """
        SELECT DATE(reported_at AT TIME ZONE 'UTC') AS date, COUNT(*) AS count
        FROM disease_surveillance
        WHERE reported_at >= NOW() - INTERVAL '1 day' * $1
        GROUP BY date
        ORDER BY date ASC
        """,
        days,
    )

    # Severity distribution
    severity_rows = await connection.fetch(
        """
        SELECT severity_level, COUNT(*) AS count
        FROM disease_surveillance
        WHERE reported_at >= NOW() - INTERVAL '1 day' * $1
        GROUP BY severity_level
        ORDER BY count DESC
        """,
        days,
    )

    # Outbreak alerts: keywords with 2× or more increase vs previous period
    alert_rows = await connection.fetch(
        """
        WITH recent AS (
            SELECT keyword, COALESCE(location_area, 'Unknown') AS area, COUNT(*) AS cnt
            FROM disease_surveillance, UNNEST(symptom_keywords) AS keyword
            WHERE reported_at >= NOW() - INTERVAL '1 day' * $1 AND keyword <> ''
            GROUP BY keyword, area
        ),
        previous AS (
            SELECT keyword, COALESCE(location_area, 'Unknown') AS area, COUNT(*) AS cnt
            FROM disease_surveillance, UNNEST(symptom_keywords) AS keyword
            WHERE reported_at >= NOW() - INTERVAL '1 day' * $2
              AND reported_at < NOW() - INTERVAL '1 day' * $1 AND keyword <> ''
            GROUP BY keyword, area
        )
        SELECT r.keyword, r.area,
               r.cnt  AS recent_count,
               COALESCE(p.cnt, 0) AS previous_count,
               ROUND(
                   CASE WHEN COALESCE(p.cnt, 0) = 0 THEN 100.0
                        ELSE (r.cnt - p.cnt)::NUMERIC / p.cnt * 100
                   END, 1
               ) AS increase_pct
        FROM recent r
        LEFT JOIN previous p USING (keyword, area)
        WHERE r.cnt >= 3
          AND (COALESCE(p.cnt, 0) = 0 OR r.cnt >= p.cnt * 2)
        ORDER BY increase_pct DESC
        LIMIT 10
        """,
        days,
        days,
    )

    return SurveillanceSummaryOut(
        days=days,
        total_reports=total,
        top_symptoms=[{"keyword": r["keyword"], "count": r["count"]} for r in top_rows],
        by_area=[{"area": r["area"], "keyword": r["keyword"], "count": r["count"]} for r in area_rows],
        daily_trend=[{"date": str(r["date"]), "count": r["count"]} for r in trend_rows],
        severity_distribution=[{"severity_level": r["severity_level"], "count": r["count"]} for r in severity_rows],
        outbreak_alerts=[
            {
                "keyword": r["keyword"],
                "area": r["area"],
                "recent_count": r["recent_count"],
                "previous_count": r["previous_count"],
                "increase_pct": float(r["increase_pct"]),
            }
            for r in alert_rows
        ],
    )


# ── Hybrid RAG triage endpoint ────────────────────────────────────────────────

class _RagTriageRequest(BaseModel):
    """Request body for the hybrid RAG triage endpoint."""
    content: str
    language: str = "th"
    session_id: str | None = None


@app.post("/triage/rag")
async def rag_triage(
    payload: _RagTriageRequest,
    connection: asyncpg.Connection = Depends(get_connection),
) -> JSONResponse:
    """Run the hybrid Rule Engine + RAG triage pipeline.

    Layer 1 evaluates hard rules (no LLM).  Layer 2 queries the official
    triage manual via pgvector and produces a structured decision.
    ``requires_nurse_review`` is always ``true``.
    """
    from app.services.triage_engine import run_triage

    triggers_rows = await connection.fetch(
        "SELECT * FROM emergency_triggers WHERE is_active = TRUE ORDER BY priority ASC"
    )
    rules_rows = await connection.fetch(
        "SELECT * FROM routing_rules WHERE is_active = TRUE ORDER BY priority ASC"
    )
    patient_input = {
        "content": payload.content,
        "language": payload.language,
        "session_id": payload.session_id or "anonymous",
    }
    result = await run_triage(
        patient_input=patient_input,
        emergency_triggers=[dict(r) for r in triggers_rows],
        routing_rules=[dict(r) for r in rules_rows],
    )
    return JSONResponse(content=result)


# ── Triage manual PDF upload ──────────────────────────────────────────────────

async def _run_ingest_task(
    *,
    pool: asyncpg.Pool,
    upload_id: str,
    pdf_path: str,
) -> None:
    """Background task: clear old embeddings, ingest new PDF, update DB record."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from app.services.ai.rag_ingest import ingest_replace

    async with pool.acquire() as conn:
        try:
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor(max_workers=1) as executor:
                chunks = await loop.run_in_executor(
                    executor,
                    lambda: ingest_replace(pdf_path),
                )
            await conn.execute(
                """UPDATE triage_manual_uploads
                      SET status='ready', chunks_count=$1, completed_at=NOW()
                    WHERE id=$2""",
                chunks,
                upload_id,
            )
            logger.info("Triage manual ingested: %d chunks (upload_id=%s)", chunks, upload_id)
        except Exception as exc:
            logger.exception("Triage manual ingest failed for upload_id=%s", upload_id)
            await conn.execute(
                """UPDATE triage_manual_uploads
                      SET status='failed', error_message=$1, completed_at=NOW()
                    WHERE id=$2""",
                str(exc)[:500],
                upload_id,
            )


@app.post("/admin/triage-manual/upload")
async def upload_triage_manual(
    request: Request,
    file: UploadFile = File(..., description="Hospital triage manual PDF"),
    connection: asyncpg.Connection = Depends(get_connection),
    admin_user: dict = Depends(require_roles("super_admin", "admin")),
) -> JSONResponse:
    """Upload a new triage manual PDF and trigger background RAG ingestion.

    Replaces any previously uploaded manual.  The old pgvector embeddings are
    deleted automatically before the new ones are stored.

    Returns a JSON object with the upload ``id`` and initial ``status``.
    """
    import os

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Save to a fixed path so the RAG ingest script can find it
    save_path = getattr(settings, "triage_manual_path", "app/data/triage_manual.pdf")
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

    content = await file.read()
    file_size = len(content)

    if file_size == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if file_size > 50 * 1024 * 1024:  # 50 MB guard
        raise HTTPException(status_code=413, detail="File too large (max 50 MB).")

    with open(save_path, "wb") as fh:
        fh.write(content)

    # Insert upload record
    uploader = admin_user.get("email") or admin_user.get("id") or "unknown"
    row = await connection.fetchrow(
        """INSERT INTO triage_manual_uploads
               (original_filename, file_size_bytes, status, uploaded_by)
           VALUES ($1, $2, 'processing', $3)
           RETURNING id, status, uploaded_at""",
        file.filename,
        file_size,
        str(uploader),
    )

    upload_id = str(row["id"])

    # Kick off background ingest (non-blocking)
    pool: asyncpg.Pool = request.app.state.db_pool
    asyncio.create_task(
        _run_ingest_task(pool=pool, upload_id=upload_id, pdf_path=save_path)
    )

    return JSONResponse(
        status_code=202,
        content={
            "id": upload_id,
            "status": "processing",
            "original_filename": file.filename,
            "file_size_bytes": file_size,
            "uploaded_at": row["uploaded_at"].isoformat(),
            "message": "Upload received. Ingestion is running in the background.",
        },
    )


@app.get("/admin/triage-manual/status")
async def get_triage_manual_status(
    connection: asyncpg.Connection = Depends(get_connection),
    admin_user: dict = Depends(require_roles("super_admin", "admin")),
) -> JSONResponse:
    """Return the latest triage manual upload record.

    The frontend polls this endpoint after uploading to track ingest progress.
    Returns ``null`` when no manual has been uploaded yet.
    """
    row = await connection.fetchrow(
        """SELECT id, original_filename, file_size_bytes, chunks_count,
                  status, error_message, uploaded_by, uploaded_at, completed_at
             FROM triage_manual_uploads
            ORDER BY uploaded_at DESC
            LIMIT 1"""
    )
    if row is None:
        return JSONResponse(content=None)

    return JSONResponse(content={
        "id": str(row["id"]),
        "original_filename": row["original_filename"],
        "file_size_bytes": row["file_size_bytes"],
        "chunks_count": row["chunks_count"],
        "status": row["status"],
        "error_message": row["error_message"],
        "uploaded_by": row["uploaded_by"],
        "uploaded_at": row["uploaded_at"].isoformat() if row["uploaded_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
    })


# ── Screening criteria governance (SRS F31-F35) ───────────────────────────────
#
# Lifecycle: upload → draft (LLM extraction merges into the active payload in
# the background) → head-nurse edit (PUT) → submit → approve → activate.
# Activating retires the current active version in the same transaction;
# activating a retired version is the rollback path. Sessions pin the version
# they started with, so activation never changes an in-flight conversation.

CRITERIA_UPLOAD_DIR = "app/data/uploads/criteria"
CRITERIA_UPLOAD_SUFFIXES = {".pdf", ".txt", ".md", ".csv", ".docx"}
_CRITERIA_PROCESSING_PREFIX = "Extracting"


def _jsonb(value):
    """asyncpg returns JSONB as str unless a codec is registered."""
    return json.loads(value) if isinstance(value, str) else value


def _criteria_version_summary(row) -> dict:
    change_summary = row["change_summary"] or ""
    return {
        "id": str(row["id"]),
        "version_no": row["version_no"],
        "status": row["status"],
        "change_summary": change_summary,
        "processing": change_summary.startswith(_CRITERIA_PROCESSING_PREFIX),
        "uploaded_by": row["uploaded_by"],
        "reviewed_by": row["reviewed_by"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
        "activated_at": row["activated_at"].isoformat() if row["activated_at"] else None,
    }


async def _active_criteria_payload(conn: asyncpg.Connection) -> dict:
    """Raw payload of the active version, or the bundled seed on a fresh DB."""
    row = await conn.fetchrow(
        "SELECT criteria FROM screening_criteria_versions WHERE status = 'active'"
    )
    if row is not None:
        return _jsonb(row["criteria"])
    from app.services.screening.rules.criteria_store import SEED_CRITERIA_PATH

    return json.loads(SEED_CRITERIA_PATH.read_text(encoding="utf-8"))


async def _run_criteria_extract_task(
    *,
    pool: asyncpg.Pool,
    version_id: str,
    file_path: str,
    filename: str,
) -> None:
    """Background task: extract rules from the uploaded document into the draft."""
    from app.services.screening.criteria_upload import extract_criteria_draft
    from app.services.screening.model_adapter import build_chat_model

    try:
        async with pool.acquire() as conn:
            base = await _active_criteria_payload(conn)
        model = build_chat_model(settings)
        draft, warnings = await extract_criteria_draft(
            file_path=file_path,
            filename=filename,
            model=model,
            base_payload=base,
        )
        summary = f"Extracted from {filename}"
        if warnings:
            summary += f" — {len(warnings)} warning(s): " + "; ".join(warnings[:10])
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE screening_criteria_versions
                      SET criteria = $1::jsonb, change_summary = $2
                    WHERE id = $3""",
                json.dumps(draft, ensure_ascii=False),
                summary[:4000],
                UUID(version_id),
            )
        logger.info("Criteria extraction complete for version %s", version_id)
    except Exception as exc:
        logger.exception("Criteria extraction failed for version %s", version_id)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """UPDATE screening_criteria_versions
                          SET change_summary = $1 WHERE id = $2""",
                    f"Extraction failed ({filename}): {exc}"[:2000],
                    UUID(version_id),
                )
        except Exception:
            logger.exception("Could not record extraction failure for %s", version_id)


@app.post("/admin/criteria/upload")
async def upload_screening_criteria(
    request: Request,
    file: UploadFile = File(..., description="Screening criteria document (PDF/TXT/MD/CSV/DOCX)"),
    connection: asyncpg.Connection = Depends(get_connection),
    admin_user: dict = Depends(require_roles("super_admin", "admin")),
) -> JSONResponse:
    """Upload a screening-criteria document and create a draft version.

    The draft starts as a copy of the currently active criteria; a background
    LLM extraction merges rules found in the document into it. The draft is
    then reviewed/edited before submit → approve → activate.
    """
    import os
    from pathlib import Path as _Path
    from uuid import uuid4

    suffix = _Path(file.filename or "").suffix.lower()
    if suffix not in CRITERIA_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {suffix or '(none)'}; "
                   f"accepted: {', '.join(sorted(CRITERIA_UPLOAD_SUFFIXES))}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB).")

    os.makedirs(CRITERIA_UPLOAD_DIR, exist_ok=True)
    save_path = os.path.join(CRITERIA_UPLOAD_DIR, f"{uuid4()}{suffix}")
    with open(save_path, "wb") as fh:
        fh.write(content)

    base = await _active_criteria_payload(connection)
    uploader = admin_user.get("email") or admin_user.get("id") or "unknown"
    row = await connection.fetchrow(
        """
        INSERT INTO screening_criteria_versions
            (version_no, status, criteria, change_summary, uploaded_by)
        VALUES (
            (SELECT COALESCE(MAX(version_no), 0) + 1 FROM screening_criteria_versions),
            'draft', $1::jsonb, $2, $3
        )
        RETURNING id, version_no, created_at
        """,
        json.dumps(base, ensure_ascii=False),
        f"{_CRITERIA_PROCESSING_PREFIX} rules from {file.filename}…",
        str(uploader),
    )
    version_id = str(row["id"])

    pool: asyncpg.Pool = request.app.state.db_pool
    asyncio.create_task(
        _run_criteria_extract_task(
            pool=pool,
            version_id=version_id,
            file_path=save_path,
            filename=file.filename or f"upload{suffix}",
        )
    )

    return JSONResponse(
        status_code=202,
        content={
            "id": version_id,
            "version_no": row["version_no"],
            "status": "draft",
            "processing": True,
            "created_at": row["created_at"].isoformat(),
            "message": "Upload received. Rule extraction is running in the background.",
        },
    )


@app.get("/admin/criteria/versions")
async def list_criteria_versions(
    _admin_user: dict = Depends(require_roles("super_admin", "admin", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    rows = await connection.fetch(
        """
        SELECT id, version_no, status, change_summary, uploaded_by, reviewed_by,
               created_at, reviewed_at, activated_at
        FROM screening_criteria_versions
        ORDER BY version_no DESC
        """
    )
    return [_criteria_version_summary(row) for row in rows]


@app.get("/admin/criteria/versions/{version_id}")
async def get_criteria_version_detail(
    version_id: UUID,
    _admin_user: dict = Depends(require_roles("super_admin", "admin", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    from app.services.screening.criteria_upload import validation_errors

    row = await connection.fetchrow(
        "SELECT * FROM screening_criteria_versions WHERE id = $1", version_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Criteria version not found")
    payload = _jsonb(row["criteria"])
    result = _criteria_version_summary(row)
    result["criteria"] = payload
    result["validation_errors"] = validation_errors(payload)
    return result


@app.get("/admin/criteria/versions/{version_id}/diff")
async def diff_criteria_version(
    version_id: UUID,
    against: UUID | None = Query(
        None, description="Version to compare against (default: the active version)"
    ),
    _admin_user: dict = Depends(require_roles("super_admin", "admin", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Section-level diff (added/removed/changed rule ids) vs another version."""
    from app.services.screening.criteria_upload import diff_criteria

    row = await connection.fetchrow(
        "SELECT criteria FROM screening_criteria_versions WHERE id = $1", version_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Criteria version not found")

    if against is not None:
        base_row = await connection.fetchrow(
            "SELECT id, criteria FROM screening_criteria_versions WHERE id = $1",
            against,
        )
        if base_row is None:
            raise HTTPException(status_code=404, detail="Comparison version not found")
        base_payload = _jsonb(base_row["criteria"])
        base_id = str(base_row["id"])
    else:
        base_payload = await _active_criteria_payload(connection)
        base_id = "active"

    return {
        "version_id": str(version_id),
        "against": base_id,
        "diff": diff_criteria(base_payload, _jsonb(row["criteria"])),
    }


@app.put("/admin/criteria/versions/{version_id}")
async def edit_criteria_version(
    version_id: UUID,
    criteria: dict = Body(..., description="Full criteria JSON document"),
    _admin_user: dict = Depends(require_roles("super_admin", "admin")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Replace a draft's criteria JSON (the pressure valve for imperfect extraction).

    Saves even when the document has validation errors — they are returned so
    the editor can fix them iteratively — but submit/activate require a clean
    document.
    """
    from app.services.screening.criteria_upload import validation_errors

    row = await connection.fetchrow(
        "SELECT status FROM screening_criteria_versions WHERE id = $1", version_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Criteria version not found")
    if row["status"] not in ("draft", "pending_review"):
        raise HTTPException(
            status_code=409,
            detail=f"Only draft/pending_review versions are editable (status: {row['status']})",
        )

    await connection.execute(
        "UPDATE screening_criteria_versions SET criteria = $1::jsonb WHERE id = $2",
        json.dumps(criteria, ensure_ascii=False),
        version_id,
    )
    errors = validation_errors(criteria)
    return {"id": str(version_id), "saved": True, "validation_errors": errors}


async def _criteria_status_transition(
    connection: asyncpg.Connection,
    version_id: UUID,
    *,
    from_statuses: tuple[str, ...],
    to_status: str,
    reviewer: str | None = None,
) -> dict:
    row = await connection.fetchrow(
        "SELECT status, criteria FROM screening_criteria_versions WHERE id = $1",
        version_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Criteria version not found")
    if row["status"] not in from_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move {row['status']} → {to_status}; "
                   f"requires status in {list(from_statuses)}",
        )

    from app.services.screening.criteria_upload import validation_errors

    errors = validation_errors(_jsonb(row["criteria"]))
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Criteria document is invalid", "errors": errors[:20]},
        )

    if to_status == "active":
        async with connection.transaction():
            await connection.execute(
                """UPDATE screening_criteria_versions
                      SET status = 'retired' WHERE status = 'active'"""
            )
            await connection.execute(
                """UPDATE screening_criteria_versions
                      SET status = 'active', activated_at = NOW() WHERE id = $1""",
                version_id,
            )
    elif reviewer is not None:
        await connection.execute(
            """UPDATE screening_criteria_versions
                  SET status = $1, reviewed_by = $2, reviewed_at = NOW()
                WHERE id = $3""",
            to_status,
            reviewer,
            version_id,
        )
    else:
        await connection.execute(
            "UPDATE screening_criteria_versions SET status = $1 WHERE id = $2",
            to_status,
            version_id,
        )
    return {"id": str(version_id), "status": to_status}


@app.post("/admin/criteria/versions/{version_id}/submit")
async def submit_criteria_version(
    version_id: UUID,
    _admin_user: dict = Depends(require_roles("super_admin", "admin")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    return await _criteria_status_transition(
        connection, version_id, from_statuses=("draft",), to_status="pending_review"
    )


@app.post("/admin/criteria/versions/{version_id}/approve")
async def approve_criteria_version(
    version_id: UUID,
    admin_user: dict = Depends(require_roles("super_admin", "admin")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    reviewer = str(admin_user.get("email") or admin_user.get("id") or "unknown")
    return await _criteria_status_transition(
        connection,
        version_id,
        from_statuses=("pending_review",),
        to_status="approved",
        reviewer=reviewer,
    )


@app.post("/admin/criteria/versions/{version_id}/activate")
async def activate_criteria_version(
    version_id: UUID,
    _admin_user: dict = Depends(require_roles("super_admin", "admin")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Activate an approved version. Activating a retired version = rollback."""
    return await _criteria_status_transition(
        connection,
        version_id,
        from_statuses=("approved", "retired"),
        to_status="active",
    )


@app.get("/admin/ai-metrics")
async def get_ai_metrics(
    date_from: str | None = Query(None, alias="from", description="ISO date/datetime lower bound"),
    date_to: str | None = Query(None, alias="to", description="ISO date/datetime upper bound"),
    _admin_user: dict = Depends(require_roles("super_admin", "admin", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Aggregate AI transparency metrics over ai_inference_audit (SRS F40).

    Feeds the head-nurse governance panel: call volumes/ok-rates/latency per
    LLM call site, dispositions by level and department, validator violation
    counts, and escalation totals.
    """

    def _parse_bound(raw: str | None, name: str):
        if raw is None:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid {name} datetime: {raw}"
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    bounds = []
    clauses = []
    lower = _parse_bound(date_from, "from")
    if lower is not None:
        bounds.append(lower)
        clauses.append(f"created_at >= ${len(bounds)}")
    upper = _parse_bound(date_to, "to")
    if upper is not None:
        bounds.append(upper)
        clauses.append(f"created_at <= ${len(bounds)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    call_sites = await connection.fetch(
        f"""
        SELECT call_site,
               COUNT(*) AS calls,
               COUNT(*) FILTER (WHERE ok) AS ok_calls,
               ROUND(AVG(latency_ms) FILTER (WHERE latency_ms IS NOT NULL)) AS avg_latency_ms
        FROM ai_inference_audit
        {where}
        GROUP BY call_site
        ORDER BY call_site
        """,
        *bounds,
    )
    dispositions = await connection.fetch(
        f"""
        SELECT rules_trace->>'level' AS level,
               rules_trace->>'department_code' AS department_code,
               COUNT(*) AS count
        FROM ai_inference_audit
        {where + (' AND ' if where else 'WHERE ')} call_site = 'disposition'
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        *bounds,
    )
    violations = await connection.fetch(
        f"""
        SELECT violation, COUNT(*) AS count
        FROM ai_inference_audit,
             LATERAL jsonb_array_elements_text(validator_result) AS violation
        {where + (' AND ' if where else 'WHERE ')} validator_result IS NOT NULL
        GROUP BY violation
        ORDER BY count DESC
        """,
        *bounds,
    )
    totals_row = await connection.fetchrow(
        f"""
        SELECT
            COUNT(DISTINCT session_id) AS sessions,
            COUNT(*) FILTER (WHERE call_site = 'escalation') AS escalations,
            COUNT(*) FILTER (WHERE call_site = 'extraction' AND NOT ok) AS extraction_failures,
            COUNT(*) FILTER (WHERE call_site = 'disposition') AS dispositions
        FROM ai_inference_audit
        {where}
        """,
        *bounds,
    )

    return {
        "from": lower.isoformat() if lower else None,
        "to": upper.isoformat() if upper else None,
        "totals": dict(totals_row) if totals_row else {},
        "call_sites": [
            {
                "call_site": r["call_site"],
                "calls": r["calls"],
                "ok_calls": r["ok_calls"],
                "ok_rate": round(r["ok_calls"] / r["calls"], 4) if r["calls"] else None,
                "avg_latency_ms": int(r["avg_latency_ms"]) if r["avg_latency_ms"] is not None else None,
            }
            for r in call_sites
        ],
        "dispositions": [
            {
                "level": int(r["level"]) if r["level"] is not None else None,
                "department_code": r["department_code"],
                "count": r["count"],
            }
            for r in dispositions
        ],
        "validator_violations": [
            {"violation": r["violation"], "count": r["count"]} for r in violations
        ],
    }
