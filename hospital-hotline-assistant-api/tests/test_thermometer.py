"""Packet parsing for the BLE Health Thermometer service (TAIDOC TD1242)."""

from app.services.thermometer import parse_temperature_packet


def test_parse_real_td1242_packet():
    # Captured from the device: flags 0x06 (°C, timestamp+type present),
    # IEEE-11073 FLOAT mantissa 362 exponent -1 -> 36.2 °C.
    data = bytes.fromhex("066a0100ffdb070a1b08110001")
    assert parse_temperature_packet(data) == 36.2


def test_parse_fahrenheit_converts_to_celsius():
    # flags 0x01 (Fahrenheit), 98.6 °F (mantissa 986, exponent -1) -> 37.0 °C
    data = bytes([0x01]) + (986).to_bytes(3, "little") + bytes([0xFF])
    assert parse_temperature_packet(data) == 37.0


def test_short_packet_returns_none():
    assert parse_temperature_packet(b"\x06\x6a") is None


def test_implausible_value_returns_none():
    # Mantissa 0 -> 0.0 "measurement" is a malformed/reserved packet.
    data = bytes([0x06, 0x00, 0x00, 0x00, 0x00])
    assert parse_temperature_packet(data) is None
