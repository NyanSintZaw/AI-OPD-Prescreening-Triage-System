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


# ── router: a settled reading reaches the session the engine reads ───────────


class _Conn:
    """asyncpg stand-in: one session row whose metadata we can inspect."""

    def __init__(self, metadata):
        self.metadata = dict(metadata)
        self.inserted = []

    async def fetchrow(self, sql, *args):
        if "INSERT INTO spo2_readings" in sql:
            from uuid import uuid4
            self.inserted.append(args)
            return {"id": uuid4()}
        return {"metadata": dict(self.metadata)}

    async def execute(self, sql, *args):
        self.metadata = dict(args[1])


class _Spo2Service:
    async def fetch_reading(self, timeout_seconds=None):
        from datetime import datetime, timezone
        from app.services.pulse_oximeter import Spo2Reading
        return Spo2Reading(spo2=91, pulse_bpm=104, measured_at=datetime.now(timezone.utc))


async def test_fetch_merges_spo2_and_pulse_into_session_vitals_with_provenance():
    """The criteria's SpO2 rules read ``metadata.vitals.spo2`` via
    turn_context; the SBAR/nurse view read ``sources``. Both must land."""
    from types import SimpleNamespace
    from uuid import uuid4

    from app.routers.pulse_oximeter import fetch_spo2
    from app.schemas import Spo2FetchRequest

    conn = _Conn({"vitals": {"systolic": 120, "diastolic": 80, "sources": {"systolic": "device"}}})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(spo2_service=_Spo2Service())))
    out = await fetch_spo2(request, Spo2FetchRequest(session_id=uuid4()), conn)

    assert out.status == "ok" and out.spo2 == 91 and out.pulse_bpm == 104
    vitals = conn.metadata["vitals"]
    assert vitals["spo2"] == 91 and vitals["pulse_bpm"] == 104
    assert vitals["sources"]["spo2"] == "device"
    assert vitals["sources"]["pulse_bpm"] == "device"
    assert vitals["sources"]["systolic"] == "device"   # earlier provenance kept
    assert vitals["systolic"] == 120                     # earlier vitals kept
    assert conn.inserted, "durable spo2_readings row written"
