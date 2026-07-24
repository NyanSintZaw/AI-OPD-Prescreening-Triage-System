"""SQLite storage for the mock HIS.

Deliberately NOT the triage system's Postgres: the whole point of this
service is that hospital data lives in a separate store owned by the
hospital, reachable only through the API.

The ``visits`` table mirrors the real MFU ``Prescreen`` export
column-for-column, so the hospital IT team sees literally their own
screening table. The ``patients`` table is the HN (hospital number)
master record: one row per patient, holding demographics plus the
patient-history fields our booth collects on a first visit
(smoking/alcohol, allergies, chronic conditions, surgeries, family
history) and the most recent weight/height measurement — a visit's
``hnx`` column links it to its patient.

Demo model — a visit starts in its *post-registration, pre-screening*
state: only ``visit_id``/``hnx``/``birthdate``/``appointment`` are filled;
every screening field is NULL until our system writes it back. A patient
with ``history_recorded_at`` NULL is a *first-time* patient: the booth
collects their history and writes it back through the API.
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
    patient_name                TEXT,
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
    follow_up                   TEXT,
    first_location_id           TEXT,
    first_location_name         TEXT,
    first_location_department   TEXT,
    second_location_id          TEXT,
    second_location_name        TEXT,
    second_location_department  TEXT
);

CREATE TABLE IF NOT EXISTS patients (
    hn                   TEXT PRIMARY KEY,
    patient_name         TEXT,
    birthdate            TEXT,
    -- Patient history collected at the AI booth on a first visit.
    smoking_alcohol      TEXT,
    allergies            TEXT,
    chronic_conditions   TEXT,
    past_surgeries       TEXT,
    family_history       TEXT,
    history_recorded_at  TEXT,
    -- Most recent booth measurement, so weight/height can be skipped
    -- on a return visit within the recency window.
    last_weight          REAL,
    last_height          REAL,
    vitals_measured_at   TEXT
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
PRE_REGISTRATION_COLUMNS = (
    "visit_id", "hnx", "patient_name", "birthdate", "appointment"
)

_PRESSURE_RE = re.compile(r"^\s*(\d{2,3})\s*/\s*(\d{2,3})\s*$")


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # CREATE IF NOT EXISTS won't extend a pre-existing DB file: patch in
    # columns added after the first release.
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(visits)")}
    for column in ("patient_name", "follow_up"):
        if column not in existing:
            conn.execute(f"ALTER TABLE visits ADD COLUMN {column} TEXT")
    conn.commit()
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
            patient_name = _str(row.get("patient_name"))
            appointment = 1 if _str(row.get("appointment")) == "1" else 0
            birthdate = _str(row.get("birthdate"))

            if pre_registration_only:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO visits
                        (visit_id, hnx, patient_name, appointment, birthdate)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (visit_id, hnx, patient_name, appointment, birthdate),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO visits (
                        visit_id, hnx, patient_name, appointment, measure_spid, measure_name,
                        measure_department, modify_time, weight, height, birthdate,
                        bmi, waist_width, pressure, temperature, pulse,
                        nurse_chief_complaint, nurse_patient_illness, follow_up,
                        first_location_id, first_location_name, first_location_department,
                        second_location_id, second_location_name, second_location_department
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        visit_id, hnx, patient_name, appointment,
                        _str(row.get("measure_spid")), _str(row.get("measure_name")),
                        _str(row.get("measure_department")), _str(row.get("modify_time")),
                        _float(row.get("weight")), _float(row.get("height")), birthdate,
                        _float(row.get("bmi")), _float(row.get("waist_width")),
                        _str(row.get("pressure")), _float(row.get("temperature")),
                        _int(row.get("pulse")),
                        _str(row.get("nurse_chief_complaint")),
                        _str(row.get("nurse_patient_illness")),
                        _str(row.get("follow_up")),
                        _str(row.get("first_location_id")), _str(row.get("first_location_name")),
                        _str(row.get("first_location_department")),
                        _str(row.get("second_location_id")), _str(row.get("second_location_name")),
                        _str(row.get("second_location_department")),
                    ),
                )
            inserted += 1
    conn.commit()
    return inserted


def seed_patients_from_csv(conn: sqlite3.Connection, csv_path: str | Path) -> int:
    """Load HN master records into ``patients`` from a CSV of the shape
    documented in ``sample_patients.csv``.

    A blank ``history_recorded_at`` means a first-time patient (no booth
    history collected yet); a filled one means a returning patient whose
    prior history/last-known vitals the booth can read back.
    """
    inserted = 0
    with open(csv_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            hn = _str(row.get("hn"))
            if not hn:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO patients (
                    hn, patient_name, birthdate, smoking_alcohol, allergies,
                    chronic_conditions, past_surgeries, family_history,
                    history_recorded_at, last_weight, last_height, vitals_measured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hn,
                    _str(row.get("patient_name")),
                    _str(row.get("birthdate")),
                    _str(row.get("smoking_alcohol")),
                    _str(row.get("allergies")),
                    _str(row.get("chronic_conditions")),
                    _str(row.get("past_surgeries")),
                    _str(row.get("family_history")),
                    _str(row.get("history_recorded_at")),
                    _float(row.get("last_weight")),
                    _float(row.get("last_height")),
                    _str(row.get("vitals_measured_at")),
                ),
            )
            inserted += 1
    conn.commit()
    return inserted


def backfill_patients_from_visits(conn: sqlite3.Connection) -> int:
    """Ensure every visit's ``hnx`` has at least a bare patient record.

    Mirrors how a visit's own demographics are pre-filled at registration:
    a patient can be known to the hospital (name/birthdate) with no booth
    history yet — that's exactly the first-time-patient case. Never
    overwrites an existing patient row.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT v.hnx AS hn, v.patient_name, v.birthdate
        FROM visits v
        LEFT JOIN patients p ON p.hn = v.hnx
        WHERE v.hnx IS NOT NULL AND p.hn IS NULL
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT OR IGNORE INTO patients (hn, patient_name, birthdate) VALUES (?, ?, ?)",
            (row["hn"], row["patient_name"], row["birthdate"]),
        )
    conn.commit()
    return len(rows)
