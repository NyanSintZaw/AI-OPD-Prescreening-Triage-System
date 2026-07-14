"""Unit tests for the criteria upload pipeline (pure parts + fake-model draft)."""

from __future__ import annotations

import copy
import json

import pytest

from app.services.screening.criteria_upload import (
    CHUNK_CHARS,
    CriteriaExtraction,
    ExtractedFinding,
    ExtractedRouting,
    ExtractedRule,
    ExtractedVitalCondition,
    _chunk,
    _rule_condition,
    diff_criteria,
    extract_criteria_draft,
    merge_extraction,
    validation_errors,
)
from app.services.screening.rules.criteria_store import SEED_CRITERIA_PATH


@pytest.fixture()
def seed_payload() -> dict:
    with open(SEED_CRITERIA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


# ── chunking ──────────────────────────────────────────────────────────────────

def test_chunk_empty_text():
    assert _chunk("   \n ") == []


def test_chunk_small_text_single_chunk():
    assert _chunk("hello world") == ["hello world"]


def test_chunk_large_text_overlaps():
    text = "x" * (CHUNK_CHARS + 500)
    chunks = _chunk(text)
    assert len(chunks) == 2
    assert chunks[0][-100:] == chunks[1][:100]  # overlap region shared


# ── condition conversion ──────────────────────────────────────────────────────

def test_rule_condition_findings_and_vitals():
    rule = ExtractedRule(
        id="r1", section="level1", label_en="e", label_th="t",
        findings_all=["chest_pain"],
        vitals_any=[ExtractedVitalCondition(vital="spo2", op="lt", value=90)],
    )
    condition = _rule_condition(rule)
    assert {"finding_id": "chest_pain"} in condition["all_of"]
    assert {"any_of": [{"vital": "spo2", "op": "lt", "value": 90.0}]} in condition["all_of"]


def test_rule_condition_unextractable_marker():
    rule = ExtractedRule(id="r_empty", section="level1", label_en="e", label_th="t")
    condition = _rule_condition(rule)
    assert condition == {"all_of": [{"finding_id": "__unextractable__"}]}


def test_rule_condition_age_band_guard():
    rule = ExtractedRule(
        id="r2", section="danger_vitals", label_en="e", label_th="t",
        vitals_all=[ExtractedVitalCondition(vital="hr", op="gt", value=180)],
        age_band="infant_1_12m",
    )
    assert _rule_condition(rule)["age_band"] == "infant_1_12m"


# ── merge ─────────────────────────────────────────────────────────────────────

def test_merge_new_level1_rule_stays_valid(seed_payload):
    extraction = CriteriaExtraction(
        findings=[ExtractedFinding(
            id="test_new_finding", label_en="New finding", label_th="อาการใหม่",
            synonyms_th=["อาการใหม่"],
        )],
        rules=[ExtractedRule(
            id="l1_test_new", section="level1", label_en="New L1", label_th="กฎใหม่",
            citation="p.99", findings_all=["test_new_finding"],
        )],
    )
    draft = merge_extraction(copy.deepcopy(seed_payload), extraction)
    assert "test_new_finding" in draft["finding_catalog"]
    assert any(r["id"] == "l1_test_new" for r in draft["level1_criteria"])
    assert validation_errors(draft) == []


def test_merge_upserts_existing_rule_by_id(seed_payload):
    draft = copy.deepcopy(seed_payload)
    existing_id = draft["level1_criteria"][0]["id"]
    count_before = len(draft["level1_criteria"])
    extraction = CriteriaExtraction(rules=[ExtractedRule(
        id=existing_id, section="level1", label_en="Replaced", label_th="แทนที่",
        findings_all=[next(iter(draft["finding_catalog"]))],
    )])
    draft = merge_extraction(draft, extraction)
    assert len(draft["level1_criteria"]) == count_before
    replaced = next(r for r in draft["level1_criteria"] if r["id"] == existing_id)
    assert replaced["label_en"] == "Replaced"


def test_merge_creates_placeholder_for_unknown_finding(seed_payload):
    extraction = CriteriaExtraction(rules=[ExtractedRule(
        id="l1_ghost", section="level1", label_en="Ghost", label_th="กฎ",
        findings_all=["never_seen_before"],
    )])
    draft = merge_extraction(copy.deepcopy(seed_payload), extraction)
    assert "never_seen_before" in draft["finding_catalog"]
    assert validation_errors(draft) == []


def test_merge_conditionless_rule_flags_unextractable(seed_payload):
    extraction = CriteriaExtraction(rules=[ExtractedRule(
        id="l1_no_condition", section="level1", label_en="Empty", label_th="ว่าง",
    )])
    draft = merge_extraction(copy.deepcopy(seed_payload), extraction)
    rule = next(r for r in draft["level1_criteria"] if r["id"] == "l1_no_condition")
    assert rule["condition"] == {"all_of": [{"finding_id": "__unextractable__"}]}
    assert "__unextractable__" in draft["finding_catalog"]
    assert validation_errors(draft) == []


def test_merge_routing_filters_unknown_acceptance_findings(seed_payload):
    known = next(iter(seed_payload["finding_catalog"]))
    extraction = CriteriaExtraction(routing=[ExtractedRouting(
        complaint_category="test_category", department_code="opd_general",
        acceptance_findings_any=[known, "totally_unknown_finding"],
    )])
    draft = merge_extraction(copy.deepcopy(seed_payload), extraction)
    entry = next(
        r for r in draft["routing_table"] if r["complaint_category"] == "test_category"
    )
    leaves = entry["specialty_conditions"][0]["any_of"]
    assert leaves == [{"finding_id": known}]
    assert validation_errors(draft) == []


def test_merge_department_rule_and_fast_track_defaults(seed_payload):
    extraction = CriteriaExtraction(rules=[
        ExtractedRule(
            id="dr_test", section="department_rule", label_en="d", label_th="d",
            findings_all=["some_finding"], department_code="opd_ent", level=2,
        ),
        ExtractedRule(
            id="ft_test", section="fast_track", label_en="f", label_th="f",
            findings_any=["some_finding"],
        ),
    ])
    draft = merge_extraction(copy.deepcopy(seed_payload), extraction)
    dept_rule = next(r for r in draft["department_rules"] if r["id"] == "dr_test")
    assert dept_rule["department_code"] == "opd_ent"
    assert dept_rule["min_level"] == 2
    fast_track = next(r for r in draft["fast_tracks"] if r["id"] == "ft_test")
    assert fast_track["department_code"] == "emergency"  # default destination
    assert validation_errors(draft) == []


# ── validation + diff ─────────────────────────────────────────────────────────

def test_validation_errors_clean_seed(seed_payload):
    assert validation_errors(seed_payload) == []


def test_validation_errors_broken_reference(seed_payload):
    broken = copy.deepcopy(seed_payload)
    broken["level1_criteria"][0]["condition"] = {"finding_id": "does_not_exist"}
    assert validation_errors(broken)


def test_diff_identical_is_empty(seed_payload):
    assert diff_criteria(seed_payload, copy.deepcopy(seed_payload)) == {}


def test_diff_reports_added_removed_changed(seed_payload):
    new = copy.deepcopy(seed_payload)
    removed_id = new["level1_criteria"].pop()["id"]
    new["danger_vitals"][0] = {**new["danger_vitals"][0], "label_en": "edited"}
    new["finding_catalog"]["brand_new"] = {
        "label_en": "x", "label_th": "x", "synonyms_en": [], "synonyms_th": [],
    }
    diff = diff_criteria(seed_payload, new)
    assert removed_id in diff["level1_criteria"]["removed"]
    assert new["danger_vitals"][0]["id"] in diff["danger_vitals"]["changed"]
    assert "brand_new" in diff["finding_catalog"]["added"]


# ── end-to-end draft with a fake model ────────────────────────────────────────

class _FakeStructured:
    def __init__(self, results):
        self._results = list(results)

    async def ainvoke(self, prompt):
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _FakeModel:
    def __init__(self, results):
        self._results = results

    def with_structured_output(self, schema):
        assert schema is CriteriaExtraction
        return _FakeStructured(self._results)


async def test_extract_criteria_draft_merges_and_validates(tmp_path, seed_payload):
    doc = tmp_path / "manual.txt"
    doc.write_text("ผู้ป่วยเจ็บแน่นหน้าอก ให้ส่งห้องฉุกเฉินทันที", encoding="utf-8")
    extraction = CriteriaExtraction(rules=[ExtractedRule(
        id="l1_from_upload", section="level1", label_en="Uploaded", label_th="กฎ",
        findings_all=["chest_pain"],
    )])
    draft, warnings = await extract_criteria_draft(
        file_path=doc,
        filename="manual.txt",
        model=_FakeModel([extraction]),
        base_payload=copy.deepcopy(seed_payload),
    )
    assert any(r["id"] == "l1_from_upload" for r in draft["level1_criteria"])
    assert warnings == []


async def test_extract_criteria_draft_records_chunk_failure(tmp_path, seed_payload):
    doc = tmp_path / "manual.txt"
    doc.write_text("some manual text", encoding="utf-8")
    draft, warnings = await extract_criteria_draft(
        file_path=doc,
        filename="manual.txt",
        model=_FakeModel([RuntimeError("model unavailable")]),
        base_payload=copy.deepcopy(seed_payload),
    )
    assert draft == seed_payload  # nothing merged
    assert len(warnings) == 1 and "failed" in warnings[0]


async def test_extract_criteria_draft_empty_document(tmp_path, seed_payload):
    doc = tmp_path / "empty.txt"
    doc.write_text("   ", encoding="utf-8")
    with pytest.raises(ValueError, match="no extractable text"):
        await extract_criteria_draft(
            file_path=doc,
            filename="empty.txt",
            model=_FakeModel([]),
            base_payload=seed_payload,
        )
