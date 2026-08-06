import logging
from datetime import datetime, timezone
from uuid import UUID
import asyncpg
from fastapi import (
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from app.config import settings
from app.database import get_connection
from app.services.blood_pressure import (
    BloodPressureFetchError,
    BloodPressureService,
)

logger = logging.getLogger(__name__)
from app.schemas import (
    BloodPressureFetchResponse,
    BpDeviceStatusOut,
    BpFetchRequest,
    BpWatchRequest,
    BpRestStatusOut,
    BpPairRequest,
    BpPairResponse,
    BpScanResponse,
    SessionMeasurementUpdate,
    SessionVitalsUpdate,
)

from fastapi import APIRouter
from app.routers.deps import require_roles

router = APIRouter()

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


@router.put("/sessions/{session_id}/vitals")
async def update_session_vitals(
    session_id: UUID,
    payload: SessionVitalsUpdate,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Store a blood-pressure reading on the session so the triage agent
    (text chat and live voice) can factor it into the assessment.
    Called by the vitals gate UI after a cuff fetch or manual entry.

    Plausibility is enforced by ``SessionVitalsUpdate`` (bounds from the
    criteria defaults, plus systolic > diastolic), so an impossible reading is
    rejected with a 422 BEFORE the hypertensive-crisis check below can see it.
    That ordering is load-bearing: 300/220 must not open a 15-minute rest
    window. See docs/vital-bounds.md.
    """
    from app.services.bp_rest import (
        get_active_rest,
        has_prior_window,
        is_hypertensive_crisis,
        open_rest_window,
        resolve_windows_for,
    )

    session_row = await connection.fetchrow(
        "SELECT metadata FROM sessions WHERE id = $1", session_id
    )
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = dict(session_row["metadata"] or {})
    visit = dict(metadata.get("visit") or {})
    hn = visit.get("hn") if isinstance(visit.get("hn"), str) else None
    visit_id = visit.get("visit_id") if isinstance(visit.get("visit_id"), str) else None

    rest = await get_active_rest(connection, hn=hn, visit_id=visit_id)
    if rest.resting:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "bp_resting",
                "message": (
                    f"Please rest before remeasuring "
                    f"({rest.seconds_remaining}s remaining)."
                ),
                "rest_until": rest.rest_until.isoformat() if rest.rest_until else None,
                "seconds_remaining": rest.seconds_remaining,
            },
        )

    # First crisis reading for this patient → open the 15-minute rest window
    # and flag the reading pending-recheck so the rules engine does NOT
    # dispose on it (white-coat/exertion effect — the meeting flow is rest,
    # re-measure, then decide). A patient who already had a window gets the
    # post-rest confirmatory reading instead: it flows to the engine as-is.
    crisis = is_hypertensive_crisis(payload.systolic, payload.diastolic)
    recheck_pending = False
    rest_until = None
    if crisis and (hn or visit_id) and not await has_prior_window(
        connection, hn=hn, visit_id=visit_id
    ):
        recheck_pending = True

    # Preserve any patient-typed vitals from a prior call on this session.
    existing_vitals = dict(metadata.get("vitals") or {})
    existing_vitals.pop("bp_recheck_pending", None)
    vitals = {
        **existing_vitals,
        "systolic": payload.systolic,
        "diastolic": payload.diastolic,
        "pulse_bpm": payload.pulse_bpm,
        "measured_at": payload.measured_at.isoformat() if payload.measured_at else None,
        "source": payload.source,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    # Per-vital provenance. A single ``source`` on the whole dict was wrong the
    # moment a patient-stated weight landed beside a cuff reading: the nurse
    # (and the hospital's SBAR) would be told the whole line was instrument
    # measured. ``source`` is kept for backwards compatibility as the default.
    sources = dict(vitals.get("sources") or {})
    for field in ("systolic", "diastolic", "pulse_bpm"):
        sources[field] = payload.source
    for field, value in (
        ("weight_kg", payload.weight_kg),
        ("height_cm", payload.height_cm),
        ("temperature", payload.temperature_c),
    ):
        if value is not None:
            sources[field] = payload.source
    vitals["sources"] = sources
    if recheck_pending:
        vitals["bp_recheck_pending"] = True
    if payload.weight_kg is not None:
        vitals["weight_kg"] = payload.weight_kg
    if payload.height_cm is not None:
        vitals["height_cm"] = payload.height_cm
    if payload.temperature_c is not None:
        vitals["temperature"] = payload.temperature_c
    metadata["vitals"] = vitals
    await connection.execute(
        "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
        session_id,
        metadata,
    )
    if not recheck_pending and (hn or visit_id):
        # Any reading outside a live window closes the recheck loop.
        await resolve_windows_for(connection, hn=hn, visit_id=visit_id)

    # Keep the durable bp_readings row in sync: link the row created at
    # fetch time when we have its id, otherwise store this (e.g. manual)
    # reading now.
    reading_id = payload.reading_id
    if reading_id is not None:
        await connection.execute(
            "UPDATE bp_readings SET session_id = $2 WHERE id = $1",
            reading_id,
            session_id,
        )
    else:
        reading_id = await _store_bp_reading(
            connection,
            session_id=session_id,
            systolic=payload.systolic,
            diastolic=payload.diastolic,
            pulse_bpm=payload.pulse_bpm,
            measured_at=payload.measured_at,
            source=payload.source,
        )

    if recheck_pending:
        rest_until = await open_rest_window(
            connection,
            hn=hn,
            visit_id=visit_id,
            reading_id=reading_id,
        )

    out: dict = {"session_id": str(session_id), "vitals": vitals}
    if rest_until is not None:
        seconds = max(0, int((rest_until - datetime.now(timezone.utc)).total_seconds()))
        out["bp_rest_until"] = rest_until.isoformat()
        out["bp_recheck"] = {
            "required": True,
            "rest_until": rest_until.isoformat(),
            "seconds_remaining": seconds,
        }
    return out


# Canonical rules-engine vital -> the raw metadata key normalize_vitals reads.
_MEASUREMENT_METADATA_KEY = {
    "temp": "temperature",
    "weight": "weight_kg",
    "height": "height_cm",
}


@router.post("/sessions/{session_id}/measurement")
async def update_session_measurement(
    session_id: UUID,
    payload: SessionMeasurementUpdate,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Record a single vital the screening engine asked for mid-interview
    (temperature-on-demand). Merges into the session's stored vitals so the
    next turn's ``turn_context`` carries it — without requiring the booth to
    re-send the blood-pressure reading.
    """
    session_row = await connection.fetchrow(
        "SELECT metadata FROM sessions WHERE id = $1", session_id
    )
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = dict(session_row["metadata"] or {})
    vitals = dict(metadata.get("vitals") or {})
    key = _MEASUREMENT_METADATA_KEY.get(payload.vital, payload.vital)
    vitals[key] = payload.value
    # This endpoint is the mid-interview popup / spoken answer: the patient is
    # telling us the number, we did not measure it. Recorded per-vital so a
    # stated weight is never presented as a booth measurement.
    sources = dict(vitals.get("sources") or {})
    sources[key] = "stated"
    vitals["sources"] = sources
    vitals["recorded_at"] = datetime.now(timezone.utc).isoformat()
    metadata["vitals"] = vitals
    await connection.execute(
        "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
        session_id,
        metadata,
    )
    return {"session_id": str(session_id), "vitals": vitals}


@router.get("/screening/vital-bounds")
async def get_vital_bounds(connection: asyncpg.Connection = Depends(get_connection)):
    """Physiologically possible ranges from the active criteria version.

    The kiosk reads these so the patient gets instant, correctly-worded
    feedback instead of a bare 422 — and so the numbers live in exactly one
    place (the criteria document) rather than being retyped in the client.
    """
    from app.services.screening.rules.criteria_store import get_active_criteria

    _, criteria = await get_active_criteria(connection)
    return {
        "bounds": {
            name: bound.model_dump() for name, bound in criteria.vital_bounds.items()
        },
        "cross_checks": {
            check_id: check.model_dump()
            for check_id, check in criteria.cross_checks.items()
        },
    }


@router.get("/vitals/blood-pressure/rest-status", response_model=BpRestStatusOut)
async def get_bp_rest_status(
    session_id: UUID | None = Query(default=None),
    hn: str | None = Query(default=None),
    visit_id: str | None = Query(default=None),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Whether this patient must wait before another BP measurement."""
    from app.services.bp_rest import get_active_rest

    resolved_hn = hn
    resolved_visit = visit_id
    if session_id is not None:
        session_row = await connection.fetchrow(
            "SELECT metadata FROM sessions WHERE id = $1", session_id
        )
        if session_row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        visit = (session_row["metadata"] or {}).get("visit") or {}
        if not resolved_hn and isinstance(visit.get("hn"), str):
            resolved_hn = visit["hn"]
        if not resolved_visit and isinstance(visit.get("visit_id"), str):
            resolved_visit = visit["visit_id"]

    status_out = await get_active_rest(
        connection, hn=resolved_hn, visit_id=resolved_visit
    )
    return BpRestStatusOut(**status_out.as_dict())


async def _session_rest_block(
    connection: asyncpg.Connection, session_id: UUID | None
) -> BloodPressureFetchResponse | None:
    """Return a ``resting`` fetch response when an active rest window blocks BP."""
    from app.services.bp_rest import get_active_rest

    if session_id is None:
        return None
    session_row = await connection.fetchrow(
        "SELECT metadata FROM sessions WHERE id = $1", session_id
    )
    if session_row is None:
        return None
    visit = (session_row["metadata"] or {}).get("visit") or {}
    hn = visit.get("hn") if isinstance(visit.get("hn"), str) else None
    visit_id = visit.get("visit_id") if isinstance(visit.get("visit_id"), str) else None
    rest = await get_active_rest(connection, hn=hn, visit_id=visit_id)
    if not rest.resting:
        return None
    mins = max(1, (rest.seconds_remaining + 59) // 60)
    return BloodPressureFetchResponse(
        status="resting",
        message=f"Please rest about {mins} more minute(s) before remeasuring blood pressure.",
        rest_until=rest.rest_until,
        seconds_remaining=rest.seconds_remaining,
    )


@router.post("/vitals/blood-pressure/fetch", response_model=BloodPressureFetchResponse)
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
    they cancel the voice flow right after measuring.
    """
    session_id = payload.session_id if payload else None
    blocked = await _session_rest_block(connection, session_id)
    if blocked is not None:
        return blocked

    bp_service: BloodPressureService = request.app.state.bp_service
    try:
        reading = await bp_service.fetch_latest()
    except BloodPressureFetchError as exc:
        return BloodPressureFetchResponse(status=exc.code, message=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("Unexpected omblepy failure")
        return BloodPressureFetchResponse(status="error", message=str(exc))

    return await _persist_and_build_bp_response(
        bp_service, connection, reading, session_id
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


@router.post("/vitals/blood-pressure/watch", response_model=BloodPressureFetchResponse)
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
    session_id = payload.session_id if payload else None
    blocked = await _session_rest_block(connection, session_id)
    if blocked is not None:
        return blocked

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
        bp_service, connection, reading, session_id
    )


@router.get("/admin/bp-device", response_model=BpDeviceStatusOut)
async def get_bp_device_status(
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
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


@router.post("/admin/bp-device/scan", response_model=BpScanResponse)
async def scan_bp_devices(
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
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


@router.post("/admin/bp-device/pair", response_model=BpPairResponse)
async def pair_bp_device(
    payload: BpPairRequest,
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
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

