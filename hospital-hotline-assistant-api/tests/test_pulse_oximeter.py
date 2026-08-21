"""Packet decoding, stability acceptance + scan classification for the
Rossmax SB210 oximeter."""

from app.services.pulse_oximeter import (
    SPO2_SERVICE_PREFIX,
    StabilityTracker,
    decode_packet,
    looks_like_oximeter,
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


def feed(tracker: StabilityTracker, readings, start=0.0, hz=1.0):
    """Feed (spo2, pulse) pairs at a fixed rate; returns the last timestamp."""
    t = start
    for spo2, pulse in readings:
        tracker.add(t, spo2, pulse)
        t += 1.0 / hz
    return t - 1.0 / hz


def test_steady_stream_accepted_after_full_window():
    tracker = StabilityTracker()
    last = feed(tracker, [(97, 72)] * 12)  # 0..11 s, one per second
    assert tracker.evaluate(last) == (97, 72)


def test_settling_overshoot_is_never_reported():
    # The clinical rule: first seconds after insertion overshoot — a fixed
    # timestamp would report them; stability detection must not.
    tracker = StabilityTracker()
    overshoot = [(85, 120), (88, 110), (92, 96)]
    last = feed(tracker, overshoot + [(97, 72)] * 6)
    # 8 s in: not yet a full window, and the overshoot is still inside it.
    assert tracker.evaluate(last) is None
    # Keep streaming steady values until the overshoot ages out.
    last = feed(tracker, [(97, 73)] * 8, start=last + 1.0)
    assert tracker.evaluate(last) == (97, 73)


def test_stream_must_span_the_window_before_acceptance():
    # Even perfectly steady values are not accepted before one full window
    # has elapsed since insertion (the stabilization period).
    tracker = StabilityTracker()
    last = feed(tracker, [(98, 70)] * 6)  # only 5 s of data
    assert tracker.evaluate(last) is None


def test_pulse_swing_blocks_acceptance():
    # SpO2 steady but the pulse still moving (>4 bpm spread) → keep waiting.
    tracker = StabilityTracker()
    readings = [(97, 70 + (i % 2) * 8) for i in range(12)]
    last = feed(tracker, readings)
    assert tracker.evaluate(last) is None


def test_sparse_stream_is_not_stable():
    # A handful of agreeing packets spread thin (poor contact, dropouts)
    # covers the window but is not a stable stream.
    tracker = StabilityTracker()
    last = feed(tracker, [(97, 72)] * 6, hz=0.4)  # one packet per 2.5 s
    assert tracker.evaluate(last) is None


def test_signal_loss_restarts_the_stabilization_clock():
    # A steady stretch, then the finger comes out for >3 s: the old samples
    # belong to a different placement and must not fast-track acceptance.
    tracker = StabilityTracker()
    last = feed(tracker, [(97, 72)] * 12)
    assert tracker.evaluate(last) == (97, 72)
    # Gap (finger out), then re-insertion with new values.
    resumed = feed(tracker, [(94, 80)] * 6, start=last + 6.0)
    assert tracker.evaluate(resumed) is None  # window restarted
    assert tracker.saw_finger is True  # deadline → "unstable", not "timeout"
    resumed = feed(tracker, [(94, 80)] * 6, start=resumed + 1.0)
    assert tracker.evaluate(resumed) == (94, 80)


def test_stale_tail_is_not_stable():
    # Signal lost and nothing since: evaluate() must not accept the old data.
    tracker = StabilityTracker()
    last = feed(tracker, [(97, 72)] * 12)
    assert tracker.evaluate(last + 5.0) is None


def test_median_of_the_stable_window():
    tracker = StabilityTracker()
    readings = [(97, 72), (98, 73), (97, 72), (98, 74), (97, 73), (97, 72),
                (98, 73), (97, 73), (97, 72), (98, 73), (97, 73), (97, 72)]
    last = feed(tracker, readings)
    assert tracker.evaluate(last) == (97, 73)


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
