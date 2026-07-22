"""Fetch the latest weight reading from an Omron BLE scale via omscale.

Counterpart of :mod:`app.services.blood_pressure` for the repo-root
``omscale/`` tool (an Omron body-composition-scale reader in the omblepy
family). Two read modes, selected by ``SCALE_READ_MODE``:

``file`` (default)
    The scale cannot be read directly from macOS (it requires a bonded BLE
    link CoreBluetooth never completes — see omscale.py's platform note), so
    a Linux host runs ``omscale.py --daemon`` (``omscale-sync.service``)
    which syncs every time the scale finishes a measurement and publishes
    the newest record to ``scale_user{N}_latest.json``. This mode reads /
    long-polls that file; share or sync it onto the API host.

``subprocess``
    The API host has working BLE access to the scale (Linux): run the
    bundled ``omscale.py`` CLI with ``--jsonOut`` and parse the reading from
    the ``OMSCALE_RESULT_JSON`` stdout line, exactly like omblepy for the
    cuff. A module-level asyncio lock serialises BLE access; concurrent
    callers get a ``busy`` status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_RESULT_MARKER = "OMSCALE_RESULT_JSON "
_RECENT_WINDOW = timedelta(minutes=15)
_FILE_POLL_INTERVAL_S = 1.0

_LB_TO_KG = 0.45359237


@dataclass
class WeightReading:
    weight_kg: float
    measured_at: datetime
    sequence: int | None = None


class WeightScaleFetchError(Exception):
    """Raised when a scale read fails; ``code`` maps to the machine-readable
    status the frontend switches on (same vocabulary as the BP service)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _default_omscale_dir() -> Path:
    # <repo-root>/omscale, resolved relative to this file:
    # app/services/weight_scale.py -> hospital-hotline-assistant-api -> repo root
    return Path(__file__).resolve().parents[3] / "omscale"


def _to_kg(weight: float, unit: str | None) -> float:
    if (unit or "kg").strip().lower() == "lb":
        return round(weight * _LB_TO_KG, 1)
    return weight


def _parse_record(row: dict) -> WeightReading | None:
    """Parse one omscale record dict (all values may be strings — the
    latest-json file stringifies everything)."""
    try:
        weight = float(row["weight"])
        measured_at = datetime.strptime(str(row["datetime"]), "%Y-%m-%d %H:%M:%S")
    except (KeyError, TypeError, ValueError):
        return None
    if weight <= 0:
        return None
    sequence: int | None = None
    try:
        if row.get("sequence") is not None:
            sequence = int(row["sequence"])
    except (TypeError, ValueError):
        sequence = None
    return WeightReading(
        weight_kg=_to_kg(weight, row.get("weightUnit")),
        measured_at=measured_at,
        sequence=sequence,
    )


def parse_result_json(output: str) -> WeightReading | None:
    """Return the newest reading from omscale's ``--jsonOut`` stdout line."""
    payload: str | None = None
    for line in output.splitlines():
        if line.startswith(_RESULT_MARKER):
            payload = line[len(_RESULT_MARKER):]
    if payload is None:
        return None
    try:
        records = json.loads(payload)
    except json.JSONDecodeError:
        return None
    latest: WeightReading | None = None
    for row in records:
        if not isinstance(row, dict):
            continue
        reading = _parse_record(row)
        if reading is None:
            continue
        if latest is None or reading.measured_at > latest.measured_at:
            latest = reading
    return latest


def parse_latest_file(text: str) -> WeightReading | None:
    """Parse a ``scale_user{N}_latest.json`` published by the sync daemon."""
    try:
        row = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    return _parse_record(row)


def _classify_subprocess_failure(output: str) -> WeightScaleFetchError:
    if "wrong device selected" in output:
        return WeightScaleFetchError(
            "wrong_device",
            "Connected to a device that is not the configured scale. "
            "Check SCALE_DEVICE_MAC.",
        )
    if "TimeoutError" in output or "not advertising" in output:
        # The scale only accepts a connection while it is in its
        # post-measurement sync-ready broadcast, so a connect timeout means
        # "no fresh measurement to hand over".
        return WeightScaleFetchError(
            "device_not_found",
            "The scale is not advertising. Step on it, wait for the weight "
            "to show on its display, and try again.",
        )
    if "Insufficient Encryption" in output or "pair" in output.lower():
        return WeightScaleFetchError(
            "pairing_error",
            "The scale refused the connection. Re-pair it with "
            "'omscale.py --pair' (blinking P on the display).",
        )
    tail = output.strip().splitlines()[-3:]
    return WeightScaleFetchError("error", " | ".join(tail) or "omscale failed")


class WeightScaleService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.omscale_dir = (
            Path(settings.scale_omscale_dir).expanduser()
            if settings.scale_omscale_dir
            else _default_omscale_dir()
        )
        self.python_bin = settings.scale_python_bin or sys.executable

    @property
    def is_busy(self) -> bool:
        return self._lock.locked()

    # ── Shared config helpers ────────────────────────────────────────────

    def _state(self) -> dict:
        try:
            return json.loads((self.omscale_dir / "omscale_state.json").read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _user_slot(self) -> int:
        if settings.scale_user_slot is not None:
            return settings.scale_user_slot
        try:
            return int(self._state().get("userSlot", 1))
        except (TypeError, ValueError):
            return 1

    def _device_mac(self) -> str | None:
        # Pairing saves the scale's address in omscale_state.json, so an
        # explicit SCALE_DEVICE_MAC is only needed to override it.
        return settings.scale_device_mac or self._state().get("address") or None

    def _latest_file(self) -> Path:
        return self.omscale_dir / f"scale_user{self._user_slot()}_latest.json"

    # ── Fetch ────────────────────────────────────────────────────────────

    async def fetch_latest(self) -> WeightReading:
        """Return the scale's newest record.

        Raises :class:`WeightScaleFetchError` with a machine-readable
        ``code`` (busy / not_configured / device_not_found / pairing_error /
        wrong_device / timeout / no_records / error) on any failure.
        """
        if settings.scale_read_mode == "subprocess":
            return await self._fetch_via_subprocess()
        return self._fetch_from_file()

    def _fetch_from_file(self) -> WeightReading:
        if not self.omscale_dir.is_dir():
            raise WeightScaleFetchError(
                "not_configured",
                f"omscale directory not found at {self.omscale_dir}. "
                "Set SCALE_OMSCALE_DIR.",
            )
        path = self._latest_file()
        try:
            text = path.read_text()
        except OSError:
            raise WeightScaleFetchError(
                "no_records",
                f"{path.name} not found — the scale has not synced a "
                "measurement yet. Step on the scale first.",
            )
        reading = parse_latest_file(text)
        if reading is None:
            raise WeightScaleFetchError(
                "no_records", f"{path.name} does not contain a parseable reading."
            )
        return reading

    async def _fetch_via_subprocess(self) -> WeightReading:
        if not (self.omscale_dir / "omscale.py").exists():
            raise WeightScaleFetchError(
                "not_configured",
                f"omscale.py not found in {self.omscale_dir}. Set SCALE_OMSCALE_DIR.",
            )
        mac = self._device_mac()
        if not mac:
            raise WeightScaleFetchError(
                "not_configured",
                "No scale address: set SCALE_DEVICE_MAC or pair once with "
                "'omscale.py --pair' so omscale_state.json holds it.",
            )
        if self._lock.locked():
            raise WeightScaleFetchError(
                "busy", "A scale operation is already in progress."
            )

        async with self._lock:
            # Default new-records-only read (fast); a rerun after the record
            # was already synced returns [] and we fall back to the latest
            # file omscale.py also publishes on every successful sync.
            cmd = [
                self.python_bin,
                "omscale.py",
                "--jsonOut",
                "-m",
                mac,
            ]
            if settings.scale_user_slot is not None:
                cmd += ["-u", str(settings.scale_user_slot)]
            logger.info("Starting omscale fetch: %s", " ".join(cmd))
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.omscale_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                raw_output, _ = await asyncio.wait_for(
                    process.communicate(),
                    timeout=settings.scale_fetch_timeout_seconds,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise WeightScaleFetchError(
                    "timeout",
                    "Timed out talking to the scale. Make sure it is nearby "
                    "and try again.",
                )

            output = raw_output.decode("utf-8", errors="replace")
            logger.info(
                "omscale exited rc=%s, output tail: %s",
                process.returncode,
                " | ".join(output.strip().splitlines()[-3:]),
            )
            has_result = _RESULT_MARKER in output
            if process.returncode != 0 or not has_result:
                raise _classify_subprocess_failure(output)

            reading = parse_result_json(output)
            if reading is not None:
                return reading
            # Empty record list — already synced earlier; the latest file
            # still holds the newest measurement.
            try:
                return self._fetch_from_file()
            except WeightScaleFetchError:
                raise WeightScaleFetchError(
                    "no_records",
                    "The scale reported no measurements yet. Step on it "
                    "first, then fetch again.",
                )

    # ── Watch ────────────────────────────────────────────────────────────

    async def watch_and_fetch(self, timeout_seconds: float) -> WeightReading:
        """Wait for a new measurement, then return it.

        ``file`` mode long-polls the daemon-published latest file until its
        contents change; ``subprocess`` mode listens for the scale's
        post-measurement BLE broadcast (like the BP cuff) and then fetches.
        Raises ``not_seen`` when nothing new arrived within
        ``timeout_seconds`` so the caller can immediately re-arm.
        """
        if settings.scale_read_mode == "subprocess":
            return await self._watch_via_ble(timeout_seconds)
        return await self._watch_file(timeout_seconds)

    async def _watch_file(self, timeout_seconds: float) -> WeightReading:
        path = self._latest_file()

        def _snapshot() -> str | None:
            try:
                return path.read_text()
            except OSError:
                return None

        baseline = _snapshot()
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while True:
            await asyncio.sleep(_FILE_POLL_INTERVAL_S)
            current = _snapshot()
            if current is not None and current != baseline:
                reading = parse_latest_file(current)
                if reading is not None:
                    return reading
                # Mid-write or corrupt — treat as the new baseline and keep
                # polling; the daemon rewrites the whole file per sync.
                baseline = current
            if asyncio.get_event_loop().time() >= deadline:
                raise WeightScaleFetchError(
                    "not_seen", "The scale has not synced a new measurement yet."
                )

    async def _watch_via_ble(self, timeout_seconds: float) -> WeightReading:
        mac = self._device_mac()
        if not mac:
            raise WeightScaleFetchError(
                "not_configured",
                "No scale address: set SCALE_DEVICE_MAC or pair once with "
                "'omscale.py --pair'.",
            )
        if self._lock.locked():
            raise WeightScaleFetchError(
                "busy", "A scale operation is already in progress."
            )

        import bleak

        target = mac.strip().lower()
        seen = asyncio.Event()

        def _on_advertisement(device, _advertisement) -> None:
            if (device.address or "").strip().lower() == target:
                seen.set()

        async with self._lock:
            scanner = bleak.BleakScanner(detection_callback=_on_advertisement)
            await scanner.start()
            try:
                await asyncio.wait_for(seen.wait(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                raise WeightScaleFetchError(
                    "not_seen",
                    "The scale has not announced a finished measurement yet.",
                )
            finally:
                try:
                    await scanner.stop()
                except Exception:  # noqa: BLE001 — adapter quirk, not fatal
                    logger.debug("BLE scanner stop failed", exc_info=True)

        # The scale is in its sync-ready broadcast right now — fetch.
        return await self._fetch_via_subprocess()

    @staticmethod
    def is_recent(reading: WeightReading) -> bool:
        """Heuristic freshness check (scale clock vs server clock)."""
        return abs(datetime.now() - reading.measured_at) <= _RECENT_WINDOW
