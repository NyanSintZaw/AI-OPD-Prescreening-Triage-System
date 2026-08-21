"""Session-level vitals endpoints shared by the devices and the interview:
the mid-interview measurement capture (temperature-on-demand, weight/height
wrap-up) and the merge helper both device routers reuse. The cuff and the
thermometer each have their own router (``blood_pressure.py``,
``thermometer.py``)."""

import logging
from datetime import datetime, timezone
from uuid import UUID
import asyncpg
from fastapi import (
    Depends,
    HTTPException,
)
from app.database import get_connection
from app.schemas import SessionMeasurementUpdate

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()

# Canonical rules-engine vital -> the raw metadata key normalize_vitals reads.
_MEASUREMENT_METADATA_KEY = {
    "temp": "temperature",
    "weight": "weight_kg",
    "height": "height_cm",
    "spo2": "spo2",
}


async def merge_session_vitals(
    connection: asyncpg.Connection,
    session_id: UUID,
    updates: dict,
    *,
    source: str | None = None,
) -> dict | None:
    """Merge values into the session's stored vitals metadata (the next
    turn's ``turn_context`` reads it). Returns the merged vitals, or None
    when the session does not exist.

    ``source`` stamps per-vital provenance (``vitals["sources"]``) for every
    updated key — "device" vs "patient_input". The SBAR handover and nurse
    review read it; without the stamp a patient-entered weight is presented
    to a clinician as a booth measurement (merge resolution 2026-08-12:
    this helper arrived without provenance and would have erased it)."""
    session_row = await connection.fetchrow(
        "SELECT metadata FROM sessions WHERE id = $1", session_id
    )
    if session_row is None:
        return None
    metadata = dict(session_row["metadata"] or {})
    vitals = dict(metadata.get("vitals") or {})
    vitals.update(updates)
    if source is not None:
        sources = dict(vitals.get("sources") or {})
        for key in updates:
            sources[key] = source
        vitals["sources"] = sources
    vitals["recorded_at"] = datetime.now(timezone.utc).isoformat()
    metadata["vitals"] = vitals
    await connection.execute(
        "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
        session_id,
        metadata,
    )
    return vitals


async def store_temperature_reading(
    connection: asyncpg.Connection,
    *,
    session_id: UUID | None,
    temperature_c: float,
    measured_at: datetime | None,
    source: str = "device",
) -> UUID | None:
    row = await connection.fetchrow(
        """
        INSERT INTO temperature_readings (session_id, temperature_c, measured_at, source)
        VALUES ($1, $2, COALESCE($3, NOW()), $4)
        RETURNING id
        """,
        session_id,
        temperature_c,
        measured_at,
        source,
    )
    return row["id"] if row is not None else None


async def store_spo2_reading(
    connection: asyncpg.Connection,
    *,
    session_id: UUID | None,
    spo2: int,
    pulse_bpm: int | None,
    measured_at: datetime | None,
    source: str = "device",
) -> UUID | None:
    row = await connection.fetchrow(
        """
        INSERT INTO spo2_readings (session_id, spo2, pulse_bpm, measured_at, source)
        VALUES ($1, $2, $3, COALESCE($4, NOW()), $5)
        RETURNING id
        """,
        session_id,
        spo2,
        pulse_bpm,
        measured_at,
        source,
    )
    return row["id"] if row is not None else None


@router.post("/sessions/{session_id}/measurement")
async def update_session_measurement(
    session_id: UUID,
    payload: SessionMeasurementUpdate,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Record a single vital the screening engine asked for mid-interview
    (temperature-on-demand; weight/height near the end of the interview,
    self-reported by the patient). Merges into the session's stored vitals so
    the next turn's ``turn_context`` carries it — without requiring the booth
    to re-send the blood-pressure reading.
    """
    key = _MEASUREMENT_METADATA_KEY.get(payload.vital, payload.vital)
    vitals = await merge_session_vitals(
        connection, session_id, {key: payload.value}, source="patient_input"
    )
    if vitals is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if payload.vital == "temp":
        # Typed temperatures get a durable row too; device fetches store
        # theirs in /vitals/temperature/fetch (the booth skips this call
        # when the device value is used unedited, so no duplicates).
        try:
            await store_temperature_reading(
                connection,
                session_id=session_id,
                temperature_c=payload.value,
                measured_at=None,
                source="manual",
            )
        except Exception:  # noqa: BLE001 — vitals merge must not fail
            logger.exception("Failed to persist manual temperature reading")
    elif payload.vital == "spo2":
        # Same durable-row rule as temperature: typed SpO2 values are stored
        # here; device fetches store theirs in /vitals/spo2/fetch.
        try:
            await store_spo2_reading(
                connection,
                session_id=session_id,
                spo2=int(payload.value),
                pulse_bpm=None,
                measured_at=None,
                source="manual",
            )
        except Exception:  # noqa: BLE001 — vitals merge must not fail
            logger.exception("Failed to persist manual SpO2 reading")
    return {"session_id": str(session_id), "vitals": vitals}
