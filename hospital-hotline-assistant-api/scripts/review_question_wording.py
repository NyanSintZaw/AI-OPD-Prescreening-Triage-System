"""Render every screening question through the real model and list the
template next to the rewording the model produced, with the wording guard's
verdict — the nurse-review sheet for "the model may reword, it must keep the
symptom".

    uv run python scripts/review_question_wording.py [--language th|en] [--ids a,b]

Writes evals/reports/question-wording-<ts>.md (+ .json). No state, no recent
exchange, no chief complaint: this is the wording in isolation — the live
render also sees the last two turns and the known answers.

Run after touching the paraphrase prompt, the guard, the catalog labels /
synonyms, or before go-live on a new model (Typhoon on the workstation).
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
from app.services.screening.model_adapter import build_chat_model  # noqa: E402
from app.services.screening.nodes.question import (  # noqa: E402
    _PARAPHRASE_PROMPT,
    _REPHRASE_INSTRUCTION,
    PARAPHRASABLE_KINDS,
    PhrasedQuestion,
    keep_terms_line,
    wording_violations,
)
from app.services.screening.persona import persona_block  # noqa: E402
from app.services.screening.rules.criteria_store import load_seed_criteria  # noqa: E402
from app.services.screening.rules.question_policy import confirm_question_for  # noqa: E402
from app.services.screening.rules.red_flags import critical_finding_ids  # noqa: E402
from app.services.screening.validator import validate_reply  # noqa: E402

REPORTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "evals" / "reports"


def all_questions(criteria):
    seen: set[str] = set()
    for source, qs in (
        ("universal", criteria.universal_questions),
        *((t.category, t.questions) for t in criteria.complaint_templates),
        ("pre_disposition", criteria.pre_disposition_questions),
    ):
        for q in qs:
            if q.id in seen:
                continue
            seen.add(q.id)
            yield source, q
    for fid in sorted(critical_finding_ids(criteria)):
        q = confirm_question_for(criteria, fid)
        if q.id not in seen:
            seen.add(q.id)
            yield "confirm", q


async def render(model, criteria, source, question, language, sem):
    verbatim = question.text_en if language == "en" else question.text_th
    instruction = _REPHRASE_INSTRUCTION[language]
    keep = keep_terms_line(question, verbatim, criteria, language)
    if keep:
        instruction = f"{instruction}\n{keep}"
    prompt = _PARAPHRASE_PROMPT[language].format(
        persona=persona_block(language), recent="-", context="-", known="-",
        instruction=instruction, question=verbatim,
    )
    row = {
        "id": question.id, "kind": question.kind, "source": source,
        "language": language, "verbatim": verbatim, "guarded_terms": keep,
    }
    async with sem:
        phrased: PhrasedQuestion | None = None
        error = ""
        for attempt in range(5):
            try:
                phrased = await asyncio.wait_for(
                    model.with_structured_output(PhrasedQuestion).ainvoke(prompt), timeout=30
                )
                break
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
                if "429" not in error and "RESOURCE_EXHAUSTED" not in error:
                    break
                await asyncio.sleep(2 ** attempt)  # quota: back off, retry
        if phrased is None:
            return {**row, "error": error}
    candidate = (phrased.question or "").strip()
    violations = wording_violations(question, verbatim, candidate, criteria, language)
    leaks = validate_reply(candidate, language=language)
    if leaks:
        violations.append("validator")
    return {
        **row,
        "ack": phrased.ack,
        "paraphrase": candidate,
        "violations": violations,
        "used": not violations and candidate != verbatim,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--language", choices=["th", "en"], default=None)
    ap.add_argument("--ids", default=None, help="comma-separated question ids")
    args = ap.parse_args()

    criteria = load_seed_criteria()
    model = build_chat_model(settings)
    sem = asyncio.Semaphore(4)
    langs = [args.language] if args.language else ["th", "en"]
    wanted = set(args.ids.split(",")) if args.ids else None
    jobs = [
        render(model, criteria, source, q, lang, sem)
        for source, q in all_questions(criteria)
        for lang in langs
        if q.kind in PARAPHRASABLE_KINDS and (wanted is None or q.id in wanted)
    ]
    rows = await asyncio.gather(*jobs)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"question-wording-{ts}.json").write_text(
        json.dumps({"model": settings.screening_model_name, "rows": rows}, ensure_ascii=False, indent=1)
    )
    lines = [
        f"# Question wording review — {ts}", "",
        f"- model: {settings.screening_model_provider}:{settings.screening_model_name}",
        f"- questions rendered: {len(rows)} (every kind except measurement; confirm = one per critical finding)",
        "",
    ]
    for lang in langs:
        sub = [r for r in rows if r["language"] == lang]
        ok = [r for r in sub if r.get("used")]
        rej = [r for r in sub if r.get("violations")]
        err = [r for r in sub if r.get("error")]
        lines.append(
            f"- **{lang}**: rewording used {len(ok)}/{len(sub)}, refused → template "
            f"{len(rej)}, errors {len(err)}"
        )
        by_reason: dict[str, int] = {}
        for r in rej:
            for v in r["violations"]:
                by_reason[v.split(":")[0]] = by_reason.get(v.split(":")[0], 0) + 1
        if by_reason:
            lines.append(f"  - refusal reasons: {by_reason}")
    lines += ["", "## Sheet", "", "| id | kind | lang | template | model's rewording | verdict |", "|---|---|---|---|---|---|"]
    for r in rows:
        verdict = ("ERROR " + r["error"]) if r.get("error") else (
            "used" if r.get("used") else ("same" if r.get("paraphrase") == r["verbatim"] else "refused: " + ", ".join(r["violations"]))
        )
        para = (r.get("paraphrase") or "").replace("|", "\\|")
        lines.append(
            f"| {r['id']} | {r['kind']} | {r['language']} | {r['verbatim'].replace('|', '/')} | {para} | {verdict} |"
        )
    (REPORTS_DIR / f"question-wording-{ts}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    print(f"report: {REPORTS_DIR / f'question-wording-{ts}.md'}")


if __name__ == "__main__":
    asyncio.run(main())
