import asyncio
import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import create_pool
from app.services import TriageService
from app.services.blood_pressure import BloodPressureService
from app.services.google_stt import GoogleSttClient
from app.services.google_tts import GoogleTtsClient
from app.services.notification_service import MockNotificationService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = await create_pool()
    app.state.admin_tokens = {}
    notifier = MockNotificationService()
    # The deterministic screening engine (LangGraph) is the only engine.
    from app.services.screening.engine import make_triage_engine

    triage_engine = make_triage_engine(settings, pool=app.state.db_pool)
    # HIS adapter: his_mode="http" talks to the hospital HIS (or the
    # standalone hospital-his-mock service); otherwise a logging mock.
    from app.services.screening.his import build_his_adapter

    app.state.his_adapter = build_his_adapter(settings)
    app.state.triage_service = TriageService(
        notifier=notifier,
        triage_engine=triage_engine,
        his_adapter=app.state.his_adapter,
    )
    app.state.tts_client = GoogleTtsClient()
    app.state.stt_client = GoogleSttClient()
    # Voice runs turn-by-turn through the same screening pipeline as text
    # chat (STT → process_chat_stream → TTS), so the deterministic engine
    # controls voice too. Owns the per-call WebSocket state for /ws/voice.
    from app.services.screening.voice_bridge import TurnVoiceService

    app.state.live_voice_service = TurnVoiceService(
        triage_service=app.state.triage_service,
        stt_client=app.state.stt_client,
        tts_client=app.state.tts_client,
        # Getter: the admin HIS-connection endpoints swap the adapter at
        # runtime; the spoken history intake must write to the current one.
        his_adapter_getter=lambda: app.state.his_adapter,
    )
    app.state.rag_prewarm_task = None
    if settings.rag_query_prewarm_on_startup:
        from app.services.ai.rag_query import start_rag_query_engine_prewarm

        app.state.rag_prewarm_task = start_rag_query_engine_prewarm()
    # Warm the screening LLM client (auth token + connection) so the first
    # patient turn isn't slow. Best-effort background task.
    app.state.model_prewarm_task = asyncio.create_task(triage_engine.prewarm())
    # Kiosk-side Omron cuff reader (omblepy subprocess wrapper).
    app.state.bp_service = BloodPressureService()
    # Kiosk-side BLE thermometer (standard Health Thermometer Service).
    from app.services.thermometer import ThermometerService

    app.state.temp_service = ThermometerService()
    try:
        yield
    finally:
        for attr in ("rag_prewarm_task", "model_prewarm_task"):
            prewarm_task = getattr(app.state, attr, None)
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


# Routers, in (approximately) the original registration order of main.py so
# the OpenAPI path listing stays stable for the docs/Bruno generator.
from app.routers import (  # noqa: E402
    admin_analytics,
    admin_criteria,
    admin_his,
    admin_reviews,
    admin_users,
    meta,
    reference,
    session_clinical,
    sessions,
    speech,
    vitals,
    voice_ws,
)

app.include_router(meta.router)
app.include_router(admin_users.router)
app.include_router(sessions.router)
app.include_router(vitals.router)
app.include_router(session_clinical.router)
app.include_router(reference.router)
app.include_router(speech.router)
app.include_router(admin_analytics.router)
app.include_router(admin_reviews.router)
app.include_router(admin_his.router)
app.include_router(voice_ws.router)
app.include_router(admin_criteria.router)
