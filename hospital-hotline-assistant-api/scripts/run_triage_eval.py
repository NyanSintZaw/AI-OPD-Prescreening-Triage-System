#!/usr/bin/env python3
"""On-demand triage-quality eval harness.

Drives the deterministic screening engine DIRECTLY (no HTTP, no Postgres)
over labeled vignettes in evals/vignettes.json and scores category / level /
department / undertriage / must-ask coverage / validator leaks.

Default run uses the REAL LLM built exactly like production
(``build_chat_model(settings)``) — run it only when you intend API spend.
``--dry-run`` swaps in the tests' FakeChatModel with a scripted feeder to
prove the machinery without any network call (scores are then meaningless
except as plumbing checks).

Usage:
    uv run python scripts/run_triage_eval.py --dry-run
    uv run python scripts/run_triage_eval.py --language th --ids cp_th_crushing
    uv run python scripts/run_triage_eval.py --criteria active
    uv run python scripts/run_triage_eval.py --criteria v2 --rag
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.screening import templates  # noqa: E402
from app.services.screening.engine import ScreeningTriageEngine  # noqa: E402
from app.services.screening.extraction import ExtractionResult  # noqa: E402
from app.services.screening.persistence import InMemoryStateStore  # noqa: E402
from app.services.screening.rules.criteria_models import ScreeningCriteria  # noqa: E402
from app.services.screening.rules.criteria_store import load_seed_criteria  # noqa: E402
from app.services.screening.validator import validate_reply  # noqa: E402

VIGNETTES_PATH = ROOT / "evals" / "vignettes.json"
REPORTS_DIR = ROOT / "evals" / "reports"
TURN_CAP = 15

VALIDATOR_DEPARTMENT_NAMES = {
    code: [n for n in names.values() if n]
    for code, names in templates.DEPARTMENT_NAMES.items()
}

DEFAULT_MEASUREMENTS = {"bp": [118, 76], "temp": 36.8, "weight": 65, "height": 165}
DEFAULT_ANSWER = {"en": "no", "th": "ไม่มีค่ะ"}
DEFAULT_SCALE_ANSWER = {"en": "about a 3", "th": "ประมาณ 3 ค่ะ"}
DEFAULT_CONFIRM_ANSWER = {"en": "yes, that's right", "th": "ใช่ค่ะ"}
DEFAULT_DECLINE = {"en": "no, that's all, thank you", "th": "ไม่มีแล้วค่ะ ขอบคุณค่ะ"}
MEASURED_TEXT = {"en": "okay, measured", "th": "วัดแล้วค่ะ"}


# -- vignette plumbing --------------------------------------------------------


def load_vignettes(path: Path = VIGNETTES_PATH) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def level_band(expected_level: Any) -> tuple[int, int]:
    if isinstance(expected_level, int):
        return expected_level, expected_level
    lo, hi = expected_level
    return int(lo), int(hi)


def question_kind_index(criteria: ScreeningCriteria) -> dict[str, str]:
    index: dict[str, str] = {}
    questions = list(criteria.universal_questions) + list(criteria.pre_disposition_questions)
    for template in criteria.complaint_templates:
        questions.extend(template.questions)
    for q in questions:
        index[q.id] = q.kind
    return index


def measurement_ctx(vital: str, measurements: dict[str, Any]) -> dict[str, float]:
    m = {**DEFAULT_MEASUREMENTS, **(measurements or {})}
    if vital == "sbp":
        bp = m["bp"]
        return {"sbp": float(bp[0]), "dbp": float(bp[1])}
    if vital == "weight":
        return {"weight": float(m["weight"]), "height": float(m["height"])}
    if vital == "temp":
        return {"temp": float(m["temp"])}
    return {vital: float(m.get(vital, 0.0))}


def pick_answer(
    vig: dict[str, Any],
    question_id: str,
    question_text: str,
    kind_index: dict[str, str],
    *,
    confirming: list[str] | None = None,
    unmatched: list[str] | None = None,
) -> str:
    for entry in vig.get("answers", []):
        pattern = entry["match"]
        if re.search(pattern, question_id or "", re.IGNORECASE) or re.search(
            pattern, question_text or "", re.IGNORECASE
        ):
            return entry["reply"]
    if unmatched is not None and question_id:
        unmatched.append(question_id)
    if kind_index.get(question_id) == "scale":
        return DEFAULT_SCALE_ANSWER[vig["language"]]
    # A CONFIRM question re-checks ONE finding the patient's own words already
    # produced, before a level-1/2 rule may fire. Answer it from the vignette's
    # `present` list (the findings that are TRUE for this patient): a blanket
    # "no" made the patient contradict its own opening ("ปากก็บวม" -> "no lip
    # swelling", four manufactured undertriage misses), a blanket "yes" made it
    # claim findings it never had (fishbone affirming airway obstruction).
    # The question node asks confirming[0], so only that finding is answered.
    if confirming:
        present = vig.get("present")
        if present is None:
            # No authored truth = the answer would be a guess. Never silent.
            if unmatched is not None:
                unmatched.append(f"NO_PRESENT_FOR_CONFIRM:{confirming[0]}")
            return DEFAULT_CONFIRM_ANSWER[vig["language"]]  # fail-safe: overtriage
        answer = DEFAULT_CONFIRM_ANSWER if confirming[0] in present else DEFAULT_ANSWER
        return answer[vig["language"]]
    return DEFAULT_ANSWER[vig["language"]]


# -- engine construction ------------------------------------------------------


def build_engine(
    criteria: ScreeningCriteria, model: Any, *, question_budget: int = 8,
    model_label: str = "screening:eval", rag_search: Any = None,
) -> tuple[ScreeningTriageEngine, InMemoryStateStore]:
    """Engine over an in-memory store — DB-free. RAG (explanation-only, and
    only for non-emergency dispositions) is off unless a search fn is passed."""
    store = InMemoryStateStore(criteria)
    engine = ScreeningTriageEngine(
        model=model,
        store=store,
        question_budget=question_budget,
        model_label=model_label,
        rag_search=rag_search,
    )
    return engine, store


RAG_CALLS: list[dict[str, Any]] = []


async def build_rag_search() -> Any:
    """production `search_triage_manual`, wrapped to record what it returned.

    Prewarmed first: the explain node gives RAG a 1.5s budget, and a cold index
    (HuggingFace embed model load) blows that on the very first vignette."""
    from app.services.ai.rag_query import prewarm_rag_query_engine, search_triage_manual

    warm = await prewarm_rag_query_engine()
    print(f"RAG: enabled (index prewarm {'ok' if warm else 'FAILED — expect misses'})")

    async def counting_search(query: str) -> str:
        try:
            text = await search_triage_manual(query)
        except Exception as exc:  # search_triage_manual swallows its own, belt+braces
            RAG_CALLS.append({"query": query, "chars": 0, "error": repr(exc)})
            raise
        RAG_CALLS.append({
            "query": query,
            "chars": len(text or ""),
            # the fn returns this sentence instead of raising when the index is down
            "hit": bool(text.strip()) and not text.startswith("ไม่พบข้อมูลจากคู่มือ"),
        })
        return text

    return counting_search


def build_real_model() -> tuple[Any, str]:
    """The production model, built exactly like make_triage_engine does."""
    from app.config import settings
    from app.services.screening.model_adapter import build_chat_model

    model = build_chat_model(settings)
    label = (
        f"screening:{settings.screening_model_provider}:{settings.screening_model_name}"
    )
    return model, label


def build_dry_model() -> Any:
    from tests.screening.fakes import FakeChatModel

    return FakeChatModel()


def dry_run_feeder(
    turn_no: int, vig: dict[str, Any], criteria: ScreeningCriteria
) -> ExtractionResult:
    """Scripted extraction for --dry-run: seed the complaint/category on turn 1
    (proves category plumbing, not the model), empty extractions after. The
    interview then runs to budget exhaustion and disposes — terminating the
    loop and exercising questions, measurements, scoring, and reports."""
    if turn_no == 1:
        expected = vig.get("expected", {})
        category = next(iter(_as_list(expected.get("category"))), None)
        valid = {t.category for t in criteria.complaint_templates}
        return ExtractionResult(
            chief_complaint=vig["opening"][:120],
            complaint_category=category if category in valid else None,
        )
    return ExtractionResult()


# -- one vignette -------------------------------------------------------------


async def run_vignette(
    vig: dict[str, Any],
    engine: ScreeningTriageEngine,
    store: InMemoryStateStore,
    criteria: ScreeningCriteria,
    *,
    model: Any = None,
    feeder: Any = None,
    turn_cap: int = TURN_CAP,
) -> dict[str, Any]:
    """Drive one vignette to disposal (or the cap) and return raw outcome."""
    language = vig["language"]
    session_id = f"eval-{vig['id']}-{uuid.uuid4().hex[:8]}"
    kind_index = question_kind_index(criteria)

    if model is not None and hasattr(model, "extractions"):
        model.extractions.clear()  # never leak canned turns across vignettes

    text = vig["opening"]
    ctx: dict[str, Any] | None = {}
    if vig.get("age") is not None:
        ctx["age_years"] = vig["age"]
    if vig.get("initial_vitals"):
        ctx["vitals"] = dict(vig["initial_vitals"])
    ctx = ctx or None

    transcript: list[dict[str, Any]] = []
    unmatched: list[str] = []
    leaks: list[str] = []
    classification: dict[str, Any] = {}
    escalated = False
    flow_complete = False
    turn1_findings: dict[str, str] = {}
    started = time.monotonic()
    turns = 0
    result: dict[str, Any] = {}

    for turn_no in range(1, turn_cap + 1):
        if feeder is not None and model is not None:
            model.extractions.append(feeder(turn_no, vig, criteria))
        result = await engine.run_turn(
            session_id=session_id,
            language=language,
            input_mode="text",
            content=text,
            turn_context=ctx,
        )
        ctx = None
        turns = turn_no
        state = await store.load(session_id)
        assert state is not None
        if turn_no == 1:
            turn1_findings = state.finding_states()
        classification = result["classification"] or {}
        is_final = bool(classification.get("classified"))
        violations = validate_reply(
            result["reply"],
            language=language,
            department_code=classification.get("department_code") if is_final else None,
            department_names=VALIDATOR_DEPARTMENT_NAMES if is_final else None,
            is_emergency=is_final and classification.get("level", 5) <= 2,
        )
        leaks.extend(f"turn {turn_no}: {v}" for v in violations)
        transcript.append({
            "turn": turn_no,
            "patient": text,
            "question_id": state.pending_question_id if not is_final else None,
            "reply": result["reply"],
            "awaiting_measurement": result.get("awaiting_measurement"),
            "classified": is_final,
        })
        escalated = bool(result.get("escalated"))
        flow_complete = bool(result.get("flow_complete"))
        if is_final or escalated:
            break
        if result.get("awaiting_measurement"):
            vital = result["awaiting_measurement"]
            ctx = {"vitals": measurement_ctx(vital, vig.get("measurements") or {})}
            text = MEASURED_TEXT[language]
        else:
            text = pick_answer(
                vig, state.pending_question_id or "", result["reply"], kind_index,
                confirming=list(getattr(state, "pending_confirm", []) or []),
                unmatched=unmatched,
            )

    # Post-disposition follow-up phase (non-emergency): answer the offer.
    post_turns = 0
    while classification.get("classified") and not flow_complete and post_turns < 3:
        fu_text = (
            vig.get("follow_up_reply")
            if post_turns == 0 and vig.get("follow_up_reply")
            else DEFAULT_DECLINE[language]
        )
        result = await engine.run_turn(
            session_id=session_id, language=language, input_mode="text", content=fu_text
        )
        post_turns += 1
        flow_complete = bool(result.get("flow_complete"))
        violations = validate_reply(result["reply"], language=language)
        leaks.extend(f"follow-up {post_turns}: {v}" for v in violations)
        transcript.append({
            "turn": turns + post_turns,
            "patient": fu_text,
            "reply": result["reply"],
            "post_disposition": True,
        })

    final_state = await store.load(session_id)
    assert final_state is not None
    return {
        "classification": classification,
        "category_actual": final_state.complaint_category,
        "asked_question_ids": list(final_state.asked_question_ids),
        "findings": final_state.finding_states(),
        "turn1_findings": turn1_findings,
        "patient_follow_up": final_state.patient_follow_up,
        "flow_complete": flow_complete,
        "escalated": escalated,
        "leaks": leaks,
        # Questions no vignette pattern matched, so a default answer was used.
        # Silence here used to hide the simulated patient denying its own
        # opening — surfaced so a corpus gap can never look like a defect.
        "unmatched_questions": unmatched,
        "turns": turns,
        "post_turns": post_turns,
        "wall_time_s": round(time.monotonic() - started, 2),
        "transcript": transcript,
    }


# -- scoring ------------------------------------------------------------------


def expected_categories(vig: dict[str, Any], criteria_mode: str) -> list[str]:
    """v1 runs score against ``expected.category``; v2/active runs score
    against ``expected.category_v2`` when the label differs, else v1."""
    expected = vig.get("expected", {})
    if criteria_mode != "v1" and expected.get("category_v2"):
        return _as_list(expected["category_v2"])
    return _as_list(expected.get("category"))


def score_vignette(
    vig: dict[str, Any], outcome: dict[str, Any], criteria_mode: str
) -> dict[str, Any]:
    expected = vig.get("expected", {})
    fail: list[str] = []

    cats = expected_categories(vig, criteria_mode)
    category_ok = outcome["category_actual"] in cats if cats else True
    if not category_ok:
        fail.append(f"category {outcome['category_actual']!r} not in {cats}")

    lo, hi = level_band(expected["level"])
    level = outcome["classification"].get("level")
    level_ok = isinstance(level, int) and lo <= level <= hi
    within_1 = isinstance(level, int) and (lo - 1) <= level <= (hi + 1)
    if not outcome["classification"].get("classified"):
        fail.append("no disposition within turn cap")
    elif not level_ok:
        fail.append(f"level {level} outside [{lo},{hi}]")

    critical_expected = bool(expected.get("undertriage_critical")) or hi <= 2
    undertriage = critical_expected and not (isinstance(level, int) and level <= 2)
    if undertriage:
        fail.append(f"CRITICAL undertriage: expected <=2, assessed {level}")

    depts = _as_list(expected.get("department"))
    dept_actual = outcome["classification"].get("department_code")
    department_ok = dept_actual in depts if depts else True
    if not department_ok:
        fail.append(f"department {dept_actual!r} not in {depts}")

    asked = outcome["asked_question_ids"]
    asked_texts = [
        t.get("reply", "") for t in outcome["transcript"] if not t.get("classified")
    ]
    must_ask_missing = [
        pattern
        for pattern in expected.get("must_ask", [])
        if not any(re.search(pattern, qid, re.IGNORECASE) for qid in asked)
        and not any(re.search(pattern, txt, re.IGNORECASE) for txt in asked_texts)
    ]
    if must_ask_missing:
        fail.append(f"must_ask not asked: {must_ask_missing}")

    if outcome["leaks"]:
        fail.append(f"{len(outcome['leaks'])} validator leak(s)")
    if outcome["escalated"]:
        fail.append("escalated to nurse")

    for fid, want in (expected.get("findings") or {}).items():
        actual = outcome["findings"].get(fid)
        ok = (
            actual == want
            if want in ("present", "absent")
            else actual != "absent"  # "not_absent": missing or present both fine
        )
        if not ok:
            fail.append(f"finding {fid}={actual!r}, wanted {want}")
    for fid, want in (expected.get("turn1_findings") or {}).items():
        if outcome["turn1_findings"].get(fid) != want:
            fail.append(
                f"turn-1 finding {fid}={outcome['turn1_findings'].get(fid)!r}, wanted {want}"
            )

    if vig.get("follow_up_expected") == "decline":
        if outcome["patient_follow_up"] is not None:
            fail.append(
                f"decline recorded as note: {outcome['patient_follow_up']!r}"
            )
        if not outcome["flow_complete"]:
            fail.append("decline did not close the flow")

    return {
        "id": vig["id"],
        "language": vig["language"],
        "description": vig.get("description", ""),
        "category_expected": cats,
        "category_actual": outcome["category_actual"],
        "category_ok": category_ok,
        "level_expected": [lo, hi],
        "level_actual": level,
        "level_ok": level_ok,
        "within_1": within_1,
        "undertriage_expected": critical_expected,
        "undertriage_critical_fail": undertriage,
        "department_expected": depts,
        "department_actual": dept_actual,
        "department_ok": department_ok,
        "must_ask_missing": must_ask_missing,
        "leaks": outcome["leaks"],
        "turns": outcome["turns"],
        "wall_time_s": outcome["wall_time_s"],
        "passed": not fail,
        "fail_reasons": fail,
        "transcript": outcome["transcript"],
    }


# -- pure-python stats (no scipy) --------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (Numerical Recipes, Lentz)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        for aa in (
            m * (b - m) * x / ((qam + m2) * (a + m2)),
            -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2)),
        ):
            d = 1.0 + aa * d
            d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
            c = 1.0 + aa / c
            if abs(c) < 1e-30:
                c = 1e-30
            h *= d * c
        if abs(d * c - 1.0) < 1e-12:
            break
    return h


def _reg_inc_beta(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b) via lgamma + continued fraction."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _beta_ppf(p: float, a: float, b: float) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(80):  # bisection: 2^-80 ≫ needed precision
        mid = (lo + hi) / 2.0
        if _reg_inc_beta(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact (Clopper-Pearson) binomial CI for k successes out of n."""
    if n == 0:
        return 0.0, 1.0
    lo = 0.0 if k == 0 else _beta_ppf(alpha / 2.0, k, n - k + 1)
    hi = 1.0 if k == n else _beta_ppf(1.0 - alpha / 2.0, k + 1, n - k)
    return lo, hi


def qwk(pairs: list[tuple[int, int]], num_classes: int = 5) -> float | None:
    """Quadratic-weighted Cohen's kappa over 1-based (expected, actual) pairs."""
    if not pairs:
        return None
    n, k = len(pairs), num_classes
    obs = [[0.0] * k for _ in range(k)]
    for e, a in pairs:
        obs[e - 1][a - 1] += 1.0 / n
    row = [sum(r) for r in obs]
    col = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = ((i - j) ** 2) / ((k - 1) ** 2)
            num += w * obs[i][j]
            den += w * row[i] * col[j]
    if den == 0.0:
        return 1.0  # single class on both sides = perfect agreement
    return 1.0 - num / den


def _qwk_pairs(results: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Band convention: expected = actual clamped into [lo, hi], so an in-band
    assessment scores perfect and an out-of-band one is penalised only by its
    distance to the nearest band edge (see evals/README.md)."""
    pairs = []
    for r in results:
        level = r["level_actual"]
        if not isinstance(level, int):
            continue
        lo, hi = r["level_expected"]
        pairs.append((min(max(level, lo), hi), level))
    return pairs


def _metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    critical = [r for r in results if r["undertriage_expected"]]
    misses = [r for r in critical if r["undertriage_critical_fail"]]

    def pct(hits: int, total: int) -> float:
        return round(100.0 * hits / total, 1) if total else 0.0

    ci = clopper_pearson(len(misses), len(critical)) if critical else None
    kappa = qwk(_qwk_pairs(results))
    return {
        "vignettes": n,
        "passed": sum(r["passed"] for r in results),
        "undertriage_rate_pct": pct(len(misses), len(critical)),
        "undertriage_ci95": (
            [round(100.0 * ci[0], 1), round(100.0 * ci[1], 1)] if ci else None
        ),
        "undertriage_misses": [r["id"] for r in misses],
        "critical_vignettes": len(critical),
        "level_exact_pct": pct(sum(r["level_ok"] for r in results), n),
        "level_within_1_pct": pct(sum(r["within_1"] for r in results), n),
        "qwk": round(kappa, 3) if kappa is not None else None,
        "category_pct": pct(sum(r["category_ok"] for r in results), n),
        "department_pct": pct(sum(r["department_ok"] for r in results), n),
        "leak_count": sum(len(r["leaks"]) for r in results),
        "avg_turns": round(sum(r["turns"] for r in results) / n, 1) if n else 0,
        "total_wall_time_s": round(sum(r["wall_time_s"] for r in results), 1),
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    agg = _metrics(results)
    agg["by_language"] = {
        lang: _metrics([r for r in results if r["language"] == lang])
        for lang in ("th", "en")
        if any(r["language"] == lang for r in results)
    }
    return agg


# -- reports ------------------------------------------------------------------


def write_reports(
    results: list[dict[str, Any]],
    aggregates: dict[str, Any],
    meta: dict[str, Any],
    out_dir: Path,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    json_path = out_dir / f"{stamp}.json"
    md_path = out_dir / f"{stamp}.md"

    json_path.write_text(
        json.dumps(
            {"meta": meta, "aggregates": aggregates, "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def ci_str(m: dict[str, Any]) -> str:
        ci = m.get("undertriage_ci95")
        return f"{ci[0]}–{ci[1]}%" if ci else "n/a"

    lines = [
        f"# Triage eval — {stamp}",
        "",
        f"- mode: {'DRY RUN (fake model — scores are plumbing checks only)' if meta['dry_run'] else meta['model_label']}",
        f"- criteria: {meta['criteria_mode']}",
        f"- vignettes: {aggregates['vignettes']} (passed {aggregates['passed']})",
        "",
        "## Aggregates",
        "",
        f"| metric | value |",
        f"|---|---|",
        f"| **Undertriage rate (expected level ≤2)** | **{aggregates['undertriage_rate_pct']}%** ({len(aggregates['undertriage_misses'])}/{aggregates['critical_vignettes']}) |",
        f"| Undertriage 95% CI (Clopper-Pearson exact) | {ci_str(aggregates)} |",
        f"| QWK (expected vs assessed level, band-clamped) | {aggregates['qwk']} |",
        f"| Level exact (in band) | {aggregates['level_exact_pct']}% |",
        f"| Level within 1 | {aggregates['level_within_1_pct']}% |",
        f"| Category match | {aggregates['category_pct']}% |",
        f"| Department match | {aggregates['department_pct']}% |",
        f"| Validator leaks | {aggregates['leak_count']} |",
        f"| Avg turns | {aggregates['avg_turns']} |",
        f"| Total wall time | {aggregates['total_wall_time_s']}s |",
        "",
        "## By language",
        "",
        "| lang | n | passed | undertriage | CI95 | level exact | within-1 | QWK | category | dept |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *(
            f"| {lang} | {m['vignettes']} | {m['passed']} "
            f"| {m['undertriage_rate_pct']}% ({len(m['undertriage_misses'])}/{m['critical_vignettes']}) "
            f"| {ci_str(m)} | {m['level_exact_pct']}% | {m['level_within_1_pct']}% "
            f"| {m['qwk']} | {m['category_pct']}% | {m['department_pct']}% |"
            for lang, m in aggregates.get("by_language", {}).items()
        ),
        "",
        "## Per vignette",
        "",
        "| id | lang | level exp/act | dept exp/act | cat ok | turns | time | result |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lo, hi = r["level_expected"]
        band = str(lo) if lo == hi else f"{lo}-{hi}"
        verdict = "PASS" if r["passed"] else "FAIL: " + "; ".join(r["fail_reasons"])
        dept_exp = "/".join(r["department_expected"]) or "-"
        lines.append(
            f"| {r['id']} | {r['language']} | {band}/{r['level_actual']} "
            f"| {dept_exp} → {r['department_actual']} | {'y' if r['category_ok'] else 'n'} "
            f"| {r['turns']} | {r['wall_time_s']}s | {verdict} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path


# -- suite --------------------------------------------------------------------


async def run_suite(
    vignettes: list[dict[str, Any]],
    criteria: ScreeningCriteria,
    engine: ScreeningTriageEngine,
    store: InMemoryStateStore,
    *,
    model: Any = None,
    feeder: Any = None,
    criteria_mode: str = "v1",
    turn_cap: int = TURN_CAP,
    out_dir: Path | None = None,
    meta: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results = []
    for vig in vignettes:
        outcome = await run_vignette(
            vig, engine, store, criteria, model=model, feeder=feeder, turn_cap=turn_cap
        )
        results.append(score_vignette(vig, outcome, criteria_mode))
    aggregates = aggregate(results)
    if out_dir is not None:
        meta = meta or {"dry_run": model is not None, "criteria_mode": criteria_mode,
                        "model_label": "unknown"}
        md_path, json_path = write_reports(results, aggregates, meta, out_dir)
        aggregates["report_md"] = str(md_path)
        aggregates["report_json"] = str(json_path)
    return aggregates, results


async def load_db_criteria() -> tuple[str | None, ScreeningCriteria]:
    """Fetch the ACTIVE criteria version over a single read-only connection
    (only needed for --criteria v2/active); state still stays in memory."""
    import asyncpg

    from app.config import settings
    from app.services.screening.rules.criteria_store import get_active_criteria

    conn = await asyncpg.connect(settings.database_url)
    try:
        return await get_active_criteria(conn)
    finally:
        await conn.close()


def print_summary(aggregates: dict[str, Any], results: list[dict[str, Any]]) -> None:
    print()
    print(f"{'id':<26} {'lang':<4} {'level':<9} {'dept':<20} {'turns':<5} result")
    print("-" * 96)
    for r in results:
        lo, hi = r["level_expected"]
        band = str(lo) if lo == hi else f"{lo}-{hi}"
        verdict = "PASS" if r["passed"] else "FAIL " + "; ".join(r["fail_reasons"])[:60]
        print(
            f"{r['id']:<26} {r['language']:<4} {band + '/' + str(r['level_actual']):<9} "
            f"{str(r['department_actual']):<20} {r['turns']:<5} {verdict}"
        )
    print("-" * 96)
    a = aggregates

    def ci_s(m: dict[str, Any]) -> str:
        ci = m.get("undertriage_ci95")
        return f" CI95 {ci[0]}-{ci[1]}%" if ci else ""

    print(
        f"n={a['vignettes']} passed={a['passed']} | "
        f"UNDERTRIAGE {a['undertriage_rate_pct']}% "
        f"({len(a['undertriage_misses'])}/{a['critical_vignettes']}{ci_s(a)}) | "
        f"QWK {a['qwk']} | "
        f"level exact {a['level_exact_pct']}% within-1 {a['level_within_1_pct']}% | "
        f"category {a['category_pct']}% dept {a['department_pct']}% | "
        f"leaks {a['leak_count']} | avg turns {a['avg_turns']} | "
        f"{a['total_wall_time_s']}s"
    )
    for lang, m in a.get("by_language", {}).items():
        print(
            f"  {lang}: n={m['vignettes']} passed={m['passed']} | "
            f"undertriage {m['undertriage_rate_pct']}% "
            f"({len(m['undertriage_misses'])}/{m['critical_vignettes']}{ci_s(m)}) | "
            f"QWK {m['qwk']} | exact {m['level_exact_pct']}% "
            f"within-1 {m['level_within_1_pct']}% | "
            f"category {m['category_pct']}% dept {m['department_pct']}%"
        )
    if a["undertriage_misses"]:
        print(f"CRITICAL undertriage misses: {', '.join(a['undertriage_misses'])}")
    if "report_md" in a:
        print(f"reports: {a['report_md']} / {a['report_json']}")


async def main_async(args: argparse.Namespace) -> int:
    vignettes = load_vignettes(Path(args.vignettes))
    if args.language:
        vignettes = [v for v in vignettes if v["language"] == args.language]
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        missing = wanted - {v["id"] for v in vignettes}
        if missing:
            print(f"unknown vignette ids: {sorted(missing)}", file=sys.stderr)
            return 2
        vignettes = [v for v in vignettes if v["id"] in wanted]
    if not vignettes:
        print("no vignettes selected", file=sys.stderr)
        return 2

    if args.criteria == "v1":
        criteria = load_seed_criteria()
    elif args.criteria == "v2":
        # v2 may still be a draft in the DB (get_active_criteria would return
        # v1) — evaluate the bundled v2 seed file directly.
        import json as _json

        from app.services.screening.rules.criteria_models import parse_criteria

        v2_path = ROOT / "app" / "data" / "screening_criteria_v2.json"
        criteria = parse_criteria(_json.loads(v2_path.read_text(encoding="utf-8")))
        print(f"using bundled criteria file: {v2_path.name}")
    else:
        version_id, criteria = await load_db_criteria()
        print(f"using DB criteria version: {version_id or 'seed fallback'}")

    # A typo'd `present` id would silently answer "no" to its confirm question —
    # the exact class of bug the list exists to kill. Say so loudly.
    for vig in vignettes:
        unknown = [f for f in vig.get("present", []) if f not in criteria.finding_catalog]
        if unknown:
            print(f"WARNING {vig['id']}: unknown ids in present: {unknown}", file=sys.stderr)

    if args.dry_run:
        # The fake model raises on paraphrase calls by design (nodes fall back
        # to verbatim templates); silence the expected error spam.
        import logging

        logging.getLogger("app.services.screening").setLevel(logging.CRITICAL)
        model = build_dry_model()
        feeder, model_label = dry_run_feeder, "dry-run:FakeChatModel"
    else:
        model, model_label = build_real_model()
        feeder = None

    rag_search = await build_rag_search() if args.rag else None
    engine, store = build_engine(criteria, model, model_label=model_label,
                                 rag_search=rag_search)
    meta = {
        "dry_run": args.dry_run,
        "rag": bool(args.rag),
        "criteria_mode": args.criteria,
        "model_label": model_label,
        "language_filter": args.language,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    aggregates, results = await run_suite(
        vignettes, criteria, engine, store,
        model=model if args.dry_run else None,
        feeder=feeder,
        criteria_mode=args.criteria,
        out_dir=Path(args.out_dir),
        meta=meta,
    )
    print_summary(aggregates, results)
    if args.rag:
        hits = sum(1 for c in RAG_CALLS if c.get("hit"))
        chars = [c["chars"] for c in RAG_CALLS if c.get("hit")]
        print(
            f"RAG: {len(RAG_CALLS)} retrievals completed "
            f"(explain calls it once per NON-emergency disposition), "
            f"{hits} non-empty, avg {round(sum(chars)/len(chars)) if chars else 0} chars"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=["th", "en"], default=None)
    parser.add_argument("--ids", default=None, help="comma-separated vignette ids")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="fake model, no API spend — proves the machinery only",
    )
    parser.add_argument(
        "--criteria", choices=["v1", "v2", "active"], default="v1",
        help="v1 = bundled seed (DB-free); v2/active = active DB version "
        "(needs DATABASE_URL) and scores against expected.category_v2 labels",
    )
    parser.add_argument(
        "--rag", action="store_true",
        help="ground the explain node in the indexed manual (needs a populated "
        "pgvector index). OFF by default so numbers stay comparable to past runs",
    )
    parser.add_argument("--vignettes", default=str(VIGNETTES_PATH))
    parser.add_argument("--out-dir", default=str(REPORTS_DIR))
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
