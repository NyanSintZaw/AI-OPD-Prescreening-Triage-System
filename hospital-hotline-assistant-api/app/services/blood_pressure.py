"""Fetch the latest blood-pressure reading from an Omron cuff via omblepy.

Runs the bundled ``omblepy`` CLI (repo-root ``omblepy/`` folder) as a
subprocess on the host machine's Bluetooth adapter with ``--jsonOut``,
then parses the reading straight from the ``OMBLEPY_RESULT_JSON`` line on
stdout — no intermediate CSV files are written or read.
Only one fetch may run at a time — BLE adapters do not handle concurrent
connections to the same peripheral, so a module-level asyncio lock guards
the subprocess and callers get a ``busy`` status instead of queueing.

The CLI's exit code is not a reliable success signal (some failure paths
log an error and return 0), so success additionally requires the
"communication finished" log line and a parseable record in the JSON.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import bleak

from app.config import settings

logger = logging.getLogger(__name__)

_RESULT_MARKER = "OMBLEPY_RESULT_JSON "
_RECENT_WINDOW = timedelta(minutes=15)

# Same address formats omblepy accepts: classic BT MAC (win/linux) or the
# CoreBluetooth UUID macOS substitutes for it.
_VALID_MAC = re.compile(r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$")
_VALID_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Advertised names that identify Omron blood-pressure monitors. Idle units
# often advertise as "HEM-XXXXT"; units in pairing mode as "BLEsmart_...".
_OMRON_NAME = re.compile(r"hem[-_]|omron|blesmart", re.IGNORECASE)

@dataclass
class BloodPressureReading:
    systolic: int
    diastolic: int
    pulse_bpm: int
    measured_at: datetime
    irregular_heartbeat: bool
    body_movement: bool


class BloodPressureFetchError(Exception):
    """Raised when the omblepy subprocess fails; ``code`` maps to the
    machine-readable status the frontend switches on."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _default_omblepy_dir() -> Path:
    # <repo-root>/omblepy, resolved relative to this file:
    # app/services/blood_pressure.py -> hospital-hotline-assistant-api -> repo root
    return Path(__file__).resolve().parents[3] / "omblepy"


def _classify_failure(output: str) -> BloodPressureFetchError:
    if "not found during discovery" in output or "not advertising within" in output:
        return BloodPressureFetchError(
            "device_not_found",
            "The blood pressure monitor is not advertising. Finish the "
            "measurement (or press its Bluetooth button) and try again.",
        )
    if "TimeoutError" in output and "connect" in output:
        # The cuff advertises while idle but only accepts a BLE connection
        # right after a measurement (or when its sync button is pressed),
        # so a connect timeout means "no fresh measurement to hand over".
        return BloodPressureFetchError(
            "device_not_found",
            "Could not connect to the monitor. Finish the measurement and "
            "fetch while the result is still on its screen.",
        )
    if "Failure to program new key" in output:
        # The cuff accepted the connection but rejected the key write —
        # it is powered on but not in pairing mode.
        return BloodPressureFetchError(
            "pairing_error",
            "The monitor refused pairing. Hold its Bluetooth button until "
            "the pairing symbol flashes, then try again.",
        )
    if "stale BLE pairing" in output or "pairing key does not match" in output:
        return BloodPressureFetchError(
            "pairing_error",
            "Bluetooth pairing with the monitor is broken. Re-pair the device "
            "with 'omblepy.py --pair' and remove stale OS pairings.",
        )
    if "required bluetooth attributes not found" in output:
        return BloodPressureFetchError(
            "wrong_device",
            "Connected to a device that is not the configured Omron monitor. "
            "Check BP_DEVICE_MAC.",
        )
    tail = output.strip().splitlines()[-3:]
    return BloodPressureFetchError("error", " | ".join(tail) or "omblepy failed")


def _parse_result_json(output: str) -> BloodPressureReading | None:
    """Return the newest reading from omblepy's ``--jsonOut`` stdout line."""
    payload: str | None = None
    for line in output.splitlines():
        if line.startswith(_RESULT_MARKER):
            payload = line[len(_RESULT_MARKER):]
    if payload is None:
        return None
    try:
        all_user_records = json.loads(payload)
    except json.JSONDecodeError:
        return None
    latest: BloodPressureReading | None = None
    for user_records in all_user_records:
        for row in user_records:
            try:
                reading = BloodPressureReading(
                    systolic=int(row["sys"]),
                    diastolic=int(row["dia"]),
                    pulse_bpm=int(row["bpm"]),
                    measured_at=datetime.strptime(
                        row["datetime"], "%Y-%m-%d %H:%M:%S"
                    ),
                    irregular_heartbeat=bool(int(row.get("ihb") or 0)),
                    body_movement=bool(int(row.get("mov") or 0)),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if latest is None or reading.measured_at > latest.measured_at:
                latest = reading
    return latest


class BloodPressureService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.omblepy_dir = (
            Path(settings.bp_omblepy_dir).expanduser()
            if settings.bp_omblepy_dir
            else _default_omblepy_dir()
        )
        self.python_bin = settings.bp_python_bin or sys.executable

    @property
    def is_busy(self) -> bool:
        return self._lock.locked()

    async def fetch_latest(self) -> BloodPressureReading:
        """Run omblepy against the configured cuff and return its newest record.

        Raises :class:`BloodPressureFetchError` with a machine-readable
        ``code`` (busy / not_configured / device_not_found / pairing_error /
        wrong_device / timeout / no_records / error) on any failure.
        """
        if not settings.bp_device_mac:
            raise BloodPressureFetchError(
                "not_configured",
                "BP_DEVICE_MAC is not set in the API .env file.",
            )
        if not (self.omblepy_dir / "omblepy.py").exists():
            raise BloodPressureFetchError(
                "not_configured",
                f"omblepy.py not found in {self.omblepy_dir}. Set BP_OMBLEPY_DIR.",
            )
        if self._lock.locked():
            raise BloodPressureFetchError(
                "busy", "A blood pressure fetch is already in progress."
            )

        async with self._lock:
            # No ``-t`` (device clock sync): the hem-7280t driver has no
            # settingsTimeSyncBytes section and crashes on it. The kiosk's
            # freshness check instead trusts the cuff clock within a
            # 90-second skew window.
            # ``-l`` (latest only) reads just the newest record per user via
            # the ring-buffer write pointer instead of dumping the cuff's
            # full memory — much faster, and read-only on the device.
            # ``--jsonOut`` returns the reading on stdout; nothing is
            # written to disk.
            cmd = [
                self.python_bin,
                "omblepy.py",
                "-l",
                "--jsonOut",
                "-d",
                settings.bp_device_name,
                "-m",
                settings.bp_device_mac,
            ]
            logger.info("Starting omblepy fetch: %s", " ".join(cmd))
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.omblepy_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                raw_output, _ = await asyncio.wait_for(
                    process.communicate(), timeout=settings.bp_fetch_timeout_seconds
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise BloodPressureFetchError(
                    "timeout",
                    "Timed out talking to the blood pressure monitor. "
                    "Make sure it is nearby and try again.",
                )

            output = raw_output.decode("utf-8", errors="replace")
            logger.info(
                "omblepy exited rc=%s, output tail: %s",
                process.returncode,
                " | ".join(output.strip().splitlines()[-3:]),
            )
            if process.returncode != 0 or "communication finished" not in output:
                raise _classify_failure(output)

            reading = _parse_result_json(output)
            if reading is None:
                raise BloodPressureFetchError(
                    "no_records",
                    "The monitor has no stored measurements yet. Take a "
                    "measurement first, then fetch again.",
                )
            return reading

    @staticmethod
    def is_recent(reading: BloodPressureReading) -> bool:
        """Heuristic freshness check (device clock vs server clock)."""
        return abs(datetime.now() - reading.measured_at) <= _RECENT_WINDOW

    # ── Admin: device discovery + pairing ────────────────────────────────

    def supported_models(self) -> list[str]:
        """Device model ids omblepy ships a driver for (deviceSpecific/*.py)."""
        driver_dir = self.omblepy_dir / "deviceSpecific"
        if not driver_dir.is_dir():
            return []
        return sorted(
            p.stem for p in driver_dir.glob("*.py") if not p.stem.startswith("_")
        )

    async def scan_devices(self, duration: float = 6.0) -> list[dict]:
        """BLE discovery sweep, mirroring omblepy's selection table.

        Returns dicts of ``{mac, name, rssi, is_omron}`` with likely Omron
        monitors first, then descending signal strength. Shares the fetch
        lock — the adapter can't scan reliably mid-connection.
        """
        if self._lock.locked():
            raise BloodPressureFetchError(
                "busy", "A blood pressure operation is already in progress."
            )
        async with self._lock:
            found = await bleak.BleakScanner.discover(
                timeout=duration, return_adv=True
            )
        devices = []
        for mac, (ble_dev, adv) in found.items():
            name = ble_dev.name or adv.local_name
            rssi = adv.rssi if adv.rssi is not None and adv.rssi != 127 else None
            devices.append(
                {
                    "mac": mac,
                    "name": name,
                    "rssi": rssi,
                    "is_omron": bool(name and _OMRON_NAME.search(name)),
                }
            )
        devices.sort(
            key=lambda d: (
                not d["is_omron"],
                -(d["rssi"] if d["rssi"] is not None else -999),
            )
        )
        return devices

    async def pair_device(self, mac: str, device_name: str) -> None:
        """Program the pairing key into a cuff (omblepy ``--pair``) and
        persist it as the configured kiosk device.

        The monitor must be in pairing mode (hold its Bluetooth button
        until the pairing symbol flashes). Raises
        :class:`BloodPressureFetchError` on any failure.
        """
        mac = mac.strip()
        if not (_VALID_MAC.match(mac) or _VALID_UUID.match(mac)):
            raise BloodPressureFetchError(
                "invalid", f"'{mac}' is not a valid Bluetooth address."
            )
        if device_name not in self.supported_models():
            raise BloodPressureFetchError(
                "invalid",
                f"Unsupported device model '{device_name}'. "
                f"Available: {', '.join(self.supported_models())}",
            )
        if self._lock.locked():
            raise BloodPressureFetchError(
                "busy", "A blood pressure operation is already in progress."
            )

        async with self._lock:
            cmd = [
                self.python_bin,
                "omblepy.py",
                "-p",
                "-d",
                device_name,
                "-m",
                mac,
            ]
            logger.info("Starting omblepy pairing: %s", " ".join(cmd))
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.omblepy_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                raw_output, _ = await asyncio.wait_for(
                    process.communicate(), timeout=settings.bp_fetch_timeout_seconds
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise BloodPressureFetchError(
                    "timeout",
                    "Timed out while pairing. Put the monitor back in "
                    "pairing mode and try again.",
                )

            output = raw_output.decode("utf-8", errors="replace")
            logger.info(
                "omblepy pairing exited rc=%s, output tail: %s",
                process.returncode,
                " | ".join(output.strip().splitlines()[-3:]),
            )
            if process.returncode != 0 or "Paired device successfully" not in output:
                err = _classify_failure(output)
                if err.code in {"device_not_found", "timeout"}:
                    # Reword the fetch-oriented guidance for pairing.
                    err = BloodPressureFetchError(
                        "device_not_found",
                        "Could not connect to the monitor. Hold its "
                        "Bluetooth button until the pairing symbol flashes, "
                        "then scan and pair again.",
                    )
                raise err

        # Persist as the active kiosk device: in-memory first (takes effect
        # for the next fetch immediately), then .env so it survives restart.
        settings.bp_device_name = device_name
        settings.bp_device_mac = mac
        try:
            _persist_env_keys(
                {"BP_DEVICE_NAME": device_name, "BP_DEVICE_MAC": mac}
            )
        except OSError:
            logger.exception("Paired OK but failed to persist .env config")


def _persist_env_keys(values: dict[str, str]) -> None:
    """Upsert key=value lines in the API's .env file (repo conventions:
    plain KEY=VALUE lines, no quoting needed for these values)."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(values)
    for idx, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            lines[idx] = f"{key}={remaining.pop(key)}"
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
