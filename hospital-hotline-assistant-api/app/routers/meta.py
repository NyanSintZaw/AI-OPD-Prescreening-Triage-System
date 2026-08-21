import logging
import asyncpg
from fastapi import (
    Depends,
)
from app.config import settings
from app.database import get_connection

logger = logging.getLogger(__name__)

from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "status": "running",
        "docs": "/docs",
    }

@router.get("/health")
async def health(connection: asyncpg.Connection = Depends(get_connection)) -> dict:
    await connection.fetchval("SELECT 1")
    return {
        "status": "ok",
        "environment": settings.environment,
        # Which brain is actually serving this booth — the question you ask
        # first when a deployment behaves unexpectedly.
        "ai": settings.ai_mode_summary,
    }

