"""Seed (or refresh) screening criteria from the bundled JSON file.

Run with: ``uv run python scripts/seed_screening_criteria.py``.

Idempotent: validates ``app/data/screening_criteria.json`` against the
schema, then inserts it as version 1, status ``active`` — the initial
version — if no version-1 row exists yet.

If the version-1 row already exists, its JSON is refreshed in place only
when it is still ``active`` and differs from the file (hand-edits during
development); otherwise nothing changes. Later versions come from the
admin review flow or ``scripts/deploy_criteria.py``.

``--reset-to-initial`` (DESTRUCTIVE, dev/UAT setup): collapses the whole
version history to a single row — version 1, active, the bundled file. All
other rows are DELETED; ``screening_sessions.criteria_version_id`` and
``ai_inference_audit.criteria_version_id`` referencing them are set NULL
(audit rows keep everything else; in-flight sessions lose their pinned
version and fall back to the active criteria). One transaction.
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

CRITERIA_PATH = (
    pathlib.Path(__file__).resolve().parents[1] / "app" / "data" / "screening_criteria.json"
)
CHANGE_SUMMARY = (
    "Initial criteria seed: MFU patient triage manual "
    "(คู่มือเกณฑ์การคัดกรองผู้ป่วย) with standards-cited breadth "
    "(MOPH ED Triage leading, ESI v5 referenced)"
)
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/hospital_hotline"
)


async def seed(conn: asyncpg.Connection) -> None:
    payload = json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))
    parse_criteria(payload)  # raises on invalid criteria
    print(f"Validated {CRITERIA_PATH.name}")

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
            CHANGE_SUMMARY,
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


async def reset_to_initial(conn: asyncpg.Connection) -> None:
    """DESTRUCTIVE: replace the entire version history with one row —
    version 1, active, the bundled file. Nulls the (nullable) FK references
    first so the deletes cannot fail."""
    payload = json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))
    parse_criteria(payload)  # raises on invalid criteria
    print(f"Validated {CRITERIA_PATH.name}")

    async with conn.transaction():
        sessions = await conn.execute(
            "UPDATE screening_sessions SET criteria_version_id = NULL "
            "WHERE criteria_version_id IS NOT NULL"
        )
        audit = await conn.execute(
            "UPDATE ai_inference_audit SET criteria_version_id = NULL "
            "WHERE criteria_version_id IS NOT NULL"
        )
        deleted = await conn.execute("DELETE FROM screening_criteria_versions")
        await conn.execute(
            """
            INSERT INTO screening_criteria_versions
                (version_no, status, criteria, change_summary, uploaded_by, activated_at)
            VALUES (1, 'active', $1::jsonb, $2, 'system-seed', NOW())
            """,
            json.dumps(payload, ensure_ascii=False),
            CHANGE_SUMMARY,
        )
    print(f"Unpinned sessions: {sessions}; audit rows: {audit}; deleted versions: {deleted}")
    print("Reset complete: single version 1 (active) from the bundled file")


async def main(reset: bool = False) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        if reset:
            await reset_to_initial(conn)
        else:
            await seed(conn)
        rows = await conn.fetch(
            "SELECT version_no, status FROM screening_criteria_versions ORDER BY version_no"
        )
        print(
            "Criteria versions: "
            + ", ".join(f"v{r['version_no']}={r['status']}" for r in rows)
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(reset="--reset-to-initial" in sys.argv[1:]))
