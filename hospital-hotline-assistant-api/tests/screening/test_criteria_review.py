"""Criteria version-review helpers (validation + diff) used by /admin/criteria/*."""

from __future__ import annotations

import copy
import json

import pytest

from app.services.screening.rules.criteria_store import (
    SEED_CRITERIA_PATH,
    diff_criteria,
    validation_errors,
)


@pytest.fixture()
def seed_payload() -> dict:
    with open(SEED_CRITERIA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


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
