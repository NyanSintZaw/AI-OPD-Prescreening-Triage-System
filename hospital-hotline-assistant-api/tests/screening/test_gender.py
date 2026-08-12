"""Gender end-to-end: HIS → state → question policy → rules → HIS write-back.

The safety contract under test everywhere here: gender may SKIP a question or
narrow a rule for a DEFINITE recorded value, but an unknown (or unexpected)
gender must behave as if every gender predicate matches — it can never
suppress a red flag or dodge a question.
"""

from types import SimpleNamespace

import httpx

from app.services.screening.engine import ScreeningTriageEngine
from app.services.screening.his import HttpHisAdapter, MockHisAdapter
from app.services.screening.his.http_adapter import _normalize_gender
from app.services.screening.rules.criteria_models import (
    CriterionCondition,
    DangerVitalRule,
)
from app.services.screening.rules.evaluator import evaluate_condition
from app.services.screening.rules.question_policy import (
    InterviewInputs,
    _is_resolved,
    get_template,
    next_question,
)
from app.services.screening.rules.red_flags import evaluate_red_flags
from app.services.screening.state import ScreeningState

from .fakes import FakeChatModel
from .test_engine import ext, make_engine


def _inputs(criteria=None, *, gender="unknown", **overrides):
    base = dict(
        complaint_category="abdominal_pain",
        findings={},
        answered_slots=frozenset(),
        asked_question_ids=frozenset(),
        age_known=True,
        age_years=30.0,
        measured_vitals=frozenset(),
        questions_asked=0,
        question_budget=8,
        ask_counts={},
        gender=gender,
    )
    base.update(overrides)
    return InterviewInputs(**base)


# ── condition AST: unknown/unexpected gender always matches ──────────────────

def _gendered_condition():
    return CriterionCondition(finding_id="vaginal_bleeding", gender="female")


def test_gender_predicate_matches_unknown_and_unexpected(criteria):
    cond = _gendered_condition()
    kwargs = dict(
        findings={"vaginal_bleeding": "present"},
        vitals={},
        age_years=30.0,
        age_bands=criteria.age_bands,
    )
    # No gender passed at all → default "unknown" → matches.
    assert evaluate_condition(cond, **kwargs) is True
    assert evaluate_condition(cond, **kwargs, gender="unknown") is True
    # An unexpected value outside the closed set must also match (fail-safe).
    assert evaluate_condition(cond, **kwargs, gender="nonbinary") is True
    assert evaluate_condition(cond, **kwargs, gender="") is True
    # Matching definite gender matches; only a definite mismatch excludes.
    assert evaluate_condition(cond, **kwargs, gender="female") is True
    assert evaluate_condition(cond, **kwargs, gender="male") is False


def test_level2_rule_with_gender_predicate_never_suppressed_by_unknown(criteria):
    """A level-2 rule carrying a gender predicate still fires for unknown AND
    unexpected gender values — undertriage by missing data is impossible."""
    rule = DangerVitalRule(
        id="test_gendered_l2",
        label_en="test", label_th="ทดสอบ",
        condition=_gendered_condition(),
        level=2,
    )
    patched = criteria.model_copy(update={"danger_vitals": [rule]})
    for gender in ("unknown", "nonbinary", "", "female"):
        hits = evaluate_red_flags(
            findings={"vaginal_bleeding": "present"},
            vitals={},
            age_years=30.0,
            criteria=patched,
            gender=gender,
        )
        assert any(h.rule_id == "test_gendered_l2" and h.level == 2 for h in hits), gender


# ── question policy: ask only when missing; skip only on definite match ──────

def test_gender_question_asked_only_when_unknown(criteria):
    # Unknown → uq_gender appears in the interview (after breathing, prio 3).
    q = next_question(criteria, _inputs(
        findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"},
    ))
    assert q is not None and q.id == "uq_gender"
    # Known (HIS or answered) → never asked.
    q = next_question(criteria, _inputs(
        gender="male",
        findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"},
    ))
    assert q is not None and q.id != "uq_gender"
    # Asked once and declined (still unknown) → not pressed a second time.
    q = next_question(criteria, _inputs(
        findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"},
        asked_question_ids=frozenset({"uq_gender"}),
        questions_asked=1,
        ask_counts={"uq_gender": 1},
    ))
    assert q is not None and q.id != "uq_gender"


def test_gender_question_offers_tappable_options(criteria):
    from app.services.screening.nodes.question import localize_options

    uq = next(q for q in criteria.universal_questions if q.id == "uq_gender")
    for language in ("en", "th"):
        chips = localize_options(uq, language, criteria)
        assert [c["id"] for c in chips] == ["male", "female", "decline"]


def test_pregnancy_question_skipped_only_for_recorded_male(criteria):
    ap = next(
        q for q in get_template(criteria, "abdominal_pain").questions
        if q.id == "ap_pregnancy"
    )
    assert ap.skip_for_gender == "male"
    # Recorded male → skip (efficiency).
    assert _is_resolved(ap, _inputs(gender="male")) is True
    # Unknown, unexpected, or female → still asked (safety).
    assert _is_resolved(ap, _inputs(gender="unknown")) is False
    assert _is_resolved(ap, _inputs(gender="nonbinary")) is False
    assert _is_resolved(ap, _inputs(gender="female")) is False


def test_no_level12_rule_carries_a_gender_predicate(criteria):
    """Guard the safety rule at the data level: escalating rules must not be
    gender-gated. (The evaluator would fail-safe on unknown anyway, but a
    definite recorded gender could still blind the rule — forbidden.)"""

    def genders(cond) -> list[str]:
        found = [cond.gender] if cond.gender is not None else []
        for child in [*cond.all_of, *cond.any_of]:
            found += genders(child)
        return found

    escalating = [
        *criteria.level1_criteria,
        *[r for r in criteria.danger_vitals if r.level <= 2],
        *[r for r in criteria.fast_tracks if r.level <= 2],
        *[r for r in criteria.department_rules if r.min_level <= 2],
    ]
    for rule in escalating:
        assert not genders(rule.condition), f"{rule.id} is gender-gated"


# ── engine: HIS gender → state, extraction fill-only ─────────────────────────

def test_turn_context_gender_reaches_state_before_rules(criteria):
    state = ScreeningState(session_id="g1")
    ScreeningTriageEngine._apply_turn_context(state, {"gender": "male"}, criteria)
    assert state.gender == "male"
    # Missing or unexpected context values never clobber a known gender.
    ScreeningTriageEngine._apply_turn_context(state, {"gender": None}, criteria)
    ScreeningTriageEngine._apply_turn_context(state, {"gender": "attack"}, criteria)
    ScreeningTriageEngine._apply_turn_context(state, {}, criteria)
    assert state.gender == "male"


async def test_engine_asks_gender_when_his_lacks_it_then_stores_answer(criteria):
    model = FakeChatModel()
    cleared = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
    }
    model.extractions.append(ext(
        chief_complaint="stomach ache", complaint_category="abdominal_pain",
        findings=cleared,
    ))
    engine = make_engine(criteria, model)

    first = await engine.run_turn(
        session_id="g2", language="en", input_mode="text",
        content="my stomach hurts",
        turn_context={"age_years": 30},  # HIS gave age but no gender
    )
    uq = next(q for q in criteria.universal_questions if q.id == "uq_gender")
    assert first["reply"] == uq.text_en
    assert [o["id"] for o in first["reply_options"]] == ["male", "female", "decline"]

    # Patient taps "Female" → stored; the gender question never returns.
    model.extractions.append(ext(gender="female"))
    await engine.run_turn(
        session_id="g2", language="en", input_mode="text", content="Female",
    )
    state = await engine._store.load("g2")
    assert state.gender == "female"
    assert state.asked_question_ids.count("uq_gender") == 1


async def test_engine_never_asks_gender_when_his_provided_it(criteria):
    model = FakeChatModel()
    model.extractions.append(ext(
        chief_complaint="stomach ache", complaint_category="abdominal_pain",
        findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"},
    ))
    engine = make_engine(criteria, model)
    first = await engine.run_turn(
        session_id="g3", language="en", input_mode="text",
        content="my stomach hurts",
        turn_context={"age_years": 30, "gender": "female"},
    )
    state = await engine._store.load("g3")
    assert state.gender == "female"
    assert "uq_gender" not in state.asked_question_ids
    uq = next(q for q in criteria.universal_questions if q.id == "uq_gender")
    assert first["reply"] != uq.text_en


def test_extracted_gender_fills_only_unknown(criteria):
    from app.services.screening.nodes.ingest import _apply

    state = ScreeningState(session_id="g4")
    _apply(state, criteria, ext(gender="male"), "ชายครับ")
    assert state.gender == "male"
    # A later contradictory utterance never flips an established value.
    _apply(state, criteria, ext(gender="female"), "หญิงค่ะ")
    assert state.gender == "male"


# ── HIS adapter: read, normalization, fill-only write-back ───────────────────

def _adapter(handler) -> HttpHisAdapter:
    transport = httpx.MockTransport(handler)
    return HttpHisAdapter(
        base_url="http://his",
        api_key="k",
        client=httpx.AsyncClient(transport=transport),
    )


def test_normalize_gender_spellings():
    assert _normalize_gender("male") == "male"
    assert _normalize_gender("M") == "male"
    assert _normalize_gender("ชาย") == "male"
    assert _normalize_gender("Female") == "female"
    assert _normalize_gender("หญิง") == "female"
    # Anything unrecognized maps to None (unknown) — never guessed.
    assert _normalize_gender("อื่นๆ") is None
    assert _normalize_gender("") is None
    assert _normalize_gender(None) is None


async def test_http_adapter_reads_gender_from_visit_lookup():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/visits/V9":
            return httpx.Response(200, json={
                "visit_id": "V9", "hn": "HN9", "birthdate": "1980-05-01",
                "active": True, "gender": "หญิง",
            })
        return httpx.Response(404)

    info = await _adapter(handler).validate_visit("V9")
    assert info is not None and info.gender == "female"


async def test_http_adapter_gender_missing_stays_none():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/visits/V9":
            return httpx.Response(200, json={
                "visit_id": "V9", "hn": "HN9", "active": True, "gender": None,
            })
        return httpx.Response(404)

    info = await _adapter(handler).validate_visit("V9")
    assert info is not None and info.gender is None


async def test_http_adapter_pushes_gender():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT" and request.url.path == "/api/v1/patients/HN9/gender":
            import json

            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"hn": "HN9", "written": True})
        return httpx.Response(404)

    assert await _adapter(handler).push_patient_gender("HN9", "female") is True
    assert seen == {"gender": "female"}
    # Failure path degrades to False, never raises.
    assert await _adapter(handler).push_patient_gender("NOPE", "female") is False


async def test_mock_adapter_pushes_gender():
    assert await MockHisAdapter().push_patient_gender("HN1", "male") is True


# ── TriageService write-back gating ──────────────────────────────────────────

class _RecordingAdapter:
    def __init__(self):
        self.pushed: list[tuple[str, str]] = []

    async def push_patient_gender(self, hn: str, gender: str) -> bool:
        self.pushed.append((hn, gender))
        return True


async def _run_push(metadata, gender):
    from app.services.triage_service import TriageService

    adapter = _RecordingAdapter()
    self = SimpleNamespace(his_adapter=adapter)
    await TriageService._maybe_push_gender(self, metadata=metadata, gender=gender)
    return adapter.pushed


async def test_service_pushes_booth_gender_when_his_lacked_it():
    metadata = {"visit": {"visit_id": "V1", "hn": "HN1", "gender": None}}
    assert await _run_push(metadata, "female") == [("HN1", "female")]
    # Success is remembered so later turns don't re-push.
    assert metadata["visit"]["gender"] == "female"
    assert await _run_push(metadata, "female") == []


async def test_service_never_pushes_over_his_recorded_gender():
    metadata = {"visit": {"visit_id": "V1", "hn": "HN1", "gender": "male"}}
    assert await _run_push(metadata, "female") == []
    assert metadata["visit"]["gender"] == "male"


async def test_service_skips_push_without_hn_or_definite_gender():
    assert await _run_push({"visit": {}}, "female") == []
    assert await _run_push({"visit": {"hn": "HN1"}}, "unknown") == []
    assert await _run_push({"visit": {"hn": "HN1"}}, None) == []
