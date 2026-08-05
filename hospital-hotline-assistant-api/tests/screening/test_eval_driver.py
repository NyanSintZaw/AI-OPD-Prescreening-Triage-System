"""Unit tests for the triage eval driver (scripts/run_triage_eval.py).

Drives vignettes through the real engine with the tests' FakeChatModel —
no LLM calls, no DB — asserting the loop terminates, scores compute, the
undertriage flag fires on a synthetic miss, and report files are written.
"""

import importlib.util
import json
from pathlib import Path

from app.services.screening.extraction import ExtractionResult, FindingUpdate

from .fakes import FakeChatModel

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "run_triage_eval", ROOT / "scripts" / "run_triage_eval.py"
)
assert _spec is not None and _spec.loader is not None
driver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(driver)


EMERGENCY_VIG = {
    "id": "t_chest_emergency",
    "language": "en",
    "description": "scripted red flags -> emergency turn 1",
    "opening": "crushing chest pain and I'm sweating a lot",
    "age": 58,
    "answers": [],
    "expected": {
        "category": "chest_pain",
        "level": [1, 2],
        "department": "emergency",
        "undertriage_critical": True,
        "must_ask": [],
        "must_not_leak": True,
    },
}

# Expected critical, but the scripted extractions never surface a red flag —
# the engine interviews to budget exhaustion and disposes non-emergency.
MISS_VIG = {
    "id": "t_synthetic_miss",
    "language": "en",
    "description": "synthetic undertriage miss",
    "opening": "a little chest twinge",
    "age": 30,
    "answers": [],
    "measurements": {"bp": [118, 76], "weight": 70, "height": 172},
    "expected": {
        "category": "chest_pain",
        "level": [1, 2],
        "department": "emergency",
        "undertriage_critical": True,
        "must_ask": [],
        "must_not_leak": True,
    },
}


def feeder(turn_no: int, vig: dict, criteria) -> ExtractionResult:
    if turn_no == 1 and vig["id"] == "t_chest_emergency":
        return ExtractionResult(
            chief_complaint="crushing chest pain",
            complaint_category="chest_pain",
            finding_updates=[
                FindingUpdate(id="chest_pain", state="present"),
                FindingUpdate(id="diaphoresis", state="present"),
            ],
        )
    if turn_no == 1:
        return ExtractionResult(
            chief_complaint="chest twinge", complaint_category="chest_pain"
        )
    return ExtractionResult()


async def test_eval_driver_end_to_end(criteria, tmp_path):
    model = FakeChatModel()
    engine, store = driver.build_engine(criteria, model, question_budget=6)
    aggregates, results = await driver.run_suite(
        [EMERGENCY_VIG, MISS_VIG],
        criteria,
        engine,
        store,
        model=model,
        feeder=feeder,
        criteria_mode="v1",
        out_dir=tmp_path,
        meta={"dry_run": True, "criteria_mode": "v1", "model_label": "test"},
    )
    by_id = {r["id"]: r for r in results}

    hit = by_id["t_chest_emergency"]
    assert hit["passed"], hit["fail_reasons"]
    assert hit["level_actual"] is not None and hit["level_actual"] <= 2
    assert hit["department_actual"] == "emergency"
    assert not hit["undertriage_critical_fail"]
    assert hit["leaks"] == []
    assert hit["turns"] == 1  # emergency disposed on the very first turn

    miss = by_id["t_synthetic_miss"]
    assert not miss["passed"]
    assert miss["undertriage_critical_fail"]
    assert any("undertriage" in reason.lower() for reason in miss["fail_reasons"])
    assert miss["turns"] <= driver.TURN_CAP  # loop terminated
    assert miss["category_actual"] == "chest_pain"

    assert aggregates["vignettes"] == 2
    assert aggregates["critical_vignettes"] == 2
    assert aggregates["undertriage_rate_pct"] == 50.0
    assert aggregates["undertriage_misses"] == ["t_synthetic_miss"]
    assert aggregates["leak_count"] == 0
    # DECIDE-AI additions: QWK, exact CI, and per-language subgroup block.
    assert isinstance(aggregates["qwk"], float)
    lo, hi = aggregates["undertriage_ci95"]
    assert 0.0 <= lo <= 50.0 <= hi <= 100.0
    assert set(aggregates["by_language"]) == {"en"}  # both vignettes are en
    en = aggregates["by_language"]["en"]
    assert en["vignettes"] == 2
    assert en["undertriage_rate_pct"] == 50.0
    assert en["qwk"] == aggregates["qwk"]

    md_files = list(tmp_path.glob("*.md"))
    json_files = list(tmp_path.glob("*.json"))
    assert len(md_files) == 1 and len(json_files) == 1
    payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert payload["aggregates"]["vignettes"] == 2
    assert {r["id"] for r in payload["results"]} == {
        "t_chest_emergency", "t_synthetic_miss",
    }
    md_text = md_files[0].read_text(encoding="utf-8")
    assert "Undertriage" in md_text
    assert "QWK" in md_text and "By language" in md_text
    assert payload["aggregates"]["by_language"]["en"]["vignettes"] == 2


def test_qwk_perfect_agreement():
    assert driver.qwk([(1, 1), (2, 2), (3, 3), (5, 5)]) == 1.0
    assert driver.qwk([(2, 2), (2, 2)]) == 1.0  # degenerate single class
    assert driver.qwk([]) is None


def test_qwk_hand_computed():
    # pairs (1,1),(1,2),(2,2),(3,4): sum w*O = 2/(16*4), sum w*E = 2.125/16
    # kappa = 1 - 0.5/2.125 = 0.7647058823...
    val = driver.qwk([(1, 1), (1, 2), (2, 2), (3, 4)])
    assert abs(val - (1.0 - 0.5 / 2.125)) < 1e-9


def test_qwk_band_clamp_convention():
    # in-band actual scores as perfect; out-of-band clamps to nearest edge
    results = [
        {"level_actual": 2, "level_expected": [1, 2]},   # in band -> (2, 2)
        {"level_actual": 4, "level_expected": [1, 2]},   # below band -> (2, 4)
        {"level_actual": None, "level_expected": [1, 2]},  # unclassified: dropped
    ]
    assert driver._qwk_pairs(results) == [(2, 2), (2, 4)]


def test_clopper_pearson_known_values():
    # BIZUSIZO template: 4/120 -> 0.9%..8.3%
    lo, hi = driver.clopper_pearson(4, 120)
    assert abs(lo - 0.009) < 0.002 and abs(hi - 0.083) < 0.002
    # zero numerator: lower bound exactly 0, upper 1-(alpha/2)^(1/n) ~ 0.185
    lo0, hi0 = driver.clopper_pearson(0, 18)
    assert lo0 == 0.0 and abs(hi0 - 0.185) < 0.002
    # k == n: upper bound exactly 1
    lon, hin = driver.clopper_pearson(18, 18)
    assert hin == 1.0 and abs(lon - 0.815) < 0.002
    assert driver.clopper_pearson(0, 0) == (0.0, 1.0)


async def test_dry_run_feeder_terminates_and_scores(criteria, tmp_path):
    """The CLI's own dry-run feeder (category seed + empty extractions) must
    terminate within the cap and produce a scoreable result."""
    model = FakeChatModel()
    engine, store = driver.build_engine(criteria, model, question_budget=6)
    vig = {
        "id": "t_dry_mild",
        "language": "en",
        "opening": "I have a cough",
        "age": 30,
        "answers": [],
        "expected": {
            "category": "dyspnea_cough",
            "level": [4, 5],
            "department": "opd_general",
            "undertriage_critical": False,
            "must_ask": [],
            "must_not_leak": True,
        },
    }
    outcome = await driver.run_vignette(
        vig, engine, store, criteria, model=model, feeder=driver.dry_run_feeder
    )
    assert outcome["turns"] <= driver.TURN_CAP
    assert outcome["classification"].get("classified") is True
    scored = driver.score_vignette(vig, outcome, "v1")
    assert scored["category_ok"]
    assert isinstance(scored["level_actual"], int)
    assert scored["leaks"] == []


def test_vignettes_file_valid(criteria):
    vignettes = driver.load_vignettes()
    assert len(vignettes) >= 60
    ids = [v["id"] for v in vignettes]
    assert len(ids) == len(set(ids)), "duplicate vignette ids"
    valid_categories = {t.category for t in criteria.complaint_templates}
    for vig in vignettes:
        assert vig["language"] in ("th", "en"), vig["id"]
        assert vig["opening"].strip(), vig["id"]
        expected = vig["expected"]
        for cat in driver._as_list(expected["category"]):
            assert cat in valid_categories, (vig["id"], cat)
        lo, hi = driver.level_band(expected["level"])
        assert 1 <= lo <= hi <= 5, vig["id"]
        assert expected.get("must_not_leak") is True, vig["id"]
        if expected.get("undertriage_critical"):
            assert hi <= 2, f"{vig['id']}: undertriage_critical but band max > 2"
