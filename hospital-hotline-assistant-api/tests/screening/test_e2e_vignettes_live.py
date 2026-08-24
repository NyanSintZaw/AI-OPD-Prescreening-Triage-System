"""Criteria-based end-to-end screening against the REAL model (integration).

Same smoke vignettes as ``test_e2e_vignettes.py`` but with Gemini doing the
extraction and rendering, so this measures what the offline suite cannot:
free-text extraction, confirm-before-fire on real answers, and the validated
wording. Skips (does not fail) when no model credentials are configured.
Writes a report to evals/reports/ — the only place triage-quality claims may
come from (CLAUDE.md).

    uv run pytest tests/screening/test_e2e_vignettes_live.py -m integration -s
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.config import settings
from app.services.screening.rules.criteria_store import load_seed_criteria

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "run_triage_eval", ROOT / "scripts" / "run_triage_eval.py"
)
assert _spec is not None and _spec.loader is not None
driver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(driver)

SMOKE_IDS = [
    "ws_th_unwell_fever_no_selfharm", "ws_en_unwell_fever_no_selfharm",
    "ws_th_stress_asks_selfharm", "ws_en_stress_asks_selfharm",
    "ws_th_dyspnea_spo2_88", "ws_en_dyspnea_spo2_88",
    "ws_th_fever_no_spo2", "ws_en_fever_no_spo2",
    "cp_th_crushing", "cp_en_crushing", "dc_th_severe", "fv_en_child_ok",
]


def _model_available() -> bool:
    if settings.screening_model_provider == "openai_compatible":
        return True
    if not getattr(settings, "google_ai_enabled", False):
        return False
    try:
        import google.auth  # noqa: F401

        google.auth.default()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def live_suite():
    if not _model_available():
        pytest.skip("no screening model credentials configured (GOOGLE_AI_ENABLED / ADC)")
    import asyncio

    criteria = load_seed_criteria()
    model, label = driver.build_real_model()
    engine, store = driver.build_engine(criteria, model, model_label=label)
    vignettes = {v["id"]: v for v in driver.load_vignettes(ROOT / "evals" / "vignettes.json")}
    selected = [vignettes[i] for i in SMOKE_IDS]
    meta = {
        "dry_run": False, "rag": False, "criteria_mode": "seed", "model_label": label,
        "language_filter": None, "suite": "test_e2e_vignettes_live smoke",
    }
    aggregates, results = asyncio.run(driver.run_suite(
        selected, criteria, engine, store, out_dir=ROOT / "evals" / "reports", meta=meta,
    ))
    print(f"\nlive smoke report: {aggregates.get('report_md')}")
    return aggregates, {r["id"]: r for r in results}


def test_no_critical_undertriage(live_suite):
    aggregates, _ = live_suite
    assert aggregates["undertriage_misses"] == [], aggregates["undertriage_misses"]


def test_no_validator_leaks(live_suite):
    aggregates, _ = live_suite
    assert aggregates["leak_count"] == 0


def test_levels_within_one_band(live_suite):
    aggregates, _ = live_suite
    assert aggregates["level_within_1_pct"] == 100.0


def test_self_harm_screen_never_asked_on_fever(live_suite):
    _, results = live_suite
    for vid in ("ws_th_unwell_fever_no_selfharm", "ws_en_unwell_fever_no_selfharm",
                "ws_th_fever_no_spo2", "ws_en_fever_no_spo2"):
        assert results[vid]["must_not_ask_hit"] == [], (vid, results[vid]["fail_reasons"])


def test_spo2_requested_on_dyspnea(live_suite):
    _, results = live_suite
    for vid in ("ws_th_dyspnea_spo2_88", "ws_en_dyspnea_spo2_88"):
        assert results[vid]["must_ask_missing"] == [], (vid, results[vid]["fail_reasons"])
