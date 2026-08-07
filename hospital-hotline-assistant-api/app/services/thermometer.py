"""Read body temperature from a BLE Health Thermometer.

Unlike the Omron cuff (proprietary protocol via the omblepy subprocess),
thermometers speak the standard GATT Health Thermometer Service:
connect, subscribe to Temperature Measurement (0x2A1C) indications, and
the device pushes the reading the moment a measurement beeps. There are
no pairing keys — "connecting" a device is just verifying it exposes the
service and persisting its MAC — so any brand that implements the
standard service (TAIDOC TD1242, FORA/Clever rebrands, Beurer, …) can be
paired from the admin device manager; nothing here is model-specific
beyond connect-retry tolerances.

Shares :data:`BLE_ADAPTER_LOCK` with the blood-pressure service — the
single Bluetooth adapter cannot scan and connect concurrently.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import bleak
from bleak import BleakClient

from app.config import settings
from app.services.blood_pressure import (
    _VALID_MAC,
    _VALID_UUID,
    BLE_ADAPTER_LOCK,
    BloodPressureFetchError as ThermometerError,  # same shape: code + message
)
from app.services.env_persist import persist_env_keys

logger = logging.getLogger(__name__)

TEMP_MEASUREMENT_CHAR = "00002a1c-0000-1000-8000-00805f9b34fb"
HEALTH_THERMOMETER_SERVICE = "00001809-0000-1000-8000-00805f9b34fb"
# GAP Device Name — read after verifying a device so the admin portal can
# show what is actually paired instead of a hardcoded model string.
DEVICE_NAME_CHAR = "00002a00-0000-1000-8000-00805f9b34fb"

_FALLBACK_DEVICE_NAME = "BLE Thermometer"

# Advertised names that identify BLE thermometers (TaiDoc makes the TD1242
# and rebrands as FORA and Clever Choice). Only a ranking heuristic for the
# scan list — the advertised Health Thermometer Service is the real signal,
# and pairing itself accepts any device that verifies.
_THERMO_NAME = re.compile(
    r"taidoc|td[- ]?12|fora|therm|temp|clever|beurer|microlife|berrcom|ihealth",
    re.IGNORECASE,
)


def looks_like_thermometer(name: str | None, service_uuids: list[str] | None) -> bool:
    """Rank scan results: an advertised Health Thermometer Service is
    definitive; otherwise fall back to brand/model name patterns."""
    if service_uuids and any(
        u.lower() == HEALTH_THERMOMETER_SERVICE for u in service_uuids
    ):
        return True
    return bool(name and _THERMO_NAME.search(name))

# The TD1242's first connect attempt often drops during service discovery
# ("failed to discover services, device disconnected"); a retry succeeds.
_CONNECT_ATTEMPTS = 3
_CONNECT_TIMEOUT = 15.0


def decode_ieee11073_float(data: bytes) -> float:
    """Decode the 4-byte IEEE-11073 FLOAT used by BLE thermometers."""
    raw = int.from_bytes(data[:4], byteorder="little", signed=False)
    mantissa = raw & 0x00FFFFFF
    exponent = (raw >> 24) & 0xFF
    # Sign-extend 24-bit mantissa and 8-bit exponent.
    if mantissa & 0x00800000:
        mantissa -= 0x01000000
    if exponent & 0x80:
        exponent -= 0x100
    return mantissa * (10**exponent)


def parse_temperature_packet(data: bytes) -> float | None:
    """Return °C from a Temperature Measurement indication, or None if malformed."""
    if len(data) < 5:
        return None
    value = decode_ieee11073_float(bytes(data[1:5]))
    if data[0] & 0x01:  # Fahrenheit flag
        value = (value - 32) * 5 / 9
    if not (0 < value < 100):  # reserved/NaN mantissa values decode absurdly
        return None
    return round(value, 2)


@dataclass
class TemperatureReading:
    temperature_c: float
    # Server clock: the TD1242's on-device clock is not settable over BLE
    # and ships wrong (year 2011), but indications arrive live at the
    # moment of measurement, so arrival time IS the measurement time.
    measured_at: datetime


class ThermometerService:
    def __init__(self) -> None:
        self._lock = BLE_ADAPTER_LOCK

    @property
    def is_busy(self) -> bool:
        return self._lock.locked()

    async def _connect(self, mac: str) -> BleakClient:
        last_error: Exception | None = None
        for attempt in range(1, _CONNECT_ATTEMPTS + 1):
            client = BleakClient(mac, timeout=_CONNECT_TIMEOUT)
            try:
                await client.connect()
                return client
            except (bleak.exc.BleakError, asyncio.TimeoutError, OSError) as exc:
                last_error = exc
                logger.info("Thermometer connect attempt %d failed: %s", attempt, exc)
                await asyncio.sleep(1.0)
        raise ThermometerError(
            "device_not_found",
            f"Could not connect to the thermometer ({last_error}). "
            "Turn it on, keep it near the kiosk, and try again.",
        )

    @staticmethod
    async def _disconnect_quietly(client: BleakClient) -> None:
        # The TD1242 drops the link itself right after indicating; a
        # stop_notify/disconnect on a dead link raises — never fatal.
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            logger.debug("Thermometer disconnect failed", exc_info=True)

    async def fetch_reading(self, timeout_seconds: float | None = None) -> TemperatureReading:
        """Connect to the configured thermometer and wait for one measurement.

        Raises :class:`ThermometerError` with a machine-readable ``code``
        (busy / not_configured / device_not_found / wrong_device / timeout).
        """
        if not settings.temp_device_mac:
            raise ThermometerError(
                "not_configured",
                "TEMP_DEVICE_MAC is not set. Connect a thermometer in the "
                "admin device settings first.",
            )
        if self._lock.locked():
            raise ThermometerError("busy", "A device operation is already in progress.")
        timeout = timeout_seconds or settings.temp_fetch_timeout_seconds

        async with self._lock:
            client = await self._connect(settings.temp_device_mac)
            try:
                if client.services.get_characteristic(TEMP_MEASUREMENT_CHAR) is None:
                    raise ThermometerError(
                        "wrong_device",
                        "Connected device does not expose the standard "
                        "thermometer service. Check TEMP_DEVICE_MAC.",
                    )
                got_reading = asyncio.Event()
                value: list[float] = []

                def _on_indication(_char, data: bytearray) -> None:
                    parsed = parse_temperature_packet(bytes(data))
                    if parsed is not None:
                        value.append(parsed)
                        got_reading.set()

                await client.start_notify(TEMP_MEASUREMENT_CHAR, _on_indication)
                try:
                    await asyncio.wait_for(got_reading.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    raise ThermometerError(
                        "timeout",
                        "No measurement received. Take a temperature "
                        "measurement while the kiosk is waiting.",
                    )
                return TemperatureReading(
                    temperature_c=value[0], measured_at=datetime.now(timezone.utc)
                )
            finally:
                await self._disconnect_quietly(client)

    # ── Admin: device discovery + connect ────────────────────────────────

    async def scan_devices(self, duration: float = 6.0) -> list[dict]:
        """BLE discovery sweep; likely thermometers first, then by signal."""
        if self._lock.locked():
            raise ThermometerError("busy", "A device operation is already in progress.")
        async with self._lock:
            found = await bleak.BleakScanner.discover(timeout=duration, return_adv=True)
        devices = []
        for mac, (ble_dev, adv) in found.items():
            name = ble_dev.name or adv.local_name
            rssi = adv.rssi if adv.rssi is not None and adv.rssi != 127 else None
            devices.append(
                {
                    "mac": mac,
                    "name": name,
                    "rssi": rssi,
                    "is_thermometer": looks_like_thermometer(name, adv.service_uuids),
                }
            )
        devices.sort(
            key=lambda d: (
                not d["is_thermometer"],
                -(d["rssi"] if d["rssi"] is not None else -999),
            )
        )
        return devices

    @staticmethod
    async def _read_device_name(client: BleakClient) -> str | None:
        # Some platforms hide the Generic Access service from GATT clients;
        # the name is a nicety, never worth failing the pairing over.
        try:
            if client.services.get_characteristic(DEVICE_NAME_CHAR) is None:
                return None
            raw = await client.read_gatt_char(DEVICE_NAME_CHAR)
            return bytes(raw).decode("utf-8", errors="ignore").strip() or None
        except Exception:  # noqa: BLE001
            logger.debug("Could not read GAP device name", exc_info=True)
            return None

    async def save_device(self, mac: str, name: str | None = None) -> None:
        """Verify the device speaks the Health Thermometer Service, then
        persist it as the kiosk thermometer (in-memory + .env).

        ``name`` is the advertised name the admin picked in the scan list;
        when absent the device's GAP name is read during the verification
        connect, so the portal shows what is actually paired.
        """
        mac = mac.strip()
        name = (name or "").strip() or None
        if not (_VALID_MAC.match(mac) or _VALID_UUID.match(mac)):
            raise ThermometerError("invalid", f"'{mac}' is not a valid Bluetooth address.")
        if self._lock.locked():
            raise ThermometerError("busy", "A device operation is already in progress.")

        async with self._lock:
            client = await self._connect(mac)
            try:
                if client.services.get_characteristic(TEMP_MEASUREMENT_CHAR) is None:
                    raise ThermometerError(
                        "wrong_device",
                        "That device does not expose the standard thermometer "
                        "service — pick the thermometer (e.g. TAIDOC TD1242).",
                    )
                if name is None:
                    name = await self._read_device_name(client)
            finally:
                await self._disconnect_quietly(client)

        settings.temp_device_mac = mac
        settings.temp_device_name = name or _FALLBACK_DEVICE_NAME
        try:
            persist_env_keys(
                {
                    "TEMP_DEVICE_MAC": mac,
                    "TEMP_DEVICE_NAME": settings.temp_device_name,
                }
            )
        except OSError:
            logger.exception("Thermometer saved but failed to persist .env config")
