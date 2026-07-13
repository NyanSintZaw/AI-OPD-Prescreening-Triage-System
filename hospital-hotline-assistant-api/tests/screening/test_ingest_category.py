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
