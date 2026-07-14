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
