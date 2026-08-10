"""A symptom the patient denied must not steer the interview.

Reported live 2026-08-10: "I have a fever but I don't have a headache" and
the booth went on asking headache questions.

The cause was in the keyword net that picks a complaint category when the
model returns none or "generic". It counted every keyword occurrence,
negated or not — so that sentence scored fever 1, headache 1, tied, and the
tie rule ("don't guess") left the category unresolved. Unresolved means the
generic question set, which re-asks broadly, which is exactly what the
patient experienced as being ignored.

Denied symptoms now score nothing. The tie disappears and fever wins.
"""

from __future__ import annotations

import pytest

from app.services.screening.nodes.ingest import _is_negated, _keyword_category
from app.services.screening.persistence import load_seed_criteria


@pytest.fixture(scope="module")
def criteria():
    return load_seed_criteria()


@pytest.mark.parametrize(
    "text,expected",
    [
        # The reported case, both languages and both phrasings.
        ("มีไข้ แต่ไม่ปวดหัว", "fever"),
        ("ผมมีไข้ครับ ไม่มีอาการปวดหัว", "fever"),
        ("I have a fever but I don't have a headache", "fever"),
        ("I have a fever but no headache", "fever"),
        # The mirror image: the denial must not swallow the real complaint
        # that follows it.
        ("ไม่มีไข้ แต่ปวดหัวมาก", "headache"),
        ("no fever but a bad headache", "headache"),
        ("ไม่ไอ แต่ปวดหัว", "headache"),
        # Denial trailing the real complaint.
        ("ปวดหัวมาก ไม่มีไข้", "headache"),
        ("I have a bad headache, no fever", "headache"),
        ("แน่นหน้าอก ไม่เหนื่อย", "chest_pain"),
        # Unchanged: plain statements still resolve.
        ("มีไข้มาสองวัน", "fever"),
        ("เจ็บแน่นหน้าอก", "chest_pain"),
        # Denying everything resolves nothing — the intake question fires.
        ("ไม่มีอาการอะไรเลย", None),
    ],
)
def test_category_ignores_denied_symptoms(criteria, text, expected):
    assert _keyword_category(text, criteria) == expected


@pytest.mark.parametrize(
    "text,keyword,negated",
    [
        ("ไม่มีอาการปวดหัว", "ปวดหัว", True),
        ("ไม่ปวดหัว", "ปวดหัว", True),
        ("ปวดหัว", "ปวดหัว", False),
        # A scope terminator ends the negation: the cough is denied, the
        # headache is not.
        ("ไม่ไอ แต่ปวดหัว", "ปวดหัว", False),
        ("no cough but headache", "headache", False),
        ("no headache", "headache", True),
        ("without headache", "headache", True),
        ("denies headache", "headache", True),
        # Too far away to be in scope — a cue in the previous clause must not
        # reach across a whole sentence.
        ("no fever at all yesterday and today a very bad headache", "headache", False),
    ],
)
def test_negation_scope(text, keyword, negated):
    assert _is_negated(text, text.lower().index(keyword)) is negated
