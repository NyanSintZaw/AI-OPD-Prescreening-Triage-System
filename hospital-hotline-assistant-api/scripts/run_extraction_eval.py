"""Single-utterance extraction eval — the synonym flywheel's measuring stick.

For each phrase in ``evals/extraction_phrases.json``, run the REAL extraction
call (same prompt builder + model config as production) on a fresh state and
score which finding ids came back:

- recall miss  — an ``expect`` id was not extracted as present
- over-match   — a ``forbid`` id WAS extracted as present (the false-Red class)
- stray        — any other L1/L2-critical id extracted that is not in
                 expect/allow (informational; the confirm gate absorbs these)

Findings that fail here become synonym edits in the criteria document (or
catalog additions to the turn-1 opener set in extraction._catalog_lines) —
never new code. Re-run after tuning; reports land in evals/reports/.

Usage:
  uv run python scripts/run_extraction_eval.py            # real model (.env)
  uv run python scripts/run_extraction_eval.py --ids cp_th_1,befast_en
  uv run python scripts/run_extraction_eval.py --criteria v2   # default: v2 file
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.screening.extraction import (  # noqa: E402
    ExtractionResult,
    build_extraction_prompt,
)
from app.services.screening.model_adapter import build_chat_model  # noqa: E402
from app.services.screening.rules.criteria_models import parse_criteria  # noqa: E402
from app.services.screening.rules.red_flags import critical_finding_ids  # noqa: E402
from app.services.screening.state import ScreeningState  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONCURRENCY = 8





async def run_case(model, criteria, case, sem) -> dict:
    state = ScreeningState(
        session_id=f"eval-{case['id']}", language=case["language"]
    )
    if case.get("category"):
        state.complaint_category = case["category"]
    prompt = build_extraction_prompt(criteria, state, case["phrase"], None)
    async with sem:
        try:
            structured = model.with_structured_output(ExtractionResult)
            result: ExtractionResult = await asyncio.wait_for(
                structured.ainvoke(prompt), timeout=30
            )
        except Exception as exc:
            return {**case, "error": f"{type(exc).__name__}: {exc}"}

    present = {u.id for u in result.finding_updates if u.state == "present"}
    evidence = {
        u.id: u.evidence for u in result.finding_updates if u.state == "present"
    }
    crit = critical_finding_ids(criteria)
    misses = sorted(set(case["expect"]) - present)
    overmatch = sorted(set(case.get("forbid", [])) & present)
    stray = sorted(
        (present & crit) - set(case["expect"]) - set(case.get("allow", []))
        - set(case.get("forbid", []))
    )
    return {
        **case,
        "present": sorted(present),
        "evidence": evidence,
        "misses": misses,
        "overmatch": overmatch,
        "stray": stray,
        "passed": not misses and not overmatch,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--criteria", default="v2", choices=["v1", "v2"])
    args = ap.parse_args()

    corpus = json.loads((ROOT / "evals" / "extraction_phrases.json").read_text())
    cases = corpus["cases"]
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    criteria = parse_criteria(json.loads(
        (ROOT / "app" / "data" / f"screening_criteria_{args.criteria}.json").read_text()
    ))
    model = build_chat_model(settings)
    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(
        *(run_case(model, criteria, c, sem) for c in cases)
    )

    ok = [r for r in results if r.get("passed")]
    print(f"\n{len(ok)}/{len(results)} passed")
    for r in results:
        if r.get("error"):
            print(f"  ERROR {r['id']}: {r['error']}")
        elif not r["passed"]:
            print(f"  FAIL  {r['id']}: miss={r['misses']} overmatch={r['overmatch']}"
                  f" got={r['present']}")
        elif r["stray"]:
            print(f"  pass~ {r['id']}: stray criticals {r['stray']}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "evals" / "reports" / f"extraction-{stamp}.json"
    out.write_text(json.dumps(
        {"criteria": args.criteria, "model": settings.screening_model_name,
         "passed": len(ok), "total": len(results), "results": results},
        ensure_ascii=False, indent=1))
    print("report:", out)


if __name__ == "__main__":
    asyncio.run(main())
