"""Packet parsing + scan classification for BLE Health Thermometers."""

from app.services.thermometer import (
    HEALTH_THERMOMETER_SERVICE,
    looks_like_thermometer,
    parse_temperature_packet,
)


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


def test_advertised_service_uuid_identifies_any_brand():
    # An unbranded/new device advertising the Health Thermometer Service
    # must be flagged even when its name matches no known brand.
    assert looks_like_thermometer("XCTZ-991", [HEALTH_THERMOMETER_SERVICE])
    assert looks_like_thermometer(None, [HEALTH_THERMOMETER_SERVICE.upper()])


def test_known_brand_names_flagged_without_service_uuids():
    for name in ("TAIDOC TD1242", "FORA IR42", "Clever Choice", "Beurer FT95"):
        assert looks_like_thermometer(name, None), name


def test_unrelated_device_not_flagged():
    assert not looks_like_thermometer("HEM-7156T", None)  # the BP cuff
    assert not looks_like_thermometer(None, ["0000180d-0000-1000-8000-00805f9b34fb"])
    assert not looks_like_thermometer(None, None)
