"""Packet decoding + scan classification for the Rossmax SB210 oximeter."""

from app.services.pulse_oximeter import (
    SPO2_SERVICE_PREFIX,
    decode_packet,
    looks_like_oximeter,
    select_reading,
)


def packet(status=0x80, spo2=97, pulse=72, pleth=None, checksum=None) -> bytes:
    body = bytes([status, spo2, pulse]) + bytes(pleth or [10] * 12)
    if checksum is None:
        checksum = sum(body) & 0xFF
    return body + bytes([checksum])


def test_valid_packet_decodes():
    decoded = decode_packet(packet(spo2=97, pulse=72))
    assert decoded is not None
    assert decoded["checksum_ok"] is True
    assert decoded["valid_measurement"] is True
    assert decoded["spo2"] == 97
    assert decoded["pulse"] == 72
    assert len(decoded["pleth"]) == 12


def test_pre_finger_zero_packet_is_not_a_measurement():
    # Before a finger is inserted the SB210 streams zeros — checksum is fine
    # (0), but 0% SpO2 is not a reading and must never reach the session.
    decoded = decode_packet(bytes(16))
    assert decoded is not None
    assert decoded["checksum_ok"] is True
    assert decoded["valid_measurement"] is False


def test_bad_checksum_rejected():
    decoded = decode_packet(packet(checksum=0x00))
    assert decoded is not None
    assert decoded["checksum_ok"] is False
    assert decoded["valid_measurement"] is False


def test_wrong_length_returns_none():
    assert decode_packet(b"\x80\x61") is None
    assert decode_packet(packet() + b"\x00") is None


def test_out_of_range_values_are_not_measurements():
    assert decode_packet(packet(spo2=127))["valid_measurement"] is False
    assert decode_packet(packet(spo2=40))["valid_measurement"] is False
    assert decode_packet(packet(pulse=10))["valid_measurement"] is False


def test_select_reading_median_rejects_blips():
    # A single settling overshoot must not become the reported value.
    samples = [(85, 120)] + [(97, 72)] * 6
    assert select_reading(samples) == (97, 72)


def test_advertised_vendor_service_identifies_the_device():
    uuid = f"{SPO2_SERVICE_PREFIX}-b5a3-f393-e0a9-e50e24dcca9e"
    assert looks_like_oximeter("XCTZ-991", [uuid])
    assert looks_like_oximeter(None, [uuid.upper()])


def test_known_names_flagged_without_service_uuids():
    for name in ("RM_SPO2", "Rossmax SB210", "SB-210", "PulseOx"):
        assert looks_like_oximeter(name, None), name


def test_unrelated_devices_not_flagged():
    assert not looks_like_oximeter("HEM-7280T", None)          # the BP cuff
    assert not looks_like_oximeter("TAIDOC TD1242", None)      # thermometer
    assert not looks_like_oximeter(
        None, ["00001809-0000-1000-8000-00805f9b34fb"]         # thermometer svc
    )
    assert not looks_like_oximeter(None, None)
