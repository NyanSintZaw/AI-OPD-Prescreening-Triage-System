"""Unit tests for the omscale weight-scale service (file mode + parsers)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

import pytest

from app.config import settings
from app.services.weight_scale import (
    WeightScaleFetchError,
    WeightScaleService,
    _default_omscale_dir,
    parse_history_csv,
    parse_latest_file,
    parse_result_json,
)


def test_default_dir_prefers_hbf222t_when_present():
    resolved = _default_omscale_dir()
    if (resolved.parent / "HBF-222T").is_dir():
        assert resolved.name == "HBF-222T"
    else:
        assert resolved.name == "omscale"


def test_parse_latest_file_stringified_values():
    # The daemon stringifies every field when publishing the latest file.
    text = json.dumps(
        {
            "datetime": "2026-07-22 16:21:11",
            "sequence": "13",
            "weight": "67.4",
            "weightUnit": "kg",
        }
    )
    reading = parse_latest_file(text)
    assert reading is not None
    assert reading.weight_kg == 67.4
    assert reading.sequence == 13
    assert reading.measured_at == datetime(2026, 7, 22, 16, 21, 11)


def test_parse_latest_file_converts_pounds():
    reading = parse_latest_file(
        json.dumps(
            {"datetime": "2026-07-22 08:00:00", "weight": "150.0", "weightUnit": "lb"}
        )
    )
    assert reading is not None
    assert reading.weight_kg == pytest.approx(68.0, abs=0.1)


def test_parse_latest_file_rejects_garbage():
    assert parse_latest_file("not json") is None
    assert parse_latest_file(json.dumps({"weight": "abc"})) is None
    assert parse_latest_file(json.dumps({"weight": "0", "datetime": "2026-01-01 00:00:00"})) is None


def test_parse_result_json_picks_newest_record():
    records = [
        {"datetime": "2026-07-22 10:00:00", "sequence": 11, "weight": 66.9, "weightUnit": "kg"},
        {"datetime": "2026-07-22 16:21:11", "sequence": 13, "weight": 67.4, "weightUnit": "kg"},
        {"datetime": "2026-07-22 12:00:00", "sequence": 12, "weight": 67.1, "weightUnit": "kg"},
    ]
    output = "some log line\nOMSCALE_RESULT_JSON " + json.dumps(records) + "\ndisconnect"
    reading = parse_result_json(output)
    assert reading is not None
    assert reading.sequence == 13
    assert reading.weight_kg == 67.4


def test_parse_result_json_empty_records():
    assert parse_result_json("OMSCALE_RESULT_JSON []") is None
    assert parse_result_json("no marker here") is None


def test_parse_latest_file_partial_record():
    # Observed in production: the daemon can leave the latest-json partial
    # (sequence + unit only, no weight) — that is not a reading.
    assert parse_latest_file(json.dumps({"sequence": "18", "weightUnit": "kg"})) is None


def test_parse_latest_file_missing_datetime_still_counts():
    # A weight without a timestamp is still a valid record; the sequence
    # carries the novelty signal.
    reading = parse_latest_file(
        json.dumps({"sequence": "18", "weight": "67.7", "weightUnit": "kg"})
    )
    assert reading is not None
    assert reading.weight_kg == 67.7
    assert reading.sequence == 18
    assert reading.measured_at is None


def test_parse_history_csv_skips_partial_rows():
    # Real scale_user1.csv shape, including the observed empty rows.
    text = (
        "datetime,sequence,weight,weightUnit\n"
        "2026-07-28 08:55:57,16,69.3,kg\n"
        "2026-07-28 09:37:16,19,67.7,kg\n"
        ",18,,kg\n"
        ",19,,kg\n"
    )
    readings = parse_history_csv(text)
    assert [r.sequence for r in readings] == [16, 19]
    assert readings[1].weight_kg == 67.7


@pytest.fixture
def file_mode_service(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "scale_read_mode", "file")
    monkeypatch.setattr(settings, "scale_omscale_dir", str(tmp_path))
    monkeypatch.setattr(settings, "scale_user_slot", 1)
    return WeightScaleService()


def _write_latest(tmp_path, weight: str, seq: str, when: str) -> None:
    (tmp_path / "scale_user1_latest.json").write_text(
        json.dumps(
            {"datetime": when, "sequence": seq, "weight": weight, "weightUnit": "kg"}
        )
    )


async def test_file_fetch_latest(file_mode_service, tmp_path):
    _write_latest(tmp_path, "67.4", "13", "2026-07-22 16:21:11")
    reading = await file_mode_service.fetch_latest()
    assert reading.weight_kg == 67.4


async def test_file_fetch_no_records_when_missing(file_mode_service):
    with pytest.raises(WeightScaleFetchError) as exc:
        await file_mode_service.fetch_latest()
    assert exc.value.code == "no_records"


async def test_file_fetch_falls_back_to_csv_history(file_mode_service, tmp_path):
    # Partial latest-json (no weight) + complete CSV history: the CSV row
    # with the highest sequence and a valid weight wins.
    (tmp_path / "scale_user1_latest.json").write_text(
        json.dumps({"sequence": "19", "weightUnit": "kg"})
    )
    (tmp_path / "scale_user1.csv").write_text(
        "datetime,sequence,weight,weightUnit\n"
        "2026-07-28 09:08:27,17,67.8,kg\n"
        "2026-07-28 09:37:16,19,67.7,kg\n"
        ",18,,kg\n"
    )
    reading = await file_mode_service.fetch_latest()
    assert reading.sequence == 19
    assert reading.weight_kg == 67.7


async def test_file_watch_resolves_on_new_measurement(file_mode_service, tmp_path):
    _write_latest(tmp_path, "67.4", "13", "2026-07-22 16:21:11")

    async def new_measurement_soon():
        await asyncio.sleep(1.2)
        _write_latest(tmp_path, "68.1", "14", "2026-07-22 16:25:00")

    writer = asyncio.ensure_future(new_measurement_soon())
    try:
        reading = await file_mode_service.watch_and_fetch(timeout_seconds=6)
    finally:
        await writer
    assert reading.weight_kg == 68.1
    assert reading.sequence == 14


async def test_file_watch_not_seen_when_unchanged(file_mode_service, tmp_path):
    _write_latest(tmp_path, "67.4", "13", "2026-07-22 16:21:11")
    with pytest.raises(WeightScaleFetchError) as exc:
        await file_mode_service.watch_and_fetch(timeout_seconds=1.5)
    assert exc.value.code == "not_seen"


async def test_file_watch_rewrite_same_sequence_is_not_new(
    file_mode_service, tmp_path
):
    # The daemon may rewrite the latest file with the SAME record (mtime
    # changes, content may too) — sequence-based detection must not fire.
    _write_latest(tmp_path, "67.4", "13", "2026-07-22 16:21:11")

    async def rewrite_soon():
        await asyncio.sleep(0.5)
        _write_latest(tmp_path, "67.40", "13", "2026-07-22 16:21:11")

    writer = asyncio.ensure_future(rewrite_soon())
    try:
        with pytest.raises(WeightScaleFetchError) as exc:
            await file_mode_service.watch_and_fetch(timeout_seconds=2)
    finally:
        await writer
    assert exc.value.code == "not_seen"


async def test_file_watch_since_sequence_returns_missed_reading(
    file_mode_service, tmp_path
):
    # A measurement that synced BETWEEN two long-poll calls: the client pins
    # its baseline with since_sequence, so the next call returns the reading
    # immediately instead of re-baselining it away.
    _write_latest(tmp_path, "68.1", "14", "2026-07-22 16:25:00")
    reading = await file_mode_service.watch_and_fetch(
        timeout_seconds=5, since_sequence=13
    )
    assert reading.sequence == 14
    assert reading.weight_kg == 68.1
