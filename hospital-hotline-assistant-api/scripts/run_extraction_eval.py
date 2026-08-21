"""Single-utterance extraction eval — the synonym flywheel's measuring stick.

For each phrase in ``evals/extraction_phrases.json``, run the REAL extraction
call (same prompt builder + model config as production) on a fresh state and
score which finding ids came back:

- recall miss  — an ``expect`` id was not extracted as present
- over-match   — a ``forbid`` id WAS extracted as present (the false-Red class)
- absent miss  — an ``expect_absent`` id the patient DENIED that did not come
                 back as state="absent". This is the repetitive-question
                 class: an uncredited denial leaves the finding unknown, so
                 the interview asks about it again ("I have a fever but no
                 headache" -> still asked about headache)
- wrong category — the model categorised on a symptom the patient denied
- stray        — any other L1/L2-critical id extracted that is not in
                 expect/allow (informational; the confirm gate absorbs these)

Findings that fail here become synonym edits in the criteria document (or
catalog additions to the turn-1 opener set in extraction._catalog_lines) —
never new code. Re-run after tuning; reports land in evals/reports/.

Usage:
  uv run python scripts/run_extraction_eval.py            # real model (.env)
  uv run python scripts/run_extraction_eval.py --ids cp_th_1,befast_en
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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
from app.services.screening.rules.criteria_store import load_seed_criteria  # noqa: E402
from app.services.screening.rules.red_flags import critical_finding_ids  # noqa: E402
from app.services.screening.state import ScreeningState  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
# 8 suits a hosted model that fans out. A local single-GPU server (Ollama on
# one card) serialises requests instead, so the extra callers just queue and
# blow the per-call timeout — every case after the first reports as an error
# and the run looks like a quality collapse. Set EVAL_CONCURRENCY=1 for local.
CONCURRENCY = int(os.environ.get("EVAL_CONCURRENCY", "8"))





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
    absent = {u.id for u in result.finding_updates if u.state == "absent"}
    evidence = {
        u.id: u.evidence for u in result.finding_updates if u.state == "present"
    }
    crit = critical_finding_ids(criteria)
    misses = sorted(set(case["expect"]) - present)
    # A denial the model dropped leaves the finding unknown, and unknown means
    # the interview asks about it again.
    absent_misses = sorted(set(case.get("expect_absent", [])) - absent)
    want_category = case.get("expect_category")
    category_wrong = bool(want_category) and result.complaint_category != want_category
    overmatch = sorted(set(case.get("forbid", [])) & present)
    stray = sorted(
        (present & crit) - set(case["expect"]) - set(case.get("allow", []))
        - set(case.get("forbid", []))
    )
    return {
        **case,
        "present": sorted(present),
        "absent": sorted(absent),
        "got_category": result.complaint_category,
        "evidence": evidence,
        "misses": misses,
        "absent_misses": absent_misses,
        "category_wrong": category_wrong,
        "overmatch": overmatch,
        "stray": stray,
        "passed": not misses and not overmatch and not absent_misses
        and not category_wrong,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    args = ap.parse_args()

    corpus = json.loads((ROOT / "evals" / "extraction_phrases.json").read_text())
    cases = corpus["cases"]
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    criteria = load_seed_criteria()
    model = build_chat_model(settings)
    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(
        *(run_case(model, criteria, c, sem) for c in cases)
    )

    ok = [r for r in results if r.get("passed")]
    # Errored calls have no verdict — counting them as clean would report a
    # dead model as a passing one.
    denial_cases = [r for r in results
                    if r.get("expect_absent") and not r.get("error")]
    print(f"\n{len(ok)}/{len(results)} passed")
    errors = [r for r in results if r.get("error")]
    if errors:
        print(f"{len(errors)} call(s) errored — excluded from every rate below")
    if denial_cases:
        clean = [r for r in denial_cases if not r.get("absent_misses")
                 and not r.get("category_wrong")]
        print(f"{len(clean)}/{len(denial_cases)} volunteered denials credited"
              " (uncredited = a question the patient will be asked again)")
    for r in results:
        if r.get("error"):
            print(f"  ERROR {r['id']}: {r['error']}")
        elif not r["passed"]:
            detail = f"miss={r['misses']} overmatch={r['overmatch']}"
            if r.get("absent_misses"):
                detail += f" denial-dropped={r['absent_misses']}"
            if r.get("category_wrong"):
                detail += (f" category={r['got_category']!r}"
                           f" want={r.get('expect_category')!r}")
            print(f"  FAIL  {r['id']}: {detail} got={r['present']}")
        elif r["stray"]:
            print(f"  pass~ {r['id']}: stray criticals {r['stray']}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "evals" / "reports" / f"extraction-{stamp}.json"
    out.write_text(json.dumps(
        {"criteria": "seed", "model": settings.screening_model_name,
         "passed": len(ok), "total": len(results), "results": results},
        ensure_ascii=False, indent=1))
    print("report:", out)


if __name__ == "__main__":
    asyncio.run(main())
