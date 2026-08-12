#!/usr/bin/env python3
"""Publish an edited criteria file to the live booth.

The engine reads the ACTIVE row in ``screening_criteria_versions``, not the
JSON on disk, so editing ``app/data/screening_criteria.json`` changes the
evals and nothing else. ``seed_screening_criteria.py`` cannot push it either:
its refresh branch only fires while version 1 is still the active row.

This inserts the file as the next version number in ``draft``, then runs the
same transaction the activate endpoint uses — retire the current active row,
activate the new one — inside one transaction so there is never a moment with
no active criteria.

    uv run python scripts/deploy_criteria.py            # show what would change
    uv run python scripts/deploy_criteria.py --activate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.services.screening.rules.criteria_models import parse_criteria  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CRITERIA_PATH = ROOT / "app" / "data" / "screening_criteria.json"
DSN = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/hospital_hotline"
)


def _summarize(criteria) -> dict[str, int]:
    """The counts most likely to have changed — enough to eyeball a diff."""
    return {
        "templates": len(criteria.complaint_templates),
        "findings": len(criteria.finding_catalog),
        "level1": len(criteria.level1_criteria),
        "tuples": len(criteria.triage_tuples),
        "danger_vitals": len(criteria.danger_vitals),
        "department_rules": len(criteria.department_rules),
        "temp_questions": sum(
            1
            for t in criteria.complaint_templates
            for q in t.questions
            if q.vital == "temp"
        ),
        "bp_questions": sum(
            1
            for t in criteria.complaint_templates
            for q in t.questions
            if q.vital == "sbp"
        ),
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--activate", action="store_true",
                    help="write and activate; without it, only report the diff")
    args = ap.parse_args()

    payload = json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))
    # Fail before touching the DB if the file is not valid criteria.
    incoming = parse_criteria(payload)
    print(f"file: {CRITERIA_PATH.name}")

    conn = await asyncpg.connect(DSN)
    try:
        active = await conn.fetchrow(
            "SELECT id, version_no, criteria FROM screening_criteria_versions"
            " WHERE status = 'active'"
        )
        if active is None:
            print("No active version — run scripts/seed_screening_criteria.py first.")
            return 1

        live = parse_criteria(json.loads(active["criteria"]))
        before, after = _summarize(live), _summarize(incoming)
        print(f"\nactive: v{active['version_no']}")
        print(f"  {'field':18} {'live':>6} {'file':>6}")
        for key in after:
            mark = "  <-- changes" if before[key] != after[key] else ""
            print(f"  {key:18} {before[key]:>6} {after[key]:>6}{mark}")

        if json.loads(active["criteria"]) == payload:
            print("\nAlready identical; nothing to deploy.")
            return 0
        if not args.activate:
            print("\nDry run. Re-run with --activate to publish.")
            return 0

        next_no = await conn.fetchval(
            "SELECT COALESCE(MAX(version_no), 0) + 1 FROM screening_criteria_versions"
        )
        # Retire BEFORE inserting: uq_screening_criteria_active is a partial
        # unique index allowing exactly one active row, and it is not
        # deferrable, so insert-then-retire fails at the insert. Both
        # statements are in one transaction, so there is no window where the
        # engine would find no active criteria.
        async with conn.transaction():
            await conn.execute(
                "UPDATE screening_criteria_versions SET status = 'retired'"
                " WHERE status = 'active'"
            )
            await conn.execute(
                """
                INSERT INTO screening_criteria_versions
                    (version_no, status, criteria, change_summary, uploaded_by,
                     activated_at)
                VALUES ($1, 'active', $2::jsonb, $3, 'deploy-script', NOW())
                """,
                next_no,
                json.dumps(payload, ensure_ascii=False),
                f"Deployed {CRITERIA_PATH.name} over v{active['version_no']}",
            )
        print(f"\nActivated v{next_no} (v{active['version_no']} retired).")
        print("Sessions already running keep their pinned version; new ones get this.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
