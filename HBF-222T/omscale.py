"""
omscale - read records from Omron Bluetooth-LE body composition monitors / scales
(e.g. VIVA HBF-222T, BCM-500 / HBF-255T, HBF-702T and other "OMRON connect" scales).

Unlike the Omron blood pressure monitors handled by omblepy.py (proprietary
eeprom-read protocol), the scales implement the standard BLE weight scale
profile: User Data Service consent + Record Access Control Point, with records
delivered on Omron's custom OmronMeasurementWS characteristic.

PLATFORM NOTE (important):
  This scale requires an ENCRYPTED (bonded) BLE link before it will expose any
  measurement data. On Linux (BlueZ) bleak's client.pair() establishes that bond
  and this tool works (this is how magcode/omviva reads the same scale). On macOS
  CoreBluetooth there is NO pairing API - bonding is only auto-triggered when a
  protected characteristic is accessed, and THIS scale never completes that
  handshake (it neither sends its own SMP security request nor accepts a
  Mac-initiated one; every protected op ends in "Insufficient Encryption" and the
  scale drops the link after ~30s). Verified exhaustively 2026-07: standard
  pairing, read-triggered bonding, notification-triggered bonding, time-sync
  priming, and the proprietary omblepy channel all fail on macOS.
  => On macOS, use the OMRON connect app + omramin cloud sync instead (see below).
     Direct BLE reading needs a Linux host (e.g. Raspberry Pi / Linux VM).

Protocol references:
  https://github.com/userx14/omblepy/issues/35
  https://github.com/magcode/omviva
  https://github.com/huraypositive/omron-android-sdk (OmronMeasurementWS.java)

Usage:
  python omscale.py -p -u 1              # first time: register/pair user slot 1
  python omscale.py -u 1                 # read new records of user slot 1
  python omscale.py -u 1 --all           # re-read all stored records
  python omscale.py -u 1 -m <mac/uuid>   # skip scan dialog
  python omscale.py -u 1 --jsonOut      # print records as one JSON line
"""

import argparse
import asyncio
import csv
import datetime
import json
import logging
import pathlib
import struct
import sys
import time

import bleak
import terminaltables

logger = logging.getLogger("omscale")

USER_CONTROL_POINT_UUID = "00002a9f-0000-1000-8000-00805f9b34fb"
RECORD_ACCESS_CONTROL_POINT_UUID = "00002a52-0000-1000-8000-00805f9b34fb"
OMRON_MEASUREMENT_WS_UUID = "8ff2ddfb-4a52-4ce5-85a4-d2f97917792a"
BODY_COMPOSITION_MEASUREMENT_UUID = "00002a9c-0000-1000-8000-00805f9b34fb"


DEFAULT_CONSENT_CODE = 0x020E

STATE_FILE = pathlib.Path(__file__).with_name("omscale_state.json")

# daemon-mode trigger bookkeeping: "BLEsmart_..." (lowercase s) is the explicit
# transfer mode (bluetooth button), but right after a measurement the scale may
# only send its idle-style beacon. Like magcode/omviva, try a sync on ANY
# advertisement from the scale - with a growing cooldown for non-sync-ready
# triggers so an idle beacon can't make the daemon hammer the scale.
_IDLE_TRIGGER = {
    "cooldownUntil": 0.0,     # monotonic time before which idle adverts are ignored
    "backoff": 60.0,          # current cooldown length, seconds
    "lastWasSyncReady": True,
}
_IDLE_BACKOFF_MIN = 60.0
_IDLE_BACKOFF_MAX = 900.0


def _startIdleCooldown(reason):
    _IDLE_TRIGGER["cooldownUntil"] = time.monotonic() + _IDLE_TRIGGER["backoff"]
    logger.info(f"{reason}; ignoring idle adverts for {int(_IDLE_TRIGGER['backoff'])}s "
                "(sync-ready 'BLEsmart_' adverts still trigger instantly)")
    _IDLE_TRIGGER["backoff"] = min(_IDLE_TRIGGER["backoff"] * 2, _IDLE_BACKOFF_MAX)

CSV_FIELDS = [
    "datetime", "sequence", "userSlot", "weight", "weightUnit", "bmi",
    "height", "heightUnit", "bodyFatPercent", "basalMetabolismKcal",
    "musclePercent", "muscleMass", "fatFreeMass", "softLeanMass",
    "bodyWaterMass", "impedanceOhm", "skeletalMusclePercent",
    "visceralFatLevel", "bodyAge",
]

WEIGHT_ONLY_FIELDS = ["datetime", "sequence", "weight", "weightUnit"]


class MeasurementFlags:
    IMPERIAL_UNIT = 1 << 0
    SEQUENCE_NUMBER = 1 << 1
    WEIGHT = 1 << 2
    TIMESTAMP = 1 << 3
    USER_ID = 1 << 4
    BMI_AND_HEIGHT = 1 << 5
    BODY_FAT_PERCENTAGE = 1 << 6
    BASAL_METABOLISM = 1 << 7
    MUSCLE_PERCENTAGE = 1 << 8
    MUSCLE_MASS = 1 << 9
    FAT_FREE_MASS = 1 << 10
    SOFT_LEAN_MASS = 1 << 11
    BODY_WATER_MASS = 1 << 12
    IMPEDANCE = 1 << 13
    SKELETAL_MUSCLE_PERCENTAGE = 1 << 14
    VISCERAL_FAT_LEVEL = 1 << 15
    BODY_AGE = 1 << 16
    BODY_FAT_STAGE = 1 << 17
    SKELETAL_MUSCLE_STAGE = 1 << 18
    VISCERAL_FAT_STAGE = 1 << 19
    MULTIPLE_PACKET = 1 << 20

    WEIGHT_RESOLUTION_KG = 0.005
    WEIGHT_RESOLUTION_LB = 0.01
    HEIGHT_RESOLUTION_M = 0.001
    HEIGHT_RESOLUTION_IN = 0.1


def parseMeasurementPacket(record, data):
    """Parse one OmronMeasurementWS packet into the record dict.
    Returns True if the measurement continues in a follow-up packet."""
    flags = int.from_bytes(data[0:3], "little")
    offset = 3

    if flags & MeasurementFlags.IMPERIAL_UNIT:
        weightRes = MeasurementFlags.WEIGHT_RESOLUTION_LB
        heightRes = MeasurementFlags.HEIGHT_RESOLUTION_IN
        record["weightUnit"] = "lb"
        record["heightUnit"] = "in"
    else:
        weightRes = MeasurementFlags.WEIGHT_RESOLUTION_KG
        heightRes = MeasurementFlags.HEIGHT_RESOLUTION_M
        record["weightUnit"] = "kg"
        record["heightUnit"] = "m"

    def u16():
        nonlocal offset
        value = int.from_bytes(data[offset:offset + 2], "little")
        offset += 2
        return value

    def u8():
        nonlocal offset
        value = data[offset]
        offset += 1
        return value

    if flags & MeasurementFlags.SEQUENCE_NUMBER:
        record["sequence"] = u16()
    if flags & MeasurementFlags.WEIGHT:
        record["weight"] = round(u16() * weightRes, 3)
    if flags & MeasurementFlags.TIMESTAMP:
        year = u16()
        month, day, hour, minute, second = data[offset:offset + 5]
        offset += 5
        record["datetime"] = f"{year:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}"
    if flags & MeasurementFlags.USER_ID:
        record["userSlot"] = u8()
    if flags & MeasurementFlags.BMI_AND_HEIGHT:
        record["bmi"] = round(u16() * 0.1, 1)
        record["height"] = round(u16() * heightRes, 3)
    if flags & MeasurementFlags.BODY_FAT_PERCENTAGE:
        record["bodyFatPercent"] = round(u16() * 0.1, 1)
    if flags & MeasurementFlags.BASAL_METABOLISM:
        record["basalMetabolismKcal"] = u16()
    if flags & MeasurementFlags.MUSCLE_PERCENTAGE:
        record["musclePercent"] = round(u16() * 0.1, 1)
    if flags & MeasurementFlags.MUSCLE_MASS:
        record["muscleMass"] = round(u16() * weightRes, 3)
    if flags & MeasurementFlags.FAT_FREE_MASS:
        record["fatFreeMass"] = round(u16() * weightRes, 3)
    if flags & MeasurementFlags.SOFT_LEAN_MASS:
        record["softLeanMass"] = round(u16() * weightRes, 3)
    if flags & MeasurementFlags.BODY_WATER_MASS:
        record["bodyWaterMass"] = round(u16() * weightRes, 3)
    if flags & MeasurementFlags.IMPEDANCE:
        record["impedanceOhm"] = round(u16() * 0.1, 1)
    if flags & MeasurementFlags.SKELETAL_MUSCLE_PERCENTAGE:
        record["skeletalMusclePercent"] = round(u16() * 0.1, 1)
    if flags & MeasurementFlags.VISCERAL_FAT_LEVEL:
        record["visceralFatLevel"] = u8() * 0.5
    if flags & MeasurementFlags.BODY_AGE:
        record["bodyAge"] = u8()
    if flags & MeasurementFlags.BODY_FAT_STAGE:
        u8()
    if flags & MeasurementFlags.SKELETAL_MUSCLE_STAGE:
        u8()
    if flags & MeasurementFlags.VISCERAL_FAT_STAGE:
        u8()

    return bool(flags & MeasurementFlags.MULTIPLE_PACKET)


def parseMeasurementPackets(packets):
    """Group raw notification packets into records; a packet with the
    multiple-packet flag set is continued by the following packet."""
    records = []
    idx = 0
    while idx < len(packets):
        record = {}
        try:
            hasContinuation = parseMeasurementPacket(record, packets[idx])
            idx += 1
            if hasContinuation and idx < len(packets):
                parseMeasurementPacket(record, packets[idx])
                idx += 1
        except IndexError:
            logger.warning(f"short/unparseable measurement packet: {bytes(packets[idx - 1]).hex()}")
            continue
        records.append(record)
    return records


def parseWeightMeasurement(data):
    """standard Weight Scale Service 2a9d indication"""
    flags = data[0]
    imperial = flags & 0x01
    offset = 1
    record = {}
    rawWeight = int.from_bytes(data[offset:offset + 2], "little")
    record["weight"] = round(rawWeight * (0.01 if imperial else 0.005), 2)
    record["weightUnit"] = "lb" if imperial else "kg"
    offset += 2
    if flags & 0x02:  # timestamp
        year, month, day, hour, minute, sec = struct.unpack_from("<HBBBBB", data, offset)
        record["datetime"] = datetime.datetime(year, month, day, hour, minute, sec)
        offset += 7
    if flags & 0x04:  # user id
        record["userSlot"] = data[offset]
        offset += 1
    if flags & 0x08:  # BMI + height
        record["bmi"] = int.from_bytes(data[offset:offset + 2], "little") * 0.1
        rawHeight = int.from_bytes(data[offset + 2:offset + 4], "little")
        record["height"] = round(rawHeight * (0.1 if imperial else 0.001), 3)
        record["heightUnit"] = "in" if imperial else "m"
    return record


def parseBodyCompositionMeasurement(data):
    """standard Body Composition Service 2a9c indication"""
    flags = int.from_bytes(data[0:2], "little")
    imperial = flags & 0x0001
    massScale = 0.01 if imperial else 0.005
    offset = 2
    record = {}
    record["bodyFatPercent"] = int.from_bytes(data[offset:offset + 2], "little") * 0.1
    offset += 2
    if flags & 0x0002:  # timestamp
        year, month, day, hour, minute, sec = struct.unpack_from("<HBBBBB", data, offset)
        record["datetime"] = datetime.datetime(year, month, day, hour, minute, sec)
        offset += 7
    if flags & 0x0004:  # user id
        record["userSlot"] = data[offset]
        offset += 1
    if flags & 0x0008:  # basal metabolism, kJ
        record["basalMetabolismKcal"] = round(int.from_bytes(data[offset:offset + 2], "little") / 4.184)
        offset += 2
    if flags & 0x0010:  # muscle percentage
        record["musclePercent"] = int.from_bytes(data[offset:offset + 2], "little") * 0.1
        offset += 2
    if flags & 0x0020:  # muscle mass
        record["muscleMass"] = round(int.from_bytes(data[offset:offset + 2], "little") * massScale, 2)
        offset += 2
    if flags & 0x0040:  # fat free mass
        record["fatFreeMass"] = round(int.from_bytes(data[offset:offset + 2], "little") * massScale, 2)
        offset += 2
    if flags & 0x0080:  # soft lean mass
        record["softLeanMass"] = round(int.from_bytes(data[offset:offset + 2], "little") * massScale, 2)
        offset += 2
    if flags & 0x0100:  # body water mass
        record["bodyWaterMass"] = round(int.from_bytes(data[offset:offset + 2], "little") * massScale, 2)
        offset += 2
    if flags & 0x0200:  # impedance
        record["impedanceOhm"] = int.from_bytes(data[offset:offset + 2], "little") * 0.1
        offset += 2
    if flags & 0x0400:  # weight
        record["weight"] = round(int.from_bytes(data[offset:offset + 2], "little") * massScale, 2)
        record["weightUnit"] = "lb" if imperial else "kg"
        offset += 2
    return record


class OmronScaleReader:
    def __init__(self, bleClient):
        self.bleClient = bleClient
        self.measurementPackets = []
        self.ucpResponse = None
        self.ucpEvent = asyncio.Event()
        self.racpResponse = None
        self.racpEvent = asyncio.Event()
        self.storedRecordCount = None
        # measurements received via the standard 2a9d/2a9c indications,
        # keyed by timestamp so weight + body composition merge into one record
        self.standardRecords = {}
        self.measurementEvent = asyncio.Event()

    def _callback(self, characteristic, data):
        uuid = characteristic.uuid.lower()
        logger.debug(f"rx {uuid} < {bytes(data).hex()}")
        if uuid == OMRON_MEASUREMENT_WS_UUID:
            self.measurementPackets.append(bytes(data))
        elif uuid == USER_CONTROL_POINT_UUID:
            self.ucpResponse = bytes(data)
            self.ucpEvent.set()
        elif uuid == RECORD_ACCESS_CONTROL_POINT_UUID:
            if data[0] == 0x05:
                self.storedRecordCount = int.from_bytes(data[2:4], "little")
                logger.info(f"device reports {self.storedRecordCount} stored record(s)")
            else:
                self.racpResponse = bytes(data)
                self.racpEvent.set()
        elif uuid == self.WEIGHT_MEASUREMENT_UUID or uuid == BODY_COMPOSITION_MEASUREMENT_UUID:
            try:
                if uuid == self.WEIGHT_MEASUREMENT_UUID:
                    record = parseWeightMeasurement(bytes(data))
                else:
                    record = parseBodyCompositionMeasurement(bytes(data))
            except Exception as e:
                logger.warning(f"failed to parse measurement indication {bytes(data).hex()}: {e}")
                return
            key = record.get("datetime") or datetime.datetime.now().replace(microsecond=0)
            record["datetime"] = key
            record["sequence"] = int(key.timestamp())
            merged = self.standardRecords.setdefault(key, {})
            merged.update(record)
            logger.info(f"measurement received: {merged}")
            self.measurementEvent.set()

    # the scale rejects User Control Point commands with 0xFD "CCCD improperly
    # configured" unless the standard measurement indications are enabled too,
    # like the official app does (the macOS bonding workaround already subscribes
    # to the proprietary channels; these are the standard-profile counterparts)
    AUXILIARY_NOTIFY_UUIDS = [
        "00002a9d-0000-1000-8000-00805f9b34fb",  # weight measurement (indicate)
        "00002a9c-0000-1000-8000-00805f9b34fb",  # body composition measurement (indicate)
        "00002a99-0000-1000-8000-00805f9b34fb",  # database change increment (notify)
    ]

    async def enableNotifications(self):
        # subscribe ONLY the three transfer channels (subscribing the standard
        # 2a9d/2a9c/2a99 characteristics as well makes this scale reject all
        # RACP commands with 0x0E). start quickly: the post-measurement sync
        # window closes ~5s after connect if the client stays silent.
        await asyncio.sleep(1)
        for uuid in [USER_CONTROL_POINT_UUID, RECORD_ACCESS_CONTROL_POINT_UUID, OMRON_MEASUREMENT_WS_UUID]:
            await self.bleClient.start_notify(uuid, self._callback)
            logger.debug(f"subscribed {uuid}")
        await asyncio.sleep(2)
        # BlueZ's StartNotify can return before the CCCD write has actually gone
        # out over the air; writing to the control points in that window makes the
        # scale answer 0xFD "CCCD Improperly Configured". Give the writes a moment.
        await asyncio.sleep(1.5)

    async def disableNotifications(self):
        for uuid in [USER_CONTROL_POINT_UUID, RECORD_ACCESS_CONTROL_POINT_UUID, OMRON_MEASUREMENT_WS_UUID]:
            try:
                await self.bleClient.stop_notify(uuid)
            except Exception:
                pass

    PAIRING_FAILED_HELP = (
        "The scale rejected BLE bonding. Most effective fix: wipe the scale's own pairing memory\n"
        "(manual section 13 'Delete the Communication Setting'; stored measurements are kept):\n"
        "  1. hold the bluetooth button >2s        -> 'P' + bluetooth symbol blink\n"
        "  2. hold the bluetooth button >2s AGAIN  -> 'CLr' blinks\n"
        "  3. press the SET button to confirm      -> pairing memory wiped\n"
        "  4. hold the bluetooth button >2s ('P' blinks) and run this script again right away.\n"
        "NOTE: this also unpairs the scale from the OMRON connect phone app (re-add it there later).\n"
        "Keep your phone's bluetooth OFF while pairing with this script, and make sure 'P' is still\n"
        "blinking at the moment the script connects."
    )

    # RX channels of Omron's proprietary transfer service - the same service the
    # omblepy blood pressure monitors use. Subscribing to these is what makes an
    # Omron device in pairing mode send the SMP Security Request that starts OS
    # pairing on macOS (the device must initiate; it ignores central-side pairing).
    LEGACY_RX_CHAR_UUIDS = [
        "49123040-aee8-11e1-a74d-0002a5d5c51b",
        "4d0bf320-aee8-11e1-a0d9-0002a5d5c51b",
        "5128ce60-aee8-11e1-b84b-0002a5d5c51b",
        "560f1420-aee8-11e1-8184-0002a5d5c51b",
        "8858eb40-aee8-11e1-bb67-0002a5d5c51b",
    ]
    WEIGHT_MEASUREMENT_UUID = "00002a9d-0000-1000-8000-00805f9b34fb"
    CURRENT_TIME_UUID = "00002a2b-0000-1000-8000-00805f9b34fb"
    # user-data characteristics are encryption-protected: reading one tells us
    # when the link has finally been encrypted (and nudges the OS to pair)
    PROTECTED_CANARY_UUIDS = [
        "00002a85-0000-1000-8000-00805f9b34fb",  # date of birth
        "00002a8e-0000-1000-8000-00805f9b34fb",  # height
        "00002a8c-0000-1000-8000-00805f9b34fb",  # gender
    ]

    async def triggerBonding(self):
        """macOS has no explicit BLE pair API and this scale ignores Mac-initiated
        pairing. Mimic the working omblepy blood-pressure flow instead: subscribe
        to Omron's proprietary transfer channels so the device fires its own SMP
        security request, then poll a protected characteristic until the link is
        encrypted. Returns True once encrypted."""
        # On Linux/BlueZ the bond is established by the OS - either a one-time
        # `bluetoothctl pair`, or BleakClient.pair() in connectToScale - and the
        # stored keys encrypt the link automatically on connect. The macOS dance
        # below only wastes the scale's short (~30s) connection window here, and
        # its protected-canary read always fails pre-registration anyway, so skip
        # it off macOS and go straight to register/read.
        if sys.platform != "darwin":
            logger.info("linux/bluez: relying on the OS-level bond, skipping the macOS bonding workaround")
            return True

        def dummyCallback(characteristic, data):
            logger.debug(f"rx (bonding trigger) {characteristic.uuid} < {bytes(data).hex()}")

        for uuid in self.LEGACY_RX_CHAR_UUIDS + [self.WEIGHT_MEASUREMENT_UUID]:
            if self.bleClient.services.get_characteristic(uuid) is None:
                logger.debug(f"bonding-trigger char {uuid} not present, skipped")
                continue
            try:
                await self.bleClient.start_notify(uuid, dummyCallback)
                logger.debug(f"subscribed bonding-trigger char {uuid}")
            except Exception as e:
                logger.debug(f"start_notify {uuid} failed (ignored): {e}")

        # the official app's first action is a time sync (unencrypted write); the
        # scale may wait for this app-like behaviour before engaging in pairing
        try:
            now = datetime.datetime.now()
            ctsPayload = struct.pack("<HBBBBBBBB", now.year, now.month, now.day,
                                     now.hour, now.minute, now.second, now.isoweekday(), 0, 0)
            await self.bleClient.write_gatt_char(self.CURRENT_TIME_UUID, ctsPayload, response=True)
            logger.debug("current time written (time sync)")
            await asyncio.sleep(2)
        except Exception as e:
            logger.debug(f"current time write failed (ignored): {e}")

        canary = None
        for uuid in self.PROTECTED_CANARY_UUIDS:
            canary = self.bleClient.services.get_characteristic(uuid)
            if canary is not None:
                break
        if canary is None:
            logger.debug("no protected canary characteristic found, skipping bonding wait")
            return False

        logger.info("waiting for BLE bonding - if a macOS pairing dialog appears, ACCEPT it...")
        for attempt in range(1, 4):
            if not self.bleClient.is_connected:
                raise OSError(f"The scale dropped the connection while bonding.\n{self.PAIRING_FAILED_HELP}")
            try:
                await asyncio.wait_for(self.bleClient.read_gatt_char(canary), 35)
                logger.info("link is encrypted - bonding complete")
                return True
            except Exception as e:
                if not self.bleClient.is_connected:
                    raise OSError(f"The scale dropped the connection while bonding.\n{self.PAIRING_FAILED_HELP}") from e
                logger.debug(f"bonding not finished yet (attempt {attempt}/3): {e}")
                await asyncio.sleep(2)
        raise OSError(f"BLE bonding did not complete.\n{self.PAIRING_FAILED_HELP}")

    async def _writeAndWait(self, charUuid, payload, event, timeout, what):
        event.clear()
        logger.debug(f"tx {charUuid} > {payload.hex()}")
        for attempt in range(1, 4):
            if not self.bleClient.is_connected:
                raise OSError(f"The scale dropped the connection during {what}.\n{self.PAIRING_FAILED_HELP}")
            try:
                await self.bleClient.write_gatt_char(charUuid, payload, response=True)
                break
            except Exception as e:
                if not self.bleClient.is_connected:
                    raise OSError(f"The scale dropped the connection during {what}.\n{self.PAIRING_FAILED_HELP}") from e
                errorText = str(e).lower()
                if "unlikely" in errorText:
                    # scale is momentarily busy (e.g. right after consent/db-change
                    # indication) - wait and retry
                    if attempt == 3:
                        raise
                    logger.warning(f"scale busy ({what}, attempt {attempt}/3) - retrying in 2s...")
                    await asyncio.sleep(2)
                    continue
                if "improperly configured" in errorText:
                    # the CCCD write from start_notify hasn't landed on the scale
                    # yet (BlueZ StartNotify returns early) - re-subscribe and retry
                    if attempt == 3:
                        raise OSError(f"scale kept rejecting {what} with 'CCCD improperly configured' - "
                                      "indications never got enabled on the control point") from e
                    logger.warning(f"scale says indications not enabled yet ({what}, attempt {attempt}/3) - "
                                   "re-subscribing and retrying in 2s...")
                    try:
                        await self.bleClient.stop_notify(charUuid)
                    except Exception:
                        pass
                    try:
                        await self.bleClient.start_notify(charUuid, self._callback)
                    except Exception as notifyError:
                        logger.debug(f"re-subscribe {charUuid} failed (ignored): {notifyError}")
                    await asyncio.sleep(2)
                    continue
                if "insufficient encryption" not in errorText and "insufficient authentication" not in errorText:
                    raise
                if attempt == 3:
                    raise OSError(f"BLE bonding did not complete (insufficient encryption).\n{self.PAIRING_FAILED_HELP}")
                logger.warning(f"link not encrypted yet ({what}, attempt {attempt}/3) - "
                               "waiting for the OS to finish bonding (this device shows no pairing "
                               "dialog), retrying in 2s...")
                await asyncio.sleep(2)
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except asyncio.TimeoutError:
            if not self.bleClient.is_connected:
                raise OSError(f"The scale dropped the connection during {what}.\n{self.PAIRING_FAILED_HELP}")
            raise TimeoutError(f"no response from scale to {what} within {timeout}s")

    async def registerUser(self, consentCode):
        payload = bytes([0x01, consentCode & 0xFF, (consentCode >> 8) & 0xFF])
        await self._writeAndWait(USER_CONTROL_POINT_UUID, payload, self.ucpEvent, 15, "register user")
        response = self.ucpResponse
        if len(response) >= 3 and response[0] == 0x20 and response[2] == 0x01:
            assignedIndex = response[3] if len(response) > 3 else None
            logger.info(f"user registered successfully (device assigned slot {assignedIndex})")
            return assignedIndex
        raise ValueError(f"user registration failed, device response: {response.hex()}. "
                         "Is the scale in pairing mode (user selected, bluetooth button held)?")

    async def sendConsent(self, userIndex, consentCode):
        payload = bytes([0x02, userIndex, consentCode & 0xFF, (consentCode >> 8) & 0xFF])
        await self._writeAndWait(USER_CONTROL_POINT_UUID, payload, self.ucpEvent, 15, "user consent")
        response = self.ucpResponse
        if len(response) >= 3 and response[0] == 0x20 and response[2] == 0x01:
            logger.info(f"consent accepted for user slot {userIndex}")
            return
        raise ValueError(f"consent rejected for user slot {userIndex}, device response: {response.hex()}. "
                         "Pair this user slot first with: python omscale.py -p -u <slot>")

    async def syncTime(self):
        # the official app's first action after connecting is a current-time
        # write; the scale can refuse record access until its clock is set
        try:
            now = datetime.datetime.now()
            ctsPayload = struct.pack("<HBBBBBBBB", now.year, now.month, now.day,
                                     now.hour, now.minute, now.second, now.isoweekday(), 0, 0)
            await self.bleClient.write_gatt_char(self.CURRENT_TIME_UUID, ctsPayload, response=True)
            logger.debug("current time written (time sync)")
            await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"current time write failed (ignored): {e}")

    async def readRecords(self, fromSequence):
        # give the scale a moment to finish its post-consent housekeeping (it
        # indicates the database change increment right after consent; an RACP
        # write in that window gets rejected with ATT 0x0E "Unlikely Error")
        await asyncio.sleep(3)
        seqLo, seqHi = fromSequence & 0xFF, (fromSequence >> 8) & 0xFF
        # opcode 0x04 = report number of stored records, operator 0x03 = greater/
        # equal, filter 0x01 = sequence number (omviva always uses this form)
        countRequest = bytes([0x04, 0x03, 0x01, seqLo, seqHi])
        try:
            logger.debug(f"tx {RECORD_ACCESS_CONTROL_POINT_UUID} > {countRequest.hex()}")
            await self.bleClient.write_gatt_char(RECORD_ACCESS_CONTROL_POINT_UUID, countRequest, response=True)
        except Exception as e:
            logger.debug(f"record-count request failed (ignored): {e}")
        await asyncio.sleep(3)

        # opcode 0x01 = report stored records, same sequence filter
        readRequest = bytes([0x01, 0x03, 0x01, seqLo, seqHi])
        try:
            logger.debug(f"tx {RECORD_ACCESS_CONTROL_POINT_UUID} > {readRequest.hex()}")
            await self.bleClient.write_gatt_char(RECORD_ACCESS_CONTROL_POINT_UUID, readRequest, response=True)
            try:
                await asyncio.wait_for(self.racpEvent.wait(), 30)
            except asyncio.TimeoutError:
                pass
        except Exception as e:
            if not self.bleClient.is_connected:
                raise OSError(f"The scale dropped the connection during record readout.\n{self.PAIRING_FAILED_HELP}") from e
            logger.info(f"RACP record readout not supported by this scale ({e}) - "
                        "waiting for live measurement indications instead")

        # wait for measurements pushed via the standard weight / body composition
        # indications. the scale sends stored unsynced records right away, and a
        # live weigh-in during the session arrives the same way.
        if not self.standardRecords and not self.measurementPackets:
            logger.info("no stored records received - STEP ON THE SCALE NOW for a live "
                        "measurement (waiting up to 60s while the connection lasts)...")
        deadline = asyncio.get_event_loop().time() + 60
        while self.bleClient.is_connected and asyncio.get_event_loop().time() < deadline:
            self.measurementEvent.clear()
            try:
                await asyncio.wait_for(self.measurementEvent.wait(), 5)
                # got a measurement - keep listening briefly for its counterpart
                # indication (weight vs body composition), then wrap up
                deadline = min(deadline, asyncio.get_event_loop().time() + 8)
            except asyncio.TimeoutError:
                if self.standardRecords or self.measurementPackets:
                    break
        if not self.bleClient.is_connected:
            logger.info("scale closed the connection")
        if self.racpResponse and self.racpResponse[0] == 0x06 and len(self.racpResponse) >= 4 and self.racpResponse[3] == 0x06:
            logger.info("no new records on the device")

        # omron extension seen in the official app traffic, signals end of transfer
        if self.bleClient.is_connected:
            try:
                await self.bleClient.write_gatt_char(RECORD_ACCESS_CONTROL_POINT_UUID, bytes([0x10, 0x00]), response=True)
                await asyncio.sleep(1)
            except Exception as e:
                logger.debug(f"end-of-transfer command failed (ignored): {e}")

        records = parseMeasurementPackets(self.measurementPackets)
        for key in sorted(self.standardRecords):
            records.append(self.standardRecords[key])
        return records


def loadState():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"address": None, "lastSequence": {}}


def saveState(state):
    STATE_FILE.write_text(json.dumps(state, indent=4))


def mergeIntoCsv(records, userIndex, fields):
    csvPath = pathlib.Path(f"scale_user{userIndex}.csv")
    existing = {}
    if csvPath.exists():
        with open(csvPath, newline="", encoding="utf-8") as infile:
            for row in csv.DictReader(infile):
                existing[(row["datetime"], row["sequence"])] = row
    for record in records:
        row = {field: record.get(field, "") for field in fields}
        existing[(str(row["datetime"]), str(row["sequence"]))] = row
    rows = sorted(existing.values(), key=lambda r: str(r["datetime"]))
    with open(csvPath, mode="w", newline="", encoding="utf-8") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fields, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"wrote {len(rows)} record(s) to {csvPath}")


async def selectBLEdevices():
    print("Scanning for Omron devices (they advertise as BLEsmart_...); make sure the scale "
          "is awake (pairing mode or right after a measurement). Ctrl+C to abort.")
    while True:
        devices = await bleak.BleakScanner.discover(return_adv=True)
        devices = list(sorted(devices.items(), key=lambda x: x[1][1].rssi, reverse=True))
        # match on the name fresh from the advertisement; bleDev.name can be a
        # stale cached value on macOS
        omronDevices = [(macAddr, bleDev, advData) for macAddr, (bleDev, advData) in devices
                        if (advData.local_name or bleDev.name or "").lower().startswith("blesmart")]
        if len(omronDevices) == 1:
            macAddr, bleDev, advData = omronDevices[0]
            print(f"found Omron device '{advData.local_name or bleDev.name}' ({macAddr})")
            return macAddr
        if not omronDevices:
            print("no BLEsmart_ device seen yet, rescanning...")
            continue
        tableEntries = [["ID", "MAC/UUID", "NAME", "RSSI"]]
        for deviceIdx, (macAddr, bleDev, advData) in enumerate(omronDevices):
            tableEntries.append([deviceIdx, macAddr, advData.local_name or bleDev.name, advData.rssi])
        print(terminaltables.AsciiTable(tableEntries).table)
        res = input("Multiple Omron devices found. Enter ID or just press Enter to rescan.\n")
        if res.isdigit() and int(res) in range(len(omronDevices)):
            return omronDevices[int(res)][0]


async def connectToScale(bleAddr, syncReadyOnly=False):
    # the scale advertises "BLEsmart_..." (lowercase s) after a bluetooth-button
    # press and "BLESmart_..." (capital S) after a measurement / while recently
    # used. Verified 2026-07-28: capital-S sessions sync fine too (the earlier
    # consent failures were the pre-fix subscription bug), so the daemon reacts
    # to ANY advert from the scale - idle-beacon hammering is prevented by the
    # cooldown in the daemon loop, not by name filtering.
    foundDevice = None
    foundAdv = None
    foundEvent = asyncio.Event()
    lastSeen = {"name": None, "at": 0.0}

    def onAdvertisement(device, advData):
        nonlocal foundDevice, foundAdv
        if getattr(device, "address", "").upper() != bleAddr.upper():
            return
        if syncReadyOnly:
            advName = advData.local_name or ""
            now = time.monotonic()
            # log everything the scale broadcasts (rate-limited): the ground
            # truth for what it actually sends right after a measurement
            if advName != lastSeen["name"] or now - lastSeen["at"] > 10:
                lastSeen["name"], lastSeen["at"] = advName, now
                logger.info(f"heard scale advertisement '{advName or '<no name>'}' "
                            f"(rssi {advData.rssi})")
            if not advName.startswith("BLEsmart"):
                # not announced as sync-ready, but omviva syncs on any advert
                # from the scale - try it too, outside the cooldown window
                if now < _IDLE_TRIGGER["cooldownUntil"]:
                    return
                _IDLE_TRIGGER["lastWasSyncReady"] = False
            else:
                _IDLE_TRIGGER["lastWasSyncReady"] = True
        foundDevice = device
        foundAdv = advData
        foundEvent.set()

    logger.info(f"waiting for scale {bleAddr} to advertise "
                + ("in sync-ready state " if syncReadyOnly else "")
                + "(hold its bluetooth button until 'P' blinks, or step on it)...")
    scanner = bleak.BleakScanner(onAdvertisement)
    await scanner.start()
    try:
        if syncReadyOnly:
            # daemon mode: scan forever - a timeout would leave blind gaps in
            # which the scale's short post-measurement burst can be missed
            await foundEvent.wait()
        else:
            await asyncio.wait_for(foundEvent.wait(), timeout=180)
    except asyncio.TimeoutError:
        raise OSError(f"Scale {bleAddr} not found within 180s. Hold its bluetooth button until 'P' "
                      "blinks (or step on the scale and wait for the measurement to finish), then run again.")
    finally:
        await scanner.stop()

    # advData.local_name comes fresh from the advertisement; device.name on
    # macOS is a cached value from an earlier connection and can be stale
    advName = foundAdv.local_name if foundAdv is not None else None
    logger.info(f"scale is advertising as '{advName or '<no name in advertisement>'}' "
                f"(rssi {foundAdv.rssi if foundAdv else '?'})")

    # the scale drops idle/unbonded links within a few seconds - on a first
    # (unbonded) run the first encrypted op must go out immediately, and even
    # when already bonded the scale can drop the link mid service-discovery if
    # it isn't kept awake. retry the connect a few times to ride that out.
    bleClient = None
    lastError = None
    for attempt in range(1, 6):
        try:
            # pair as part of connect (bleak >= 3): pairing is then driven by
            # bluetoothd with proper bonding + key distribution, before any GATT
            # operation can trigger the kernel's no-bond security elevation
            # successful connects complete in 2-3s; a hung attempt otherwise
            # burns the whole timeout, so keep it short and retry instead
            bleClient = bleak.BleakClient(foundDevice, timeout=10, pair=True)
        except TypeError:
            bleClient = bleak.BleakClient(foundDevice, timeout=10)
        try:
            await bleClient.connect()
            logger.info(f"connected (attempt {attempt})")
            break
        except Exception as e:
            lastError = e
            logger.warning(f"connect/service-discovery failed (attempt {attempt}/5): {e}. "
                           "The scale drops the link fast - keep its 'P' symbol blinking. Retrying...")
            try:
                await bleClient.disconnect()
            except Exception:
                pass
            await asyncio.sleep(1)
    else:
        raise OSError(f"Could not get a stable connection to the scale after 5 attempts "
                      f"(last error: {lastError}).\nHold the scale's bluetooth button so 'P' keeps "
                      "blinking for the whole time this script runs.")
    try:
        await bleClient.pair(protection_level=2)
        logger.info("BLE bonding done")
    except TypeError:
        await bleClient.pair()
        logger.info("BLE bonding done")
    except Exception as e:
        errorText = str(e).lower()
        if "authentication" in errorText or "rejected" in errorText:
            # the scale actively refused SMP pairing - continuing would leave the
            # link unencrypted and every control-point write would fail cryptically
            try:
                await bleClient.disconnect()
            except Exception:
                pass
            raise OSError(f"The scale refused BLE pairing ({e}). It was not in pairing mode at the "
                          f"moment of connection, or its pairing memory holds a stale entry.\n"
                          f"{OmronScaleReader.PAIRING_FAILED_HELP}") from e
        # already bonded (Linux, via bluetoothctl) or no explicit pair API (macOS);
        # either way the stored keys encrypt the link automatically
        logger.debug(f"explicit pair not needed/available ({e}); relying on existing bond")
    return bleClient


async def main():
    parser = argparse.ArgumentParser(description="read records from Omron BLE body composition scales")
    parser.add_argument("-u", "--user", type=int, default=None, choices=[0, 1, 2, 3, 4], help="user slot on the scale; default: the slot assigned by the scale during pairing (saved in state file)")
    parser.add_argument("-p", "--pair", action="store_true", help="register a user on the scale (scale must be in pairing mode with blinking P); the scale assigns the user slot")
    parser.add_argument("-m", "--mac", type=str, help="bluetooth mac address (win/linux) or device UUID (macOS); skips scan dialog")
    parser.add_argument("--all", action="store_true", help="read all stored records, not only new ones")
    parser.add_argument("--consent", type=lambda x: int(x, 0), default=DEFAULT_CONSENT_CODE, help="consent code (default 0x020E)")
    parser.add_argument("--full", action="store_true", help="output all body composition fields instead of only weight")
    parser.add_argument("--jsonOut", action="store_true", help="print records as one JSON line (prefix OMSCALE_RESULT_JSON) instead of writing csv")
    parser.add_argument("-t", "--timeSync", action="store_true", help="synchronize the scale's internal clock with system time (records get stale dates after a battery change)")
    parser.add_argument("--daemon", action="store_true", help="run forever: keep scanning and sync every time the scale appears (for the systemd service)")
    parser.add_argument("--loggerDebug", action="store_true", help="verbose logging")
    args = parser.parse_args()

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if args.loggerDebug else logging.INFO)
    if args.loggerDebug:
        # surface bleak's backend decisions (StartNotify etc.) but not the very
        # noisy D-Bus scanner signals
        bleakLogger = logging.getLogger("bleak")
        bleakLogger.addHandler(handler)
        bleakLogger.setLevel(logging.DEBUG)
        logging.getLogger("bleak.backends.bluezdbus.manager").setLevel(logging.INFO)

    if args.daemon:
        # stay resident: scan -> sync -> repeat, so the scanner is already
        # running the moment the scale advertises after a measurement
        logger.info("daemon mode: continuously waiting for the scale")
        while True:
            try:
                newRecords = await syncOnce(args)
                if newRecords:
                    _IDLE_TRIGGER["backoff"] = _IDLE_BACKOFF_MIN
                if _IDLE_TRIGGER["lastWasSyncReady"]:
                    _IDLE_TRIGGER["cooldownUntil"] = 0.0
                else:
                    # the scale keeps beaconing after a sync - always cool down
                    # after an idle-triggered attempt so we don't reconnect to
                    # a scale that has nothing new (battery + radio time)
                    _startIdleCooldown("idle-beacon sync done" if newRecords
                                       else "idle-beacon sync yielded no new records")
                await asyncio.sleep(1)
            except asyncio.TimeoutError:
                await asyncio.sleep(1)
            except Exception as e:
                if not _IDLE_TRIGGER["lastWasSyncReady"]:
                    _startIdleCooldown(f"idle-beacon sync failed ({e.__class__.__name__})")
                logger.info(f"sync attempt ended ({e.__class__.__name__}); retrying in 3s...")
                logger.debug(f"details: {e}")
                await asyncio.sleep(3)
    else:
        await syncOnce(args)


async def syncOnce(args):
    state = loadState()
    if args.mac:
        bleAddr = args.mac
    elif state.get("address"):
        bleAddr = state["address"]
        logger.info(f"using saved scale address {bleAddr} (delete {STATE_FILE.name} to rescan)")
    else:
        bleAddr = await selectBLEdevices()
    state["address"] = bleAddr
    saveState(state)

    bleClient = await connectToScale(bleAddr, syncReadyOnly=args.daemon)
    try:
        if bleClient.services.get_characteristic(USER_CONTROL_POINT_UUID) is None:
            state["address"] = None
            saveState(state)
            raise OSError(f"The device at {bleAddr} has no Omron user control point characteristic - "
                          "this is not the scale (wrong device selected). Cleared the saved address; "
                          "run again to rescan.")
        for service in bleClient.services:
            logger.debug(f"service {service.uuid}")
            for char in service.characteristics:
                logger.debug(f"  char {char.uuid} props={','.join(char.properties)}")
        reader = OmronScaleReader(bleClient)
        await reader.triggerBonding()
        await reader.enableNotifications()
        # time sync is opt-in: omviva doesn't send one and the scale syncs fine
        # without it, but the internal clock resets on battery change (records
        # then carry stale dates) - run with --timeSync occasionally to fix it
        if args.timeSync:
            await reader.syncTime()

        userIndex = args.user if args.user is not None else int(state.get("userSlot", 1))

        if args.pair:
            assignedIndex = await reader.registerUser(args.consent)
            if assignedIndex is not None and assignedIndex != 0xFF:
                userIndex = assignedIndex
                logger.info(f"scale assigned user slot {userIndex}, saving as default for future syncs")
            state["userSlot"] = userIndex
            saveState(state)

        await reader.sendConsent(userIndex, args.consent)

        lastSequence = 0 if args.all else int(state["lastSequence"].get(str(userIndex), 0))
        records = await reader.readRecords(lastSequence + 1)
        await reader.disableNotifications()

        logger.info(f"received {len(records)} record(s)")
        for record in records:
            logger.info(f"  {record.get('datetime')} seq={record.get('sequence')} "
                        f"weight={record.get('weight')}{record.get('weightUnit', '')} "
                        f"bodyFat={record.get('bodyFatPercent')}%")

        sequences = [r["sequence"] for r in records if r.get("sequence") is not None]
        if sequences:
            state["lastSequence"][str(userIndex)] = max(max(sequences), lastSequence)
        saveState(state)

        fields = CSV_FIELDS if args.full else WEIGHT_ONLY_FIELDS
        if not args.full:
            records = [{field: r.get(field) for field in fields} for r in records]
        if args.jsonOut:
            print("OMSCALE_RESULT_JSON " + json.dumps(records), flush=True)
        else:
            mergeIntoCsv(records, userIndex, fields)
        if records:
            # always publish the single most recent measurement for easy
            # downstream consumption (display, uploader, ...)
            latest = max(records, key=lambda r: str(r.get("datetime")))
            latestPath = pathlib.Path(__file__).with_name(f"scale_user{userIndex}_latest.json")
            latestPath.write_text(json.dumps({k: str(v) for k, v in latest.items() if v is not None}, indent=4))
            logger.info(f"latest measurement -> {latestPath.name}: "
                        f"{latest.get('weight')}{latest.get('weightUnit', '')} at {latest.get('datetime')}")
        return len(records)
    finally:
        logger.info("disconnect")
        if bleClient.is_connected:
            try:
                await bleClient.disconnect()
            except Exception as e:
                logger.debug(f"disconnect raised (ignored): {e}")


if __name__ == "__main__":
    asyncio.run(main())
