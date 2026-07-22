"""Seed the mock HIS SQLite database from a CSV export.

Usage (from hospital-his-mock/):

    # from the real hospital export (kept out of git)
    HIS_MOCK_DATA_PATH=/path/to/Prescreen_7Day.csv uv run python scripts/seed_db.py

    # or the committed synthetic sample
    uv run python scripts/seed_db.py --sample

The database file is created fresh if missing; existing visits are
replaced by visit_id.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from his_mock.database import (
    backfill_patients_from_visits,
    connect,
    seed_from_csv,
    seed_patients_from_csv,
)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_CSV = PACKAGE_ROOT / "sample_visits.csv"
SAMPLE_PATIENTS_CSV = PACKAGE_ROOT / "sample_patients.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the mock HIS database")
    parser.add_argument(
        "--csv",
        default=os.environ.get("HIS_MOCK_DATA_PATH", ""),
        help="CSV export path (defaults to $HIS_MOCK_DATA_PATH)",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Seed from the committed synthetic sample instead of a real export",
    )
    parser.add_argument(
        "--patients-csv",
        default=os.environ.get("HIS_MOCK_PATIENTS_DATA_PATH", ""),
        help="Patients (HN) CSV path (defaults to $HIS_MOCK_PATIENTS_DATA_PATH)",
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("HIS_MOCK_DB_PATH", "his_mock.db"),
        help="SQLite database path (defaults to $HIS_MOCK_DB_PATH or his_mock.db)",
    )
    args = parser.parse_args()

    use_sample = args.sample or not args.csv
    csv_path = SAMPLE_CSV if use_sample else Path(args.csv)
    if not Path(csv_path).exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    conn = connect(args.db)
    # The synthetic sample seeds pre-registration state (screening fields
    # blank) for the before/after demo; a real export loads complete rows.
    count = seed_from_csv(conn, csv_path, pre_registration_only=use_sample)
    print(f"Seeded {count} visits from {csv_path} into {args.db}")

    use_sample_patients = args.sample or not args.patients_csv
    patients_csv_path = SAMPLE_PATIENTS_CSV if use_sample_patients else Path(args.patients_csv)
    if Path(patients_csv_path).exists():
        patient_count = seed_patients_from_csv(conn, patients_csv_path)
        print(f"Seeded {patient_count} patients from {patients_csv_path} into {args.db}")
    backfilled = backfill_patients_from_visits(conn)
    if backfilled:
        print(f"Backfilled {backfilled} bare patient record(s) from visits with no prior HN record")


if __name__ == "__main__":
    main()
