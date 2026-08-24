"""Criteria-based end-to-end screening, offline and deterministic.

Drives authored vignettes (evals/vignettes.json) through the REAL engine —
graph, question policy, confirm-before-fire, measurements, rules, validator,
explain fallback — with `present_feeder` standing in for the extraction
model. Every scenario must (a) dispose to the expected level band and
department, (b) ask / never ask the named questions, (c) speak the expected
department name, (d) agree with the pure rules oracle on its own final
state, and (e) leak nothing. The live-Gemini counterpart is
``test_e2e_vignettes_live.py`` (integration-marked).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.services.screening.rules.criteria_store import load_seed_criteria

from .fakes import FakeChatModel

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "run_triage_eval", ROOT / "scripts" / "run_triage_eval.py"
)
assert _spec is not None and _spec.loader is not None
driver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(driver)

# The smoke set: every behaviour this plan added (ws_*) plus anchor cases
# across the level bands, both languages. Kept deterministic on purpose —
# the live run is where extraction quality is measured.
SMOKE_IDS = [
    # plan behaviours
    "ws_th_unwell_fever_no_selfharm", "ws_en_unwell_fever_no_selfharm",
    "ws_th_stress_asks_selfharm", "ws_en_stress_asks_selfharm",
    "ws_th_dyspnea_spo2_88", "ws_en_dyspnea_spo2_88",
    "ws_th_dyspnea_spo2_92_retraction", "ws_en_dyspnea_spo2_92_retraction",
    "ws_th_fever_no_spo2", "ws_en_fever_no_spo2",
    # anchors
    "cp_en_crushing", "cp_th_crushing", "dc_th_severe", "dc_en_child",
    "fv_th_mild", "fv_th_infant", "fv_en_child_ok", "mh_en_depression",
    "gen_en_overdose",
]


def _load():
    vignettes = driver.load_vignettes(ROOT / "evals" / "vignettes.json")
    by_id = {v["id"]: v for v in vignettes}
    missing = [i for i in SMOKE_IDS if i not in by_id]
    assert not missing, f"smoke ids missing from vignettes.json: {missing}"
    return [by_id[i] for i in SMOKE_IDS]


@pytest.fixture(scope="module")
def suite():
    import asyncio
    import logging

    # the fake model raises on render calls by design → verbatim templates
    logging.getLogger("app.services.screening").setLevel(logging.CRITICAL)
    criteria = load_seed_criteria()
    model = FakeChatModel()
    engine, store = driver.build_engine(
        criteria, model, model_label="e2e:fake+present_feeder"
    )
    aggregates, results = asyncio.run(driver.run_suite(
        _load(), criteria, engine, store, model=model, feeder=driver.present_feeder,
    ))
    return aggregates, {r["id"]: r for r in results}


def test_every_smoke_vignette_passes(suite):
    aggregates, results = suite
    failed = {i: r["fail_reasons"] for i, r in results.items() if not r["passed"]}
    assert not failed, failed
    assert aggregates["undertriage_misses"] == []
    assert aggregates["leak_count"] == 0


def test_engine_agrees_with_rules_oracle_everywhere_it_was_asked(suite):
    _, results = suite
    checked = [r for r in results.values() if r["oracle"] is not None]
    assert checked, "no vignette carried expected.oracle"
    assert all(r["oracle_ok"] for r in checked)


def test_self_harm_screen_only_where_it_belongs(suite):
    _, results = suite
    for vid in ("ws_th_unwell_fever_no_selfharm", "ws_en_unwell_fever_no_selfharm",
                "ws_th_fever_no_spo2", "ws_en_fever_no_spo2"):
        assert results[vid]["must_not_ask_hit"] == [], vid
    for vid in ("ws_th_stress_asks_selfharm", "ws_en_stress_asks_selfharm"):
        assert results[vid]["must_ask_missing"] == [], vid


def test_spo2_requested_for_dyspnea_and_drives_the_level(suite):
    _, results = suite
    for vid in ("ws_th_dyspnea_spo2_88", "ws_en_dyspnea_spo2_88"):
        r = results[vid]
        assert r["must_ask_missing"] == [] and r["level_actual"] == 1, vid
    for vid in ("ws_th_dyspnea_spo2_92_retraction", "ws_en_dyspnea_spo2_92_retraction"):
        assert results[vid]["level_actual"] == 2, vid


def test_patient_hears_the_right_department_name(suite):
    _, results = suite
    for vid in SMOKE_IDS:
        r = results[vid]
        assert not any("department name" in reason for reason in r["fail_reasons"]), (vid, r["fail_reasons"])
