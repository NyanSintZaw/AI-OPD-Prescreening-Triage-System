"""SQLite storage for the mock HIS.

Deliberately NOT the triage system's Postgres: the whole point of this
service is that hospital data lives in a separate store owned by the
hospital, reachable only through the API.

The hospital's masked sample collapses many real patients into a few
``hnx`` prefixes, so there is no patients table — demographics
(birthdate, HN) live on the visit row, which is also all the prescreen
integration needs.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    visit_id                    TEXT PRIMARY KEY,
    hn                          TEXT,
    appointment                 INTEGER NOT NULL DEFAULT 0,
    birthdate                   TEXT,
    weight                      REAL,
    height                      REAL,
    bmi                         REAL,
    systolic                    INTEGER,
    diastolic                   INTEGER,
    temperature                 REAL,
    pulse                       INTEGER,
    nurse_chief_complaint       TEXT,
    nurse_patient_illness       TEXT,
    first_location_id           TEXT,
    first_location_name         TEXT,
    first_location_department   TEXT,
    second_location_id          TEXT,
    second_location_name        TEXT,
    second_location_department  TEXT,
    modify_time                 TEXT
);

CREATE TABLE IF NOT EXISTS prescreen_results (
    visit_id               TEXT PRIMARY KEY REFERENCES visits(visit_id),
    session_ref            TEXT,
    slip_code              TEXT,
    recommended_department TEXT,
    complaint              TEXT,
    vitals                 TEXT,
    reasons                TEXT,
    status                 TEXT NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'confirmed', 'rerouted')),
    confirmed_department   TEXT,
    confirmed_by           TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at             TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_PRESSURE_RE = re.compile(r"^\s*(\d{2,3})\s*/\s*(\d{2,3})\s*$")


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value and value.strip() else None
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value and value.strip() else None
    except ValueError:
        return None


def parse_pressure(value: str | None) -> tuple[int | None, int | None]:
    """Split the HIS "140/74" blood-pressure string into systolic/diastolic."""
    if not value:
        return None, None
    match = _PRESSURE_RE.match(value)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def seed_from_csv(conn: sqlite3.Connection, csv_path: str | Path) -> int:
    """Load hospital prescreen rows (the 7-day export format) into visits."""
    inserted = 0
    with open(csv_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            visit_id = (row.get("visit_id") or "").strip()
            if not visit_id:
                continue
            systolic, diastolic = parse_pressure(row.get("pressure"))
            conn.execute(
                """
                INSERT OR REPLACE INTO visits (
                    visit_id, hn, appointment, birthdate,
                    weight, height, bmi, systolic, diastolic, temperature, pulse,
                    nurse_chief_complaint, nurse_patient_illness,
                    first_location_id, first_location_name, first_location_department,
                    second_location_id, second_location_name, second_location_department,
                    modify_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    visit_id,
                    (row.get("hnx") or "").strip() or None,
                    1 if (row.get("appointment") or "").strip() == "1" else 0,
                    (row.get("birthdate") or "").strip() or None,
                    _float(row.get("weight")),
                    _float(row.get("height")),
                    _float(row.get("bmi")),
                    systolic,
                    diastolic,
                    _float(row.get("temperature")),
                    _int(row.get("pulse")),
                    (row.get("nurse_chief_complaint") or "").strip() or None,
                    (row.get("nurse_patient_illness") or "").strip() or None,
                    (row.get("first_location_id") or "").strip() or None,
                    (row.get("first_location_name") or "").strip() or None,
                    (row.get("first_location_department") or "").strip() or None,
                    (row.get("second_location_id") or "").strip() or None,
                    (row.get("second_location_name") or "").strip() or None,
                    (row.get("second_location_department") or "").strip() or None,
                    (row.get("modify_time") or "").strip() or None,
                ),
            )
            inserted += 1
    conn.commit()
    return inserted
