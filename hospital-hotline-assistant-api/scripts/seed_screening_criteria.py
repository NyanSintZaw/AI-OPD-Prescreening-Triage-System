"""Seed (or refresh) screening criteria version 1 from the bundled JSON.

Run with: ``uv run python scripts/seed_screening_criteria.py``.

Idempotent: validates ``app/data/screening_criteria_v1.json`` against the
schema, then inserts it as version 1 with status ``active`` if no version 1
row exists yet. If version 1 exists, its JSON is refreshed in place only when
it is still the active version and differs from the file (hand-edits during
development); otherwise nothing changes.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

import asyncpg

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.screening.rules.criteria_models import parse_criteria  # noqa: E402

SEED_PATH = pathlib.Path(__file__).resolve().parents[1] / "app" / "data" / "screening_criteria_v1.json"
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/hospital_hotline"
)


async def main() -> None:
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    parse_criteria(payload)  # raises on invalid criteria
    print(f"Validated {SEED_PATH.name}")

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            "SELECT id, status, criteria FROM screening_criteria_versions WHERE version_no = 1"
        )
        criteria_json = json.dumps(payload, ensure_ascii=False)
        if row is None:
            await conn.execute(
                """
                INSERT INTO screening_criteria_versions
                    (version_no, status, criteria, change_summary, uploaded_by, activated_at)
                VALUES (1, 'active', $1::jsonb, $2, 'system-seed', NOW())
                """,
                criteria_json,
                "Initial hand-encoded criteria from the MFU patient triage manual "
                "(คู่มือเกณฑ์การคัดกรองผู้ป่วย)",
            )
            print("Inserted screening criteria version 1 (active)")
        elif row["status"] == "active" and json.loads(row["criteria"]) != payload:
            await conn.execute(
                "UPDATE screening_criteria_versions SET criteria = $1::jsonb WHERE id = $2",
                criteria_json,
                row["id"],
            )
            print("Refreshed active version 1 criteria from file")
        else:
            print(f"Version 1 already present (status={row['status']}); no change")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
