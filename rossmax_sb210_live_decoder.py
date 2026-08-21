#!/usr/bin/env python3
"""
Rossmax SB210 / RM_SPO2 live BLE decoder.

Observed packet format for characteristic:
    6e40f682-b5a3-f393-e0a9-e50e24dcca9e

16-byte packet:
    byte 0      = status/sequence byte (partially understood)
    byte 1      = SpO2 percentage
    byte 2      = pulse rate (bpm)
    bytes 3-14  = pleth waveform samples (12 samples)
    byte 15     = checksum: sum(bytes[0:15]) & 0xFF

The decoder only displays SpO2/HR when they are in physiologically
plausible ranges, while preserving all raw values for debugging.
"""

import argparse
import asyncio
from datetime import datetime, timezone

from bleak import BleakClient, BleakScanner

DEVICE_NAME = "RM_SPO2"
DEFAULT_DEVICE_ID = "CE98D97E-20E8-F63C-61A7-F96A82DF34C2"
DATA_CHAR = "6e40f682-b5a3-f393-e0a9-e50e24dcca9e"


def decode_packet(data: bytes):
    if len(data) != 16:
        return None

    checksum_expected = sum(data[:15]) & 0xFF
    checksum_received = data[15]
    checksum_ok = checksum_expected == checksum_received

    status = data[0]
    spo2 = data[1]
    pulse = data[2]
    pleth = list(data[3:15])

    # Before a finger/valid measurement, the SB210 sends zeros here.
    valid_measurement = (
        checksum_ok
        and 50 <= spo2 <= 100
        and 25 <= pulse <= 250
    )

    return {
        "status": status,
        "spo2": spo2,
        "pulse": pulse,
        "pleth": pleth,
        "checksum": checksum_received,
        "checksum_expected": checksum_expected,
        "checksum_ok": checksum_ok,
        "valid_measurement": valid_measurement,
    }


async def find_device(device_id: str | None):
    print(f"Scanning for {DEVICE_NAME}...")
    devices = await BleakScanner.discover(timeout=8.0, return_adv=True)

    for _, (device, adv) in devices.items():
        if device.name == DEVICE_NAME:
            print(f"Found {device.name} [{device.address}]")
            return device

        if device_id and device.address.lower() == device_id.lower():
            print(f"Found {device.name or 'device'} [{device.address}]")
            return device

    return None


async def main(args):
    device = await find_device(args.device)

    if device is None:
        print("RM_SPO2 not found.")
        print("Turn on the SB210 and run this script again.")
        return

    print(f"Connecting to {device.address}...")

    last_values = {"spo2": None, "pulse": None}

    def on_data(sender, data: bytearray):
        raw = bytes(data)
        decoded = decode_packet(raw)

        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        if decoded is None:
            print(f"{now} unexpected packet len={len(raw)} hex={raw.hex()}")
            return

        if not decoded["checksum_ok"]:
            print(
                f"{now} BAD CHECKSUM "
                f"got=0x{decoded['checksum']:02x} "
                f"expected=0x{decoded['checksum_expected']:02x} "
                f"hex={raw.hex()}"
            )
            return

        if decoded["valid_measurement"]:
            spo2 = decoded["spo2"]
            pulse = decoded["pulse"]

            changed = (
                spo2 != last_values["spo2"]
                or pulse != last_values["pulse"]
            )

            if changed or args.every_packet:
                print(
                    f"{now}  "
                    f"SpO2={spo2:3d}%  "
                    f"Pulse={pulse:3d} bpm  "
                    f"status=0x{decoded['status']:02x}"
                )

                if args.pleth:
                    print("   Pleth:", " ".join(f"{x:3d}" for x in decoded["pleth"]))

            last_values["spo2"] = spo2
            last_values["pulse"] = pulse

        elif args.raw_invalid:
            print(
                f"{now} waiting for valid reading "
                f"SpO2_raw={decoded['spo2']} "
                f"Pulse_raw={decoded['pulse']} "
                f"status=0x{decoded['status']:02x} "
                f"hex={raw.hex()}"
            )

    async with BleakClient(device) as client:
        print("Connected.")
        print(f"Subscribing to {DATA_CHAR}")
        await client.start_notify(DATA_CHAR, on_data)

        print()
        print("Insert finger into the SB210.")
        print("Press Ctrl+C to stop.")
        print()

        try:
            if args.seconds > 0:
                await asyncio.sleep(args.seconds)
            else:
                while True:
                    await asyncio.sleep(3600)
        finally:
            try:
                await client.stop_notify(DATA_CHAR)
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Decode Rossmax SB210 SpO2, pulse and pleth data over BLE."
    )
    parser.add_argument(
        "--device",
        default=DEFAULT_DEVICE_ID,
        help="BLE device address/UUID reported by Bleak on macOS",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=0,
        help="Capture duration. 0 means run until Ctrl+C.",
    )
    parser.add_argument(
        "--pleth",
        action="store_true",
        help="Print the 12 pleth waveform samples from each displayed packet.",
    )
    parser.add_argument(
        "--every-packet",
        action="store_true",
        help="Print every valid packet rather than only changed SpO2/pulse readings.",
    )
    parser.add_argument(
        "--raw-invalid",
        action="store_true",
        help="Show packets before a valid finger measurement is available.",
    )

    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        print("\nStopped.")