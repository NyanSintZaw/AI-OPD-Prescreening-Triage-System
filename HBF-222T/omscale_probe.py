"""
omscale_probe - test the Omron scale's proprietary (omblepy-style) transfer
service WITHOUT BLE bonding on macOS.

Steps (each reported):
  A. read the unlock characteristic
  B. subscribe unlock + all RX channels + mystery char
  C. try unlock with candidate keys (zeros / ffs / omblepy default)
  D. enter key programming mode, 3 attempts       (if no unlock worked)
  E. data readout + eeprom reads                  (if an unlock worked)
  F. read misc characteristics unencrypted

Usage: python omscale_probe.py
"""

import asyncio
import json
import logging
import pathlib

import bleak

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("omscale_probe")
logging.getLogger("bleak").setLevel(logging.WARNING)

UNLOCK_UUID = "b305b680-aee7-11e1-a730-0002a5d5c51b"
TX_UUID = "db5b55e0-aee7-11e1-965e-0002a5d5c51b"
RX_UUIDS = [
    "49123040-aee8-11e1-a74d-0002a5d5c51b",
    "4d0bf320-aee8-11e1-a0d9-0002a5d5c51b",
    "5128ce60-aee8-11e1-b84b-0002a5d5c51b",
    "560f1420-aee8-11e1-8184-0002a5d5c51b",
    "8858eb40-aee8-11e1-bb67-0002a5d5c51b",
]
MYSTERY_UUID = "547df234-6043-43d6-81a3-1dc46fa5245e"
MISC_READ_UUIDS = {
    "mystery_547df234": MYSTERY_UUID,
    "user_index_2a9a": "00002a9a-0000-1000-8000-00805f9b34fb",
    "scale_feature_2a9e": "00002a9e-0000-1000-8000-00805f9b34fb",
    "battery_2a19": "00002a19-0000-1000-8000-00805f9b34fb",
    "db_change_2a99": "00002a99-0000-1000-8000-00805f9b34fb",
}
CANDIDATE_KEYS = [
    ("zeros", bytearray(16)),
    ("ffs", bytearray(b"\xff" * 16)),
    ("omblepy_default", bytearray.fromhex("deadbeaf12341234deadbeaf12341234")),
]

STATE_FILE = pathlib.Path(__file__).with_name("omscale_state.json")


def withCrc(hexStr):
    packet = bytearray.fromhex(hexStr)
    xorCrc = 0
    for byte in packet:
        xorCrc ^= byte
    packet.append(xorCrc)
    return packet


def eepromReadCommand(address, size):
    packet = bytearray.fromhex("080100")
    packet += address.to_bytes(2, "big")
    packet += size.to_bytes(1, "big")
    packet += b"\x00"
    xorCrc = 0
    for byte in packet:
        xorCrc ^= byte
    packet.append(xorCrc)
    return packet


async def main():
    state = json.loads(STATE_FILE.read_text())
    bleAddr = state["address"]

    foundDevice = None
    foundEvent = asyncio.Event()

    def onAdvertisement(device, advData):
        nonlocal foundDevice
        if device.address.upper() == bleAddr.upper():
            foundDevice = device
            foundEvent.set()

    logger.info(f"waiting for scale {bleAddr} (pairing mode OR right after a measurement)...")
    scanner = bleak.BleakScanner(onAdvertisement)
    await scanner.start()
    try:
        await asyncio.wait_for(foundEvent.wait(), timeout=120)
    finally:
        await scanner.stop()

    client = bleak.BleakClient(foundDevice, timeout=15)
    await client.connect()
    logger.info("connected")

    results = {}
    responseHolder = {}
    responseEvent = asyncio.Event()

    def unlockCallback(char, data):
        responseHolder["data"] = bytes(data)
        responseEvent.set()

    rxPackets = []

    def makeRxCallback(label):
        def rxCallback(char, data):
            rxPackets.append((label, bytes(data)))
            logger.info(f"RX {label} < {bytes(data).hex()}")
        return rxCallback

    async def unlockWrite(payload, timeout=6):
        responseEvent.clear()
        responseHolder.pop("data", None)
        await client.write_gatt_char(UNLOCK_UUID, payload, response=True)
        try:
            await asyncio.wait_for(responseEvent.wait(), timeout)
            return responseHolder.get("data")
        except asyncio.TimeoutError:
            return None

    def drainRx():
        drained = [f"{label}:{pkt.hex()}" for label, pkt in rxPackets]
        rxPackets.clear()
        return drained

    try:
        # A: plain read of unlock char
        try:
            value = await asyncio.wait_for(client.read_gatt_char(UNLOCK_UUID), 25)
            results["A_read_unlock"] = f"OK: {bytes(value).hex()}"
        except Exception as e:
            results["A_read_unlock"] = f"FAILED: {e}"

        # B: subscribe unlock + RX channels + mystery char
        try:
            await client.start_notify(UNLOCK_UUID, unlockCallback)
            for idx, uuid in enumerate(RX_UUIDS):
                await client.start_notify(uuid, makeRxCallback(f"ch{idx}"))
            results["B_subscribe"] = "OK"
        except Exception as e:
            results["B_subscribe"] = f"FAILED: {e}"
            raise
        try:
            await client.start_notify(MYSTERY_UUID, makeRxCallback("mystery"))
        except Exception as e:
            results["B_mystery_subscribe"] = f"FAILED: {e}"

        # C: unlock with candidate keys
        unlockedWith = None
        for keyName, key in CANDIDATE_KEYS:
            response = await unlockWrite(b"\x01" + key)
            results[f"C_unlock_{keyName}"] = f"response: {response.hex() if response else 'none'}"
            if response is not None and response[:2] == bytes.fromhex("8100"):
                unlockedWith = keyName
                break

        # D: enter key programming mode (only if no key worked)
        if unlockedWith is None:
            for attempt in range(1, 4):
                response = await unlockWrite(b"\x02" + b"\x00" * 16)
                results["D_keyprog_mode"] = f"attempt {attempt}: response {response.hex() if response else 'none'}"
                if response is not None and response[:2] == bytes.fromhex("8200"):
                    response = await unlockWrite(b"\x00" + CANDIDATE_KEYS[2][1])
                    results["D_program_key"] = f"response: {response.hex() if response else 'none'}"
                    if response is not None and response[:2] == bytes.fromhex("8000"):
                        unlockedWith = "omblepy_default (just programmed)"
                    break
                await asyncio.sleep(1)

        # E: data readout if unlocked
        if unlockedWith is not None:
            results["E_unlocked_with"] = unlockedWith
            try:
                await client.write_gatt_char(TX_UUID, withCrc("08000000001000"), response=True)
                await asyncio.sleep(3)
                results["E_start_readout"] = f"rx: {drainRx() or 'none'}"
                for address in (0x0000, 0x0100):
                    await client.write_gatt_char(TX_UUID, eepromReadCommand(address, 0x10), response=True)
                    await asyncio.sleep(3)
                    results[f"E_eeprom_{address:04x}"] = f"rx: {drainRx() or 'none'}"
                await client.write_gatt_char(TX_UUID, withCrc("080f0000000000"), response=True)
                await asyncio.sleep(2)
                results["E_end_readout"] = f"rx: {drainRx() or 'none'}"
            except Exception as e:
                results["E_readout"] = f"FAILED: {e}"

        # F: misc unencrypted reads
        for name, uuid in MISC_READ_UUIDS.items():
            try:
                value = await asyncio.wait_for(client.read_gatt_char(uuid), 8)
                results[f"F_{name}"] = f"OK: {bytes(value).hex()}"
            except Exception as e:
                results[f"F_{name}"] = f"FAILED: {e}"
    finally:
        leftover = drainRx()
        print("\n========== PROBE RESULTS ==========")
        for step, outcome in results.items():
            print(f"  {step}: {outcome}")
        if leftover:
            print(f"  leftover_rx: {leftover}")
        print("===================================\n")
        if client.is_connected:
            try:
                await client.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
