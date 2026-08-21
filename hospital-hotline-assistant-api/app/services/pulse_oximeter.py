"""Read SpO2 + pulse from a Rossmax SB210 fingertip pulse oximeter.

The SB210 (advertises as ``RM_SPO2``) streams a proprietary 16-byte packet
over a Nordic-UART-style notify characteristic (protocol reverse-engineered
in ``rossmax_sb210_live_decoder.py`` at the repo root):

    byte 0      status/sequence
    byte 1      SpO2 %
    byte 2      pulse rate (bpm)
    bytes 3-14  pleth waveform samples
    byte 15     checksum: sum(bytes[0:15]) & 0xFF

Before a finger is inserted the device streams zeros, and the first
~30-60 s after insertion overshoot while the reading settles — so a fetch
follows the clinical measurement procedure instead of trusting early
values: keep collecting, accept only once the last stability window shows
no meaningful movement (SpO2 within 1 point, pulse within a few bpm), and
report the median of that stable window. Losing the signal (finger out,
poor contact) restarts the stabilization clock.

Shares :data:`BLE_ADAPTER_LOCK` with the other device services — the single
Bluetooth adapter cannot scan and connect concurrently.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median

import bleak
from bleak import BleakClient

from app.config import settings
from app.services.blood_pressure import (
    _VALID_MAC,
    _VALID_UUID,
    BLE_ADAPTER_LOCK,
    BloodPressureFetchError as PulseOximeterError,  # same shape: code + message
)
from app.services.env_persist import persist_env_keys

logger = logging.getLogger(__name__)

# Vendor data stream (Nordic-UART-style). The characteristic is the real
# pairing signal; the advertised service is its 6e40f680… container.
SPO2_DATA_CHAR = "6e40f682-b5a3-f393-e0a9-e50e24dcca9e"
SPO2_SERVICE_PREFIX = "6e40f680"

_FALLBACK_DEVICE_NAME = "Rossmax SB210"

# Advertised names that identify fingertip pulse oximeters. Only a ranking
# heuristic for the scan list — pairing verifies the data characteristic.
_OXIMETER_NAME = re.compile(
    r"rm_spo2|rossmax|sb[- ]?210|spo2|oxim|pulseox|po[- ]?\d{3}",
    re.IGNORECASE,
)

_CONNECT_ATTEMPTS = 3
_CONNECT_TIMEOUT = 15.0
# ── Acceptance criteria (mirrors the manual nursing procedure) ───────────
# A reading counts only when the values have genuinely stopped moving:
# every sample in the trailing window must agree within the ranges below,
# and the stream must have covered the whole window since (re)insertion —
# which is what keeps the stabilization-period overshoot out of the result.
_STABILITY_WINDOW_S = 10.0
_SPO2_STABLE_RANGE = 1  # percentage points, max-min across the window
_PULSE_STABLE_RANGE = 4  # bpm, max-min across the window
_MIN_WINDOW_SAMPLES = 8  # a sparse/dropout stream is not a stable stream
# No valid packet for this long means the finger came out (the SB210
# streams zeros without one) — earlier samples then belong to a different
# placement and the stabilization clock restarts.
_SIGNAL_LOSS_RESET_S = 3.0


def looks_like_oximeter(name: str | None, service_uuids: list[str] | None) -> bool:
    """Rank scan results: the advertised vendor service is definitive;
    otherwise fall back to brand/model name patterns."""
    if service_uuids and any(
        u.lower().startswith(SPO2_SERVICE_PREFIX) for u in service_uuids
    ):
        return True
    return bool(name and _OXIMETER_NAME.search(name))


def decode_packet(data: bytes) -> dict | None:
    """Decode one 16-byte SB210 packet; None when the length is wrong."""
    if len(data) != 16:
        return None
    checksum_expected = sum(data[:15]) & 0xFF
    checksum_ok = checksum_expected == data[15]
    spo2 = data[1]
    pulse = data[2]
    return {
        "status": data[0],
        "spo2": spo2,
        "pulse": pulse,
        "pleth": list(data[3:15]),
        "checksum_ok": checksum_ok,
        # Zeros stream before a finger is inserted; out-of-range values are
        # settling noise. Only physiologically plausible pairs count.
        "valid_measurement": bool(
            checksum_ok and 50 <= spo2 <= 100 and 25 <= pulse <= 250
        ),
    }


class StabilityTracker:
    """Accumulates timestamped samples and decides when the reading is
    clinically stable (see the acceptance criteria constants above).

    Pure logic — timestamps come from the caller — so the acceptance rules
    are unit-testable without Bluetooth.
    """

    def __init__(self) -> None:
        self._samples: list[tuple[float, int, int]] = []  # (t, spo2, pulse)
        # Whether any valid measurement was ever seen this fetch — decides
        # timeout (no finger) vs unstable (finger, but never steadied).
        self.saw_finger = False

    def add(self, now: float, spo2: int, pulse: int) -> None:
        self.saw_finger = True
        if self._samples and now - self._samples[-1][0] > _SIGNAL_LOSS_RESET_S:
            self._samples.clear()
        self._samples.append((now, spo2, pulse))

    def evaluate(self, now: float) -> tuple[int, int] | None:
        """Median (spo2, pulse) of the trailing window iff stable, else None."""
        if not self._samples:
            return None
        if now - self._samples[-1][0] > _SIGNAL_LOSS_RESET_S:
            return None  # signal currently lost; add() resets on return
        # Earliest possible acceptance is one full window after
        # (re)insertion, so the settling overshoot can never be reported.
        if now - self._samples[0][0] < _STABILITY_WINDOW_S:
            return None
        window = [s for s in self._samples if now - s[0] <= _STABILITY_WINDOW_S]
        if len(window) < _MIN_WINDOW_SAMPLES:
            return None
        spo2s = [spo2 for _, spo2, _ in window]
        pulses = [pulse for _, _, pulse in window]
        if max(spo2s) - min(spo2s) > _SPO2_STABLE_RANGE:
            return None
        if max(pulses) - min(pulses) > _PULSE_STABLE_RANGE:
            return None
        return int(round(median(spo2s))), int(round(median(pulses)))


@dataclass
class Spo2Reading:
    spo2: int
    pulse_bpm: int
    # Server clock: packets stream live, so arrival time is measurement time.
    measured_at: datetime


class PulseOximeterService:
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
                logger.info("Oximeter connect attempt %d failed: %s", attempt, exc)
                await asyncio.sleep(1.0)
        raise PulseOximeterError(
            "device_not_found",
            f"Could not connect to the pulse oximeter ({last_error}). "
            "Turn it on, keep it near the kiosk, and try again.",
        )

    @staticmethod
    async def _disconnect_quietly(client: BleakClient) -> None:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            logger.debug("Oximeter disconnect failed", exc_info=True)

    async def fetch_reading(self, timeout_seconds: float | None = None) -> Spo2Reading:
        """Connect to the configured oximeter and wait for a STABLE reading:
        values stream immediately, but the result is only accepted once the
        trailing window has stopped moving (median of that window).

        Raises :class:`PulseOximeterError` with a machine-readable ``code``
        (busy / not_configured / device_not_found / wrong_device / timeout
        / unstable — timeout means no finger was ever detected, unstable
        means a finger was seen but the values never steadied).
        """
        if not settings.spo2_device_mac:
            raise PulseOximeterError(
                "not_configured",
                "SPO2_DEVICE_MAC is not set. Connect a pulse oximeter in the "
                "admin device settings first.",
            )
        if self._lock.locked():
            raise PulseOximeterError("busy", "A device operation is already in progress.")
        timeout = timeout_seconds or settings.spo2_fetch_timeout_seconds

        async with self._lock:
            client = await self._connect(settings.spo2_device_mac)
            try:
                if client.services.get_characteristic(SPO2_DATA_CHAR) is None:
                    raise PulseOximeterError(
                        "wrong_device",
                        "Connected device does not stream SB210 oximeter "
                        "data. Check SPO2_DEVICE_MAC.",
                    )
                loop = asyncio.get_running_loop()
                tracker = StabilityTracker()
                sample_event = asyncio.Event()

                def _on_notify(_char, data: bytearray) -> None:
                    decoded = decode_packet(bytes(data))
                    if decoded is None or not decoded["valid_measurement"]:
                        return
                    tracker.add(loop.time(), decoded["spo2"], decoded["pulse"])
                    sample_event.set()

                await client.start_notify(SPO2_DATA_CHAR, _on_notify)
                deadline = loop.time() + timeout
                while True:
                    now = loop.time()
                    if now >= deadline:
                        if tracker.saw_finger:
                            raise PulseOximeterError(
                                "unstable",
                                "The reading never stabilized. Keep the hand "
                                "still, relaxed and warm (movement, a cold "
                                "finger or nail polish interfere) and try "
                                "again.",
                            )
                        raise PulseOximeterError(
                            "timeout",
                            "No measurement received. Insert a finger into "
                            "the oximeter while the kiosk is waiting.",
                        )
                    try:
                        await asyncio.wait_for(
                            sample_event.wait(), timeout=min(1.0, deadline - now)
                        )
                    except asyncio.TimeoutError:
                        pass
                    sample_event.clear()
                    stable = tracker.evaluate(loop.time())
                    if stable is not None:
                        spo2, pulse = stable
                        return Spo2Reading(
                            spo2=spo2,
                            pulse_bpm=pulse,
                            measured_at=datetime.now(timezone.utc),
                        )
            finally:
                await self._disconnect_quietly(client)

    # ── Admin: device discovery + connect ────────────────────────────────

    async def scan_devices(self, duration: float = 6.0) -> list[dict]:
        """BLE discovery sweep; likely oximeters first, then by signal."""
        if self._lock.locked():
            raise PulseOximeterError("busy", "A device operation is already in progress.")
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
                    "is_oximeter": looks_like_oximeter(name, adv.service_uuids),
                }
            )
        devices.sort(
            key=lambda d: (
                not d["is_oximeter"],
                -(d["rssi"] if d["rssi"] is not None else -999),
            )
        )
        return devices

    async def save_device(self, mac: str, name: str | None = None) -> None:
        """Verify the device streams the SB210 data characteristic, then
        persist it as the kiosk pulse oximeter (in-memory + .env)."""
        mac = mac.strip()
        name = (name or "").strip() or None
        if not (_VALID_MAC.match(mac) or _VALID_UUID.match(mac)):
            raise PulseOximeterError("invalid", f"'{mac}' is not a valid Bluetooth address.")
        if self._lock.locked():
            raise PulseOximeterError("busy", "A device operation is already in progress.")

        async with self._lock:
            client = await self._connect(mac)
            try:
                if client.services.get_characteristic(SPO2_DATA_CHAR) is None:
                    raise PulseOximeterError(
                        "wrong_device",
                        "That device does not stream SB210 oximeter data — "
                        "pick the pulse oximeter (RM_SPO2).",
                    )
            finally:
                await self._disconnect_quietly(client)

        settings.spo2_device_mac = mac
        settings.spo2_device_name = name or _FALLBACK_DEVICE_NAME
        try:
            persist_env_keys(
                {
                    "SPO2_DEVICE_MAC": mac,
                    "SPO2_DEVICE_NAME": settings.spo2_device_name,
                }
            )
        except OSError:
            logger.exception("Oximeter saved but failed to persist .env config")
