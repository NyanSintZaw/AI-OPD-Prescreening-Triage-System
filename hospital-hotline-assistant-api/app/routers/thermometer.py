"""Thermometer endpoints: the BLE kiosk thermometer — one-measurement fetch
and admin pairing. The blood-pressure cuff has its own router
(``blood_pressure.py``); the shared session-vitals helpers live in
``vitals.py``."""

import logging
from uuid import UUID
import asyncpg
from fastapi import (
    Depends,
    Request,
)
from app.config import settings
from app.database import get_connection
from app.routers.vitals import merge_session_vitals, store_temperature_reading
from app.services.thermometer import ThermometerError, ThermometerService

logger = logging.getLogger(__name__)
from app.schemas import (
    TempDeviceStatusOut,
    TempFetchRequest,
    TempPairRequest,
    TempPairResponse,
    TempScanResponse,
    TemperatureFetchResponse,
)

from fastapi import APIRouter
from app.routers.deps import require_roles

router = APIRouter()


@router.post("/vitals/temperature/fetch", response_model=TemperatureFetchResponse)
async def fetch_temperature(
    request: Request,
    payload: TempFetchRequest | None = None,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Long-poll the kiosk thermometer for one measurement.

    The device pushes the reading over a standard Health Thermometer
    indication the moment the measurement beeps, so this call connects,
    waits for that push (up to ``timeout_seconds``), persists the reading
    to ``temperature_readings`` and — when a session is given — merges it
    into the session vitals so the next screening turn carries it.
    Always returns 200 with a ``status`` field the kiosk UI branches on.
    """
    temp_service: ThermometerService = request.app.state.temp_service
    session_id = payload.session_id if payload else None
    try:
        reading = await temp_service.fetch_reading(
            payload.timeout_seconds if payload else None
        )
    except ThermometerError as exc:
        return TemperatureFetchResponse(status=exc.code, message=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("Unexpected thermometer failure")
        return TemperatureFetchResponse(status="error", message=str(exc))

    reading_id: UUID | None = None
    try:
        reading_id = await store_temperature_reading(
            connection,
            session_id=session_id,
            temperature_c=reading.temperature_c,
            measured_at=reading.measured_at,
            source="device",
        )
    except Exception:  # noqa: BLE001 — reading display must not fail
        logger.exception("Failed to persist temperature reading")
    if session_id is not None:
        try:
            # A BLE thermometer reading is an instrument measurement — the
            # provenance the SBAR shows the nurse as "วัดที่บูธ".
            await merge_session_vitals(
                connection, session_id, {"temperature": reading.temperature_c},
                source="device",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to merge temperature into session vitals")

    return TemperatureFetchResponse(
        status="ok",
        temperature_c=reading.temperature_c,
        measured_at=reading.measured_at,
        reading_id=reading_id,
    )


@router.get("/admin/temp-device", response_model=TempDeviceStatusOut)
async def get_temp_device_status(
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
):
    """Current thermometer configuration for the admin portal device manager."""
    temp_service: ThermometerService = request.app.state.temp_service
    return TempDeviceStatusOut(
        device_name=settings.temp_device_name,
        device_mac=settings.temp_device_mac,
        configured=bool(settings.temp_device_mac),
        busy=temp_service.is_busy,
    )


@router.post("/admin/temp-device/scan", response_model=TempScanResponse)
async def scan_temp_devices(
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
):
    """Sweep for nearby BLE devices (~6s) so the admin can pick the thermometer."""
    temp_service: ThermometerService = request.app.state.temp_service
    try:
        devices = await temp_service.scan_devices()
    except ThermometerError as exc:
        return TempScanResponse(
            status="busy" if exc.code == "busy" else "error", message=str(exc)
        )
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("BLE scan failed")
        return TempScanResponse(status="error", message=str(exc))
    return TempScanResponse(status="ok", devices=devices)


@router.post("/admin/temp-device/pair", response_model=TempPairResponse)
async def pair_temp_device(
    payload: TempPairRequest,
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
):
    """Verify the selected device speaks the thermometer service and make it
    the active kiosk thermometer (persists to .env, effective immediately)."""
    temp_service: ThermometerService = request.app.state.temp_service
    try:
        await temp_service.save_device(payload.mac, payload.name)
    except ThermometerError as exc:
        return TempPairResponse(status=exc.code, message=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        logger.exception("Unexpected thermometer connect failure")
        return TempPairResponse(status="error", message=str(exc))
    return TempPairResponse(
        status="ok",
        device_name=settings.temp_device_name,
        device_mac=settings.temp_device_mac,
    )
