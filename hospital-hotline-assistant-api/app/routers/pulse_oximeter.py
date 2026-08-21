"""Pulse-oximeter endpoints: the Rossmax SB210 fingertip device — settled
SpO2/pulse fetch and admin pairing. The cuff and thermometer have their own
routers (``blood_pressure.py``, ``thermometer.py``); the shared
session-vitals helpers live in ``vitals.py``."""

import logging
from uuid import UUID
import asyncpg
from fastapi import (
    Depends,
    Request,
)
from app.config import settings
from app.database import get_connection
from app.routers.vitals import merge_session_vitals, store_spo2_reading
from app.services.pulse_oximeter import PulseOximeterError, PulseOximeterService

logger = logging.getLogger(__name__)
from app.schemas import (
    Spo2DeviceStatusOut,
    Spo2FetchRequest,
    Spo2FetchResponse,
    Spo2PairRequest,
    Spo2PairResponse,
    Spo2ScanResponse,
)

from fastapi import APIRouter
from app.routers.deps import require_roles

router = APIRouter()


@router.post("/vitals/spo2/fetch", response_model=Spo2FetchResponse)
async def fetch_spo2(
    request: Request,
    payload: Spo2FetchRequest | None = None,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Take one settled SpO2/pulse reading from the fingertip oximeter.

    Connects, waits for the patient's finger (up to ``timeout_seconds``),
    lets the value settle, persists the reading to ``spo2_readings`` and —
    when a session is given — merges it into the session vitals so the next
    screening turn carries it (the criteria's low-SpO2 rules read it).
    Always returns 200 with a ``status`` field the kiosk UI branches on.
    """
    spo2_service: PulseOximeterService = request.app.state.spo2_service
    session_id = payload.session_id if payload else None
    try:
        reading = await spo2_service.fetch_reading(
            payload.timeout_seconds if payload else None
        )
    except PulseOximeterError as exc:
        return Spo2FetchResponse(status=exc.code, message=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("Unexpected pulse-oximeter failure")
        return Spo2FetchResponse(status="error", message=str(exc))

    reading_id: UUID | None = None
    try:
        reading_id = await store_spo2_reading(
            connection,
            session_id=session_id,
            spo2=reading.spo2,
            pulse_bpm=reading.pulse_bpm,
            measured_at=reading.measured_at,
            source="device",
        )
    except Exception:  # noqa: BLE001 — reading display must not fail
        logger.exception("Failed to persist SpO2 reading")
    if session_id is not None:
        try:
            # Instrument measurement — the provenance the SBAR shows the
            # nurse as measured at the booth. The oximeter's pulse is a real
            # heart-rate reading, so it flows too (latest measurement wins).
            await merge_session_vitals(
                connection,
                session_id,
                {"spo2": reading.spo2, "pulse_bpm": reading.pulse_bpm},
                source="device",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to merge SpO2 into session vitals")

    return Spo2FetchResponse(
        status="ok",
        spo2=reading.spo2,
        pulse_bpm=reading.pulse_bpm,
        measured_at=reading.measured_at,
        reading_id=reading_id,
    )


@router.get("/admin/spo2-device", response_model=Spo2DeviceStatusOut)
async def get_spo2_device_status(
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
):
    """Current pulse-oximeter configuration for the admin device manager."""
    spo2_service: PulseOximeterService = request.app.state.spo2_service
    return Spo2DeviceStatusOut(
        device_name=settings.spo2_device_name,
        device_mac=settings.spo2_device_mac,
        configured=bool(settings.spo2_device_mac),
        busy=spo2_service.is_busy,
    )


@router.post("/admin/spo2-device/scan", response_model=Spo2ScanResponse)
async def scan_spo2_devices(
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
):
    """Sweep for nearby BLE devices (~6s) so the admin can pick the oximeter."""
    spo2_service: PulseOximeterService = request.app.state.spo2_service
    try:
        devices = await spo2_service.scan_devices()
    except PulseOximeterError as exc:
        return Spo2ScanResponse(
            status="busy" if exc.code == "busy" else "error", message=str(exc)
        )
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("BLE scan failed")
        return Spo2ScanResponse(status="error", message=str(exc))
    return Spo2ScanResponse(status="ok", devices=devices)


@router.post("/admin/spo2-device/pair", response_model=Spo2PairResponse)
async def pair_spo2_device(
    payload: Spo2PairRequest,
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
):
    """Verify the selected device streams SB210 oximeter data and make it
    the active kiosk pulse oximeter (persists to .env, effective immediately)."""
    spo2_service: PulseOximeterService = request.app.state.spo2_service
    try:
        await spo2_service.save_device(payload.mac, payload.name)
    except PulseOximeterError as exc:
        return Spo2PairResponse(status=exc.code, message=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("Unexpected oximeter connect failure")
        return Spo2PairResponse(status="error", message=str(exc))
    return Spo2PairResponse(
        status="ok",
        device_name=settings.spo2_device_name,
        device_mac=settings.spo2_device_mac,
    )
