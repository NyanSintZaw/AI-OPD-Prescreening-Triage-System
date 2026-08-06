"""The idempotency-key rule behind the double-booking fix.

`_push_his_routing` is fire-and-forget, so a timeout records `unknown` while
the hospital may already hold the queue row. What makes a nurse's re-confirm
safe is that it reuses the SAME request_id — the hospital then replays the
original result instead of queueing the patient twice. A genuine reroute must
NOT reuse it, or the hospital would dedupe away a real move.
"""
from app.routers.admin_reviews import _resolve_request_id


def test_no_prior_allocates_a_new_key():
    rid = _resolve_request_id(None, "opd_internal_medicine")
    assert rid.startswith("MFU-")
    assert len(rid.split("-")) == 3  # prefix + YYYYMMDD + sequence


def test_retry_to_the_same_department_reuses_the_key():
    prior = {"request_id": "MFU-20260807-ABC123", "department_code": "opd_general"}
    assert _resolve_request_id(prior, "opd_general") == "MFU-20260807-ABC123"


def test_reroute_to_a_different_department_allocates_a_new_key():
    prior = {"request_id": "MFU-20260807-ABC123", "department_code": "opd_general"}
    assert _resolve_request_id(prior, "opd_cardiology") != "MFU-20260807-ABC123"


def test_prior_without_a_key_allocates_one():
    """Older rows (and the `skipped` outcomes) carry no request_id."""
    prior = {"status": "skipped", "reason": "no_visit_link"}
    assert _resolve_request_id(prior, "opd_general").startswith("MFU-")


def test_keys_are_unique_per_allocation():
    codes = {_resolve_request_id(None, "opd_general") for _ in range(20)}
    assert len(codes) == 20
