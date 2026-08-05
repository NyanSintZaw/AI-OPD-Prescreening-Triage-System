"""Seed (or refresh) screening criteria from the bundled JSON files.

Run with: ``uv run python scripts/seed_screening_criteria.py [--activate-v2]``.

Idempotent: validates each bundled document against the schema, then

- v1 (``screening_criteria_v1.json``) is inserted as ``active`` if no
  version-1 row exists yet;
- v2 (``screening_criteria_v2.json``) is inserted as a ``draft`` awaiting
  the admin review flow.

If a row already exists (matched on ``version_no`` — unique index), its JSON
is refreshed in place only when it still has its seeded status (v1 active,
v2 draft) and differs from the file (hand-edits during development);
otherwise nothing changes.

``--activate-v2`` (dev shortcut): activates the v2 row using the same SQL
semantics as the ``/admin/criteria/.../activate`` endpoint — one transaction
that retires the current active row and marks v2 active (the partial unique
index guarantees exactly one active). Production activates via the admin UI
review flow instead.
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

DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "data"
SEEDS = [
    # (version_no, path, seeded status, change_summary)
    (
        1,
        DATA_DIR / "screening_criteria_v1.json",
        "active",
        "Initial hand-encoded criteria from the MFU patient triage manual "
        "(คู่มือเกณฑ์การคัดกรองผู้ป่วย)",
    ),
    (
        2,
        DATA_DIR / "screening_criteria_v2.json",
        "draft",
        "v2 breadth additions (ESI v5-cited): 10 new complaint categories "
        "and source_standards provenance",
    ),
]
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/hospital_hotline"
)


async def seed_version(
    conn: asyncpg.Connection,
    version_no: int,
    path: pathlib.Path,
    status: str,
    change_summary: str,
) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    parse_criteria(payload)  # raises on invalid criteria
    print(f"Validated {path.name}")

    row = await conn.fetchrow(
        "SELECT id, status, criteria FROM screening_criteria_versions WHERE version_no = $1",
        version_no,
    )
    criteria_json = json.dumps(payload, ensure_ascii=False)
    if row is None:
        await conn.execute(
            """
            INSERT INTO screening_criteria_versions
                (version_no, status, criteria, change_summary, uploaded_by, activated_at)
            VALUES ($1, $2, $3::jsonb, $4, 'system-seed',
                    CASE WHEN $5 THEN NOW() END)
            """,
            version_no,
            status,
            criteria_json,
            change_summary,
            status == "active",
        )
        print(f"Inserted screening criteria version {version_no} ({status})")
    elif row["status"] == status and json.loads(row["criteria"]) != payload:
        await conn.execute(
            "UPDATE screening_criteria_versions SET criteria = $1::jsonb WHERE id = $2",
            criteria_json,
            row["id"],
        )
        print(f"Refreshed {status} version {version_no} criteria from file")
    else:
        print(f"Version {version_no} already present (status={row['status']}); no change")


async def activate_v2(conn: asyncpg.Connection) -> None:
    """Dev shortcut mirroring the activate endpoint's transaction."""
    row = await conn.fetchrow(
        "SELECT id, status FROM screening_criteria_versions WHERE version_no = 2"
    )
    if row is None:
        raise SystemExit("--activate-v2: no version 2 row exists to activate")
    if row["status"] == "active":
        print("Version 2 already active; no change")
        return
    async with conn.transaction():
        await conn.execute(
            "UPDATE screening_criteria_versions SET status = 'retired' WHERE status = 'active'"
        )
        await conn.execute(
            """UPDATE screening_criteria_versions
                  SET status = 'active', activated_at = NOW() WHERE id = $1""",
            row["id"],
        )
    print("Activated version 2 (previous active retired)")


async def main(activate_v2_flag: bool = False) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        for version_no, path, status, change_summary in SEEDS:
            await seed_version(conn, version_no, path, status, change_summary)
        if activate_v2_flag:
            await activate_v2(conn)
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
    asyncio.run(main(activate_v2_flag="--activate-v2" in sys.argv[1:]))
