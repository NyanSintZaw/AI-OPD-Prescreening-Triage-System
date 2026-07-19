"""Complaint-category normalization in the ingest node.

The model must copy a category id verbatim, but real models merge ids
(gemini-3.1-flash-lite returns 'ear_nose_throat' for sore throat + cough).
_closest_category deterministically maps a near-miss to the unique known id
with the highest token overlap, and refuses to guess on ties.
"""

from __future__ import annotations

from app.services.screening.nodes.ingest import _closest_category

KNOWN = {
    "generic", "chest_pain", "dyspnea_cough", "abdominal_pain", "headache",
    "fever", "ear", "nose_throat", "eye", "injury", "pregnancy",
    "mental_health", "musculoskeletal", "urinary",
}


def test_merged_id_maps_to_best_overlap():
    # {ear, nose, throat}: nose_throat overlaps 2 tokens, ear only 1.
    assert _closest_category("ear_nose_throat", KNOWN) == "nose_throat"


def test_exact_tokens_and_hyphens():
    assert _closest_category("nose-throat", KNOWN) == "nose_throat"
    assert _closest_category("CHEST_PAIN", KNOWN) == "chest_pain"


def test_ambiguous_overlap_is_rejected():
    # "pain" overlaps chest_pain and abdominal_pain equally — don't guess.
    assert _closest_category("pain", KNOWN) is None


def test_no_overlap_is_rejected():
    assert _closest_category("dermatology", KNOWN) is None


def test_strip_ambiguous_affirmation():
    """A bare Yes to a compound red flag must not record its findings —
    models mark them ALL present, which both pollutes the nurse record and
    (before the fix) silently skipped the clarifying re-ask."""
    from types import SimpleNamespace

    from app.services.screening.extraction import ExtractionResult, FindingUpdate
    from app.services.screening.nodes.ingest import strip_ambiguous_affirmation

    pending = SimpleNamespace(
        kind="red_flag", id="fv_danger",
        finding_ids=["confusion", "dyspnea", "stiff_neck"],
    )

    def result_with_all():
        return ExtractionResult(finding_updates=[
            FindingUpdate(id="confusion", state="present"),
            FindingUpdate(id="dyspnea", state="present"),
            FindingUpdate(id="stiff_neck", state="present"),
            FindingUpdate(id="fever", state="present"),  # unrelated: kept
        ])

    # bare yes (en + th) -> the question's findings dropped, others kept
    for text in ("Yes", "ใช่ค่ะ", "yes!"):
        r = result_with_all()
        strip_ambiguous_affirmation(r, pending, text)
        assert [u.id for u in r.finding_updates] == ["fever"], text

    # a specific answer keeps everything
    r = result_with_all()
    strip_ambiguous_affirmation(r, pending, "Yes, my neck is stiff and I'm confused")
    assert len(r.finding_updates) == 4

    # denials untouched (extraction's absent updates must survive)
    r = ExtractionResult(finding_updates=[
        FindingUpdate(id="confusion", state="absent"),
        FindingUpdate(id="dyspnea", state="absent"),
        FindingUpdate(id="stiff_neck", state="absent"),
    ])
    strip_ambiguous_affirmation(r, pending, "None of these")
    assert len(r.finding_updates) == 3

    # single-finding and uq_breathing questions are exempt
    single = SimpleNamespace(kind="red_flag", id="fv_chemo", finding_ids=["recent_chemotherapy"])
    r = ExtractionResult(finding_updates=[FindingUpdate(id="recent_chemotherapy", state="present")])
    strip_ambiguous_affirmation(r, single, "Yes")
    assert len(r.finding_updates) == 1


def _pending(qid, finding_ids, kind="associated"):
    from types import SimpleNamespace
    return SimpleNamespace(kind=kind, id=qid, finding_ids=finding_ids)


def test_bare_denial_only_answers_the_pending_question():
    """Observed live (S3-en): "No" to the fever-associated question flipped
    fever — established on turn 1 with 37.9 °C measured — to absent, dropping
    the triage level from 4 to 5."""
    from app.services.screening.extraction import ExtractionResult, FindingUpdate
    from app.services.screening.nodes.ingest import strip_unscoped_denial

    pending = _pending("fv_associated", ["cough", "sore_throat", "runny_nose"])
    for text in ("No", "ไม่ใช่", "No, none of those", "ไม่มีอาการอื่นเลย",
                 "no other symptoms", "ไม่มีอาการเหล่านี้"):
        r = ExtractionResult(finding_updates=[
            FindingUpdate(id="cough", state="absent"),
            FindingUpdate(id="fever", state="absent"),      # out of scope: dropped
            FindingUpdate(id="dyspnea", state="absent"),    # out of scope: dropped
        ])
        strip_unscoped_denial(r, pending, text)
        assert [u.id for u in r.finding_updates] == ["cough"], text

    # a substantive denial sentence passes through untouched
    r = ExtractionResult(finding_updates=[
        FindingUpdate(id="cough", state="absent"),
        FindingUpdate(id="fever", state="absent"),
    ])
    strip_unscoped_denial(r, pending, "no cough, and the fever is gone too")
    assert len(r.finding_updates) == 2

    # no pending question -> volunteered negations are kept
    r = ExtractionResult(finding_updates=[FindingUpdate(id="fever", state="absent")])
    strip_unscoped_denial(r, None, "No")
    assert len(r.finding_updates) == 1


def test_bare_uncertainty_records_nothing():
    """Observed live (S7-th): "ไม่แน่ใจเลยครับ" was extracted as all three
    GI-bleed red flags absent; EN "not sure" correctly stayed unknown."""
    from app.services.screening.extraction import ExtractionResult, FindingUpdate
    from app.services.screening.nodes.ingest import strip_uncertain_answer

    for text in ("ไม่แน่ใจเลยครับ", "ไม่แน่ใจค่ะ", "maybe? I'm not sure honestly",
                 "not sure", "I don't know", "ไม่ทราบครับ", "อาจจะ ไม่แน่ใจนะคะ"):
        r = ExtractionResult(
            finding_updates=[FindingUpdate(id="hematemesis", state="absent")],
            slot_updates={"onset": "maybe"},
        )
        strip_uncertain_answer(r, text)
        assert r.finding_updates == [] and r.slot_updates == {}, text

    # real content containing "not sure" is untouched
    r = ExtractionResult(finding_updates=[FindingUpdate(id="melena", state="present")])
    strip_uncertain_answer(r, "I'm not sure about the stool but I did vomit blood")
    assert len(r.finding_updates) == 1


def test_keyword_category_fallback():
    """Observed live (S4-en): "kinda dizzy, the room was spining" went to
    generic — skipping the BEFAST stroke screen the Thai run got."""
    from app.services.screening.nodes.ingest import _keyword_category
    from app.services.screening.rules.criteria_store import load_seed_criteria

    criteria = load_seed_criteria()
    en = "so i was at a party yesterday and i started feelin kinda dizzy, the room was spining. im 68"
    assert _keyword_category(en, criteria) == "headache"
    assert _keyword_category("เมื่อวานรู้สึกเวียนหัวมากเลยค่ะ", criteria) == "headache"
    # เวียนหัว (headache) + บ้านหมุน (ear/vertigo) tie -> refuse to guess
    assert _keyword_category("เวียนหัว บ้านหมุนๆ ค่ะ", criteria) is None
    # no keyword match -> stays unresolved (rash has no category in v1)
    assert _keyword_category("i have a rash on my arm", criteria) is None
    # short denial answers never re-categorize
    assert _keyword_category("No, none of those", criteria) is None


def test_measured_temperature_outranks_extraction():
    """A booth thermometer reading ≥37.8 sets fever present and blocks a
    later chat denial from flipping it (observed live: fever absent with
    temp 37.9 recorded)."""
    from app.services.screening.extraction import ExtractionResult, FindingUpdate
    from app.services.screening.nodes.ingest import _apply
    from app.services.screening.rules.criteria_store import load_seed_criteria
    from app.services.screening.state import ScreeningState
    from app.services.screening.vitals import apply_objective_findings

    criteria = load_seed_criteria()
    state = ScreeningState(session_id="t", language="en", mode="text")
    state.vitals["temp"] = 37.9
    apply_objective_findings(state)
    assert state.findings["fever"].state == "present"

    _apply(state, criteria, ExtractionResult(finding_updates=[
        FindingUpdate(id="fever", state="absent"),
        FindingUpdate(id="cough", state="absent"),
    ]), "no fever, no cough")
    assert state.findings["fever"].state == "present"   # blocked
    assert state.findings["cough"].state == "absent"    # unrelated: applied

    # below threshold the patient's denial stands
    state2 = ScreeningState(session_id="t2", language="en", mode="text")
    state2.vitals["temp"] = 36.9
    apply_objective_findings(state2)
    assert "fever" not in state2.findings
