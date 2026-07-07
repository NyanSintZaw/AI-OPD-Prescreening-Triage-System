"""SQLite storage for the mock HIS.

Deliberately NOT the triage system's Postgres: the whole point of this
service is that hospital data lives in a separate store owned by the
hospital, reachable only through the API.

The ``visits`` table mirrors the real MFU ``Prescreen`` export
column-for-column, so the hospital IT team sees literally their own
screening table. Demographics (``hnx``, ``birthdate``) live on the visit
row (the masked sample collapses many patients into a few ``hnx``
prefixes, so there is no separate patients table).

Demo model — a visit starts in its *post-registration, pre-screening*
state: only ``visit_id``/``hnx``/``birthdate``/``appointment`` are filled;
every screening field is NULL until our system writes it back.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

# Column-for-column mirror of the hospital's Prescreen export. ``pressure``
# stays the raw "140/74" string exactly as the export carries it.
SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    visit_id                    TEXT PRIMARY KEY,
    hnx                         TEXT,
    appointment                 INTEGER NOT NULL DEFAULT 0,
    measure_spid                TEXT,
    measure_name                TEXT,
    measure_department          TEXT,
    modify_time                 TEXT,
    weight                      REAL,
    height                      REAL,
    birthdate                   TEXT,
    bmi                         REAL,
    waist_width                 REAL,
    pressure                    TEXT,
    temperature                 REAL,
    pulse                       INTEGER,
    nurse_chief_complaint       TEXT,
    nurse_patient_illness       TEXT,
    first_location_id           TEXT,
    first_location_name         TEXT,
    first_location_department   TEXT,
    second_location_id          TEXT,
    second_location_name        TEXT,
    second_location_department  TEXT
);

CREATE TABLE IF NOT EXISTS prescreen_results (
    visit_id               TEXT PRIMARY KEY REFERENCES visits(visit_id),
    session_ref            TEXT,
    slip_code              TEXT,
    recommended_department TEXT,
    complaint              TEXT,
    reason                 TEXT,
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

# Columns the hospital already knows at registration (we only READ these).
PRE_REGISTRATION_COLUMNS = ("visit_id", "hnx", "birthdate", "appointment")

_PRESSURE_RE = re.compile(r"^\s*(\d{2,3})\s*/\s*(\d{2,3})\s*$")


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _float(value) -> float | None:
    try:
        s = str(value).strip() if value is not None else ""
        return float(s) if s else None
    except ValueError:
        return None


def _int(value) -> int | None:
    try:
        s = str(value).strip() if value is not None else ""
        return int(float(s)) if s else None
    except ValueError:
        return None


def _str(value) -> str | None:
    s = str(value).strip() if value is not None else ""
    return s or None


def parse_pressure(value: str | None) -> tuple[int | None, int | None]:
    """Split a "140/74" blood-pressure string into systolic/diastolic."""
    if not value:
        return None, None
    match = _PRESSURE_RE.match(str(value))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def seed_from_csv(
    conn: sqlite3.Connection,
    csv_path: str | Path,
    *,
    pre_registration_only: bool = False,
) -> int:
    """Load hospital prescreen rows (the export format) into ``visits``.

    ``pre_registration_only`` keeps only the fields the hospital knows at
    registration (``visit_id``/``hnx``/``birthdate``/``appointment``) and
    leaves every screening field NULL — the "before" state our system then
    fills in. Otherwise every column present in the CSV is loaded (a
    completed export).
    """
    inserted = 0
    with open(csv_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            visit_id = _str(row.get("visit_id"))
            if not visit_id:
                continue
            hnx = _str(row.get("hnx")) or _str(row.get("hn"))
            appointment = 1 if _str(row.get("appointment")) == "1" else 0
            birthdate = _str(row.get("birthdate"))

            if pre_registration_only:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO visits (visit_id, hnx, appointment, birthdate)
                    VALUES (?, ?, ?, ?)
                    """,
                    (visit_id, hnx, appointment, birthdate),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO visits (
                        visit_id, hnx, appointment, measure_spid, measure_name,
                        measure_department, modify_time, weight, height, birthdate,
                        bmi, waist_width, pressure, temperature, pulse,
                        nurse_chief_complaint, nurse_patient_illness,
                        first_location_id, first_location_name, first_location_department,
                        second_location_id, second_location_name, second_location_department
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        visit_id, hnx, appointment,
                        _str(row.get("measure_spid")), _str(row.get("measure_name")),
                        _str(row.get("measure_department")), _str(row.get("modify_time")),
                        _float(row.get("weight")), _float(row.get("height")), birthdate,
                        _float(row.get("bmi")), _float(row.get("waist_width")),
                        _str(row.get("pressure")), _float(row.get("temperature")),
                        _int(row.get("pulse")),
                        _str(row.get("nurse_chief_complaint")),
                        _str(row.get("nurse_patient_illness")),
                        _str(row.get("first_location_id")), _str(row.get("first_location_name")),
                        _str(row.get("first_location_department")),
                        _str(row.get("second_location_id")), _str(row.get("second_location_name")),
                        _str(row.get("second_location_department")),
                    ),
                )
            inserted += 1
    conn.commit()
    return inserted
