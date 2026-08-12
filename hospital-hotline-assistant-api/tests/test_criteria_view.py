"""Nurse-readable criteria projection: condition rendering + GET /admin/criteria/active."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers.deps import get_current_admin_user
from app.database import get_connection
from app.services.criteria_view import build_criteria_view, render_condition
from app.services.screening.rules.criteria_store import SEED_CRITERIA_PATH

LABELS = {"fever": "Fever", "confusion": "Confusion", "stiff_neck": "Neck stiffness"}


@pytest.fixture()
def seed_payload() -> dict:
    return json.loads(SEED_CRITERIA_PATH.read_text(encoding="utf-8"))


# ── render_condition ─────────────────────────────────────────────────────────

def test_render_leaf_finding_uses_label():
    assert render_condition({"finding_id": "fever"}, LABELS) == "Fever"


def test_render_unknown_finding_falls_back_to_id():
    assert render_condition({"finding_id": "mystery"}, LABELS) == "mystery"


def test_render_nested_composite_parenthesizes_inner_group():
    condition = {
        "all_of": [
            {"finding_id": "fever"},
            {"any_of": [{"finding_id": "confusion"}, {"finding_id": "stiff_neck"}]},
        ]
    }
    assert render_condition(condition, LABELS) == "Fever AND (Confusion OR Neck stiffness)"


def test_render_thai_uses_thai_joiners():
    condition = {"any_of": [{"finding_id": "fever"}, {"finding_id": "confusion"}]}
    assert render_condition(condition, {}, "th") == "fever หรือ confusion"


def test_render_absent_state_is_negated():
    assert render_condition({"finding_id": "fever", "state": "absent"}, LABELS) == "NO Fever"


def test_render_vital_comparison_uses_symbols():
    # `le`/`ge` are the schema's operator names — they must not leak raw.
    assert render_condition({"vital": "sbp", "op": "le", "value": 90}) == "SBP ≤ 90"
    assert render_condition({"vital": "spo2", "op": "lt", "value": 92}) == "SpO₂ < 92"


def test_render_age_band_prefix():
    condition = {"finding_id": "fever", "age_band": "elderly"}
    assert render_condition(condition, LABELS) == "[elderly] Fever"


def test_render_garbage_is_not_an_exception():
    assert render_condition(None) == "—"
    assert render_condition({}) == "—"


# ── build_criteria_view ──────────────────────────────────────────────────────

def test_view_renders_every_rule_group_from_the_seed(seed_payload):
    view = build_criteria_view(seed_payload, {"version_no": 1})
    assert view["version_no"] == 1
    groups = {r["group"] for r in view["rules"]}
    assert {"level1", "danger_vital", "department_rule", "triage_tuple"} <= groups
    for rule in view["rules"]:
        assert rule["condition_en"] and rule["condition_en"] != "—"
        assert rule["condition_th"] and rule["condition_th"] != "—"
        assert "all_of" not in rule["condition_en"]  # no raw AST leaking through


def test_view_findings_are_sorted_and_complete(seed_payload):
    view = build_criteria_view(seed_payload)
    ids = [f["id"] for f in view["findings"]]
    assert ids == sorted(seed_payload["finding_catalog"])
    assert all(f["label_th"] for f in view["findings"])


def test_view_keeps_questions_in_authored_order(seed_payload):
    view = build_criteria_view(seed_payload)
    template = next(t for t in view["complaint_templates"] if t["questions"])
    source = next(
        t for t in seed_payload["complaint_templates"] if t["category"] == template["category"]
    )
    assert [q["id"] for q in template["questions"]] == [q["id"] for q in source["questions"]]


def test_view_flags_placeholder_citations():
    payload = {
        "finding_catalog": {"fever": {"label_en": "Fever", "label_th": "ไข้"}},
        "department_rules": [
            {
                "id": "r1", "label_en": "x", "label_th": "x", "department_code": "opd_ent",
                "min_level": 3, "condition": {"finding_id": "fever"},
                "citation": "MFU routing. ⚠️ PLACEHOLDER department pending confirmation.",
            },
            {
                "id": "r2", "label_en": "y", "label_th": "y", "department_code": "emergency",
                "min_level": 2, "condition": {"finding_id": "fever"},
                "citation": "MFU Triage — Level 2",
            },
        ],
    }
    by_id = {r["id"]: r for r in build_criteria_view(payload)["rules"]}
    assert by_id["r1"]["placeholder"] is True
    assert by_id["r2"]["placeholder"] is False


def test_view_renders_triage_tuple_findings_as_a_condition():
    payload = {
        "finding_catalog": {
            "chest_pain": {"label_en": "Chest pain", "label_th": "เจ็บหน้าอก"},
            "sweating": {"label_en": "Sweating", "label_th": "เหงื่อแตก"},
            "diabetes": {"label_en": "Diabetes", "label_th": "เบาหวาน"},
            "smoker": {"label_en": "Smoker", "label_th": "สูบบุหรี่"},
        },
        "triage_tuples": [
            {
                "id": "t1", "label_en": "ACS", "label_th": "ACS",
                "findings_all": ["chest_pain", "sweating"],
                "risk_factors_any": ["diabetes", "smoker"],
                "force_min_level": 2, "citation": "MFU Triage — Level 2",
            }
        ],
    }
    rule = build_criteria_view(payload)["rules"][0]
    assert rule["condition_en"] == "Chest pain AND Sweating AND (Diabetes OR Smoker)"
    assert rule["min_level"] == 2


def test_view_survives_an_invalid_document():
    # A draft with a dangling finding reference must still render, not 500.
    payload = {"finding_catalog": {}, "level1_criteria": [
        {"id": "l1", "label_en": "x", "label_th": "x", "condition": {"finding_id": "ghost"}}
    ]}
    assert build_criteria_view(payload)["rules"][0]["condition_en"] == "ghost"


# ── GET /admin/criteria/active ───────────────────────────────────────────────

class _FakeConn:
    def __init__(self, row):
        self._row = row

    async def fetchrow(self, *_args, **_kwargs):
        return self._row


@pytest.fixture()
def override_admin():
    app.dependency_overrides[get_current_admin_user] = lambda: {
        "id": "u1", "email": "n@x", "role": "nurse", "is_active": True
    }
    yield
    app.dependency_overrides.clear()


async def _get_active(row) -> dict:
    app.dependency_overrides[get_connection] = lambda: _FakeConn(row)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/admin/criteria/active")
    assert resp.status_code == 200
    return resp.json()


async def test_active_endpoint_returns_the_active_version(override_admin, seed_payload):
    from datetime import datetime
    from uuid import uuid4

    body = await _get_active({
        "id": uuid4(),
        "version_no": 7,
        "status": "active",
        "change_summary": "MFU manual v7",
        "activated_at": datetime(2026, 8, 1, 9, 0),
        "criteria": json.dumps(seed_payload),  # asyncpg hands JSONB back as str
    })
    assert body["version_no"] == 7
    assert body["status"] == "active"
    assert body["activated_at"].startswith("2026-08-01")
    assert body["findings"] and body["rules"] and body["complaint_templates"]
    assert "condition" not in body["rules"][0]  # AST stays server-side


async def test_active_endpoint_falls_back_to_the_seed(override_admin):
    body = await _get_active(None)
    assert body["status"] == "seed"
    assert body["version_no"] is None
    assert body["findings"]


async def test_active_endpoint_requires_a_token():
    app.dependency_overrides.clear()
    app.dependency_overrides[get_connection] = lambda: _FakeConn(None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            assert (await client.get("/admin/criteria/active")).status_code == 401
    finally:
        app.dependency_overrides.clear()
