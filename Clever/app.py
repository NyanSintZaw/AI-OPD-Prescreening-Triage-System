import asyncio
from bleak import BleakClient, BleakScanner

STANDARD_TEMP_CHARACTERISTIC = (
    "00002a1c-0000-1000-8000-00805f9b34fb"
)

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

    return mantissa * (10 ** exponent)


def parse_temperature_measurement(data: bytearray) -> None:
    print("Raw packet:", data.hex())

    if len(data) < 5:
        print("Packet too short")
        return

    flags = data[0]
    fahrenheit = bool(flags & 0x01)
    value = decode_ieee11073_float(bytes(data[1:5]))
    unit = "°F" if fahrenheit else "°C"

    print(f"Temperature: {value:.2f}{unit}")


async def main():
    print("Scanning... Take a temperature measurement now.")

    devices = await BleakScanner.discover(timeout=15.0)

    for index, device in enumerate(devices):
        print(index, device.name, device.address)

    # Replace this after identifying the thermometer.
    address = input("Enter thermometer address: ").strip()

    async with BleakClient(address) as client:
        print("Connected:", client.is_connected)

        found_standard_characteristic = False

        for service in client.services:
            print(f"\nService: {service.uuid}")

            for characteristic in service.characteristics:
                print(
                    "  Characteristic:",
                    characteristic.uuid,
                    characteristic.properties,
                )

                if characteristic.uuid.lower() == STANDARD_TEMP_CHARACTERISTIC:
                    found_standard_characteristic = True

        if found_standard_characteristic:
            await client.start_notify(
                STANDARD_TEMP_CHARACTERISTIC,
                lambda _, data: parse_temperature_measurement(data),
            )

            print("Take another measurement.")
            await asyncio.sleep(30)

            await client.stop_notify(STANDARD_TEMP_CHARACTERISTIC)
        else:
            print(
                "\nThe standard thermometer characteristic was not found. "
                "The device probably uses a proprietary TaiDoc characteristic."
            )


asyncio.run(main())