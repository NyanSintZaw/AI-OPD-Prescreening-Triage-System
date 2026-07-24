"""Reset the stack to a clean demo state.

    uv run python scripts/reset_demo.py            # retire sessions + reseed HIS state
    uv run python scripts/reset_demo.py --purge    # additionally DELETE all session data

Default (safe) mode:
  - marks every ``active`` session ``reset`` so no VN offers "continue"
  - clears all BP rest windows
  - resets every mock-HIS visit to its pre-registration state
  - wipes booth-collected history for the seeded FIRST-TIME patients only
    (03/04/06/08 — restores their first-time badge; seeded returning
    patients keep their CSV histories)

``--purge`` additionally deletes ALL sessions and their dependent rows
(messages, assessments, reviews, surveillance, screening state, audit) so
the nurse queue and dashboards start empty. Use before a stakeholder demo;
skip it when you want realistic-looking history around.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

FIRST_TIME_VISITS = [
    "990000000000000003",
    "990000000000000004",
    "990000000000000006",
    "990000000000000008",
]

# Session-scoped tables with FKs that don't all cascade — delete children
# first, parents last.
PURGE_STATEMENTS = [
    "DELETE FROM ai_inference_audit",
    "DELETE FROM screening_sessions",
    "DELETE FROM assessment_reviews",
    "DELETE FROM department_recommendations",
    "DELETE FROM severity_assessments",
    "DELETE FROM symptom_entries",
    "DELETE FROM disease_surveillance",
    "DELETE FROM messages",
    "UPDATE bp_readings SET session_id = NULL",
    "DELETE FROM sessions",
]


async def main(purge: bool) -> None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        if purge:
            for stmt in PURGE_STATEMENTS:
                result = await conn.execute(stmt)
                print(f"  {stmt.split(' FROM ')[-1].split(' SET ')[0]:28} {result}")
        else:
            retired = await conn.execute(
                "UPDATE sessions SET status = 'reset' WHERE status = 'active'"
            )
            print(f"  sessions retired (active → reset): {retired}")
        cleared = await conn.execute("DELETE FROM bp_rest_windows")
        print(f"  bp_rest_windows cleared: {cleared}")
    finally:
        await conn.close()

    base = settings.his_base_url or "http://localhost:8001"
    headers = {"X-API-Key": settings.his_api_key or ""}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{base}/api/admin/reset", headers=headers, json={}
        )
        r.raise_for_status()
        print(f"  mock HIS visits reset: {r.json().get('reset')}")
        r = await client.post(
            f"{base}/api/admin/reset",
            headers=headers,
            json={"visit_ids": FIRST_TIME_VISITS, "reset_history": True},
        )
        r.raise_for_status()
        print(f"  first-time patients restored: {len(FIRST_TIME_VISITS)}")

        patients = (
            await client.get(f"{base}/api/patients", headers=headers)
        ).json()["patients"]
        first = sorted(p["hn"] for p in patients if p["is_first_time"])
        print(f"  HIS check → {len(patients)} patients, first-time: {first}")

    print("\nDemo state ready.")
    if not purge:
        print("(Old session rows kept for nurse-queue history — run with "
              "--purge for a completely empty database.)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--purge",
        action="store_true",
        help="delete ALL session data instead of just retiring active sessions",
    )
    args = parser.parse_args()
    asyncio.run(main(args.purge))
