"""Golden end-to-end transcripts (SRS acceptance scenarios).

Each test walks one complete patient journey through the engine — interview,
disposition, post-completion guidance — and runs the output
validator over EVERY patient-facing reply, proving no turn in either language
can leak the triage level/color, a diagnosis, or a prescription.
"""

import pytest

from app.services.screening import templates
from app.services.screening.engine import ScreeningTriageEngine
from app.services.screening.extraction import ExtractionResult, FindingUpdate
from app.services.screening.persistence import InMemoryStateStore
from app.services.screening.validator import validate_reply

from .fakes import FakeChatModel

VALIDATOR_DEPARTMENT_NAMES = {
    code: [names["en"], names["th"]]
    for code, names in templates.DEPARTMENT_NAMES.items()
}


def make_engine(criteria, model):
    return ScreeningTriageEngine(
        model=model,
        store=InMemoryStateStore(criteria),
        question_budget=8,
        model_label="screening:test",
    )


def ext(**kwargs):
    updates = [
        FindingUpdate(id=fid, state=state)
        for fid, state in kwargs.pop("findings", {}).items()
    ]
    return ExtractionResult(finding_updates=updates, **kwargs)


def assert_reply_safe(
    reply: str,
    language: str,
    *,
    department_code: str | None = None,
    is_emergency: bool = False,
) -> None:
    violations = validate_reply(
        reply,
        language=language,
        department_code=department_code,
        department_names=VALIDATOR_DEPARTMENT_NAMES if department_code else None,
        is_emergency=is_emergency,
    )
    assert violations == [], f"unsafe reply {violations}: {reply!r}"


class Journey:
    """Drives one session and validates every reply as it goes."""

    def __init__(self, criteria, language: str, session_id: str) -> None:
        self.model = FakeChatModel()
        self.engine = make_engine(criteria, self.model)
        self.language = language
        self.session_id = session_id
        self.replies: list[str] = []

    async def turn(
        self,
        text: str,
        extraction: ExtractionResult | None = None,
        **safety,
    ) -> dict:
        if extraction is not None:
            self.model.extractions.append(extraction)
        result = await self.engine.run_turn(
            session_id=self.session_id,
            language=self.language,
            input_mode="text",
            content=text,
        )
        self.replies.append(result["reply"])
        assert_reply_safe(result["reply"], self.language, **safety)
        return result


async def test_golden_en_cough_full_journey(criteria):
    """EN: cough → structured interview → opd_general → repeat guidance.
    Every reply validator-clean (no contact/phone step — booth-only)."""

    j = Journey(criteria, "en", "g1")

    r = await j.turn("I have a cough", ext(
        chief_complaint="cough", complaint_category="dyspnea_cough",
        findings={"cough": "present"},
    ))
    r = await j.turn("I'm 30", ext(age_years=30))
    r = await j.turn("no trouble breathing", ext(findings={
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
    }))
    r = await j.turn("I can speak normally", ext(findings={
        "severe_respiratory_distress": "absent", "blue_lips": "absent",
    }))
    r = await j.turn("no blood", ext(findings={"hemoptysis": "absent"}))
    r = await j.turn("no chest pain", ext(findings={"chest_pain": "absent"}))
    r = await j.turn("no fever", ext(findings={"fever": "absent", "high_fever": "absent"}))
    r = await j.turn("about a 2", ext(distress_score=2))
    r = await j.turn("3 days ago", ext(slot_updates={"onset": "3 days ago"}))

    classification = r["classification"]
    assert classification["classified"] is True
    assert classification["department_code"] == "opd_general"
    assert classification["disposition_reasons"], "nurse reasoning must be present"
    assert_reply_safe(r["reply"], "en", department_code="opd_general")

    # post-completion turn repeats guidance, never restarts the interview
    r = await j.turn("where do I go again?")
    assert "OPD General" in r["reply"]
    assert r["classification"] == {}

    # 9 interview/dispose turns + 1 repeat = 10 (no contact turns)
    assert len(j.replies) == 10


async def test_golden_th_chest_pain_emergency_journey(criteria):
    """TH: chest pain + sweating → emergency on turn 1, no interview loop →
    repeat guidance. Thai replies throughout."""

    j = Journey(criteria, "th", "g2")

    r = await j.turn(
        "เจ็บแน่นหน้าอก เหงื่อแตกเยอะมากค่ะ",
        ext(
            chief_complaint="เจ็บแน่นหน้าอก",
            complaint_category="chest_pain",
            findings={"chest_pain": "present", "diaphoresis": "present"},
        ),
        department_code="emergency",
        is_emergency=True,
    )
    classification = r["classification"]
    assert classification["classified"] is True
    assert classification["level"] <= 2
    assert classification["department_code"] == "emergency"
    # emergency decided on the very first turn — no interview questions
    assert len(j.replies) == 1

    # post-completion turn repeats guidance, never restarts the interview
    r = await j.turn("แล้วต้องไปไหนนะคะ")
    assert "ฉุกเฉิน" in r["reply"]
    assert r["classification"] == {}

    for reply in j.replies:
        assert "ระดับ" not in reply
        assert "สีแดง" not in reply


async def test_golden_en_ear_fails_ent_criteria_to_general(criteria):
    """EN: mild ear pain that meets NO ENT acceptance criterion falls back to
    opd_general (the manual's specialty-fail routing pattern)."""

    j = Journey(criteria, "en", "g3")

    r = await j.turn("my ear hurts a little", ext(
        chief_complaint="ear pain", complaint_category="ear",
        findings={"ear_pain": "present"}, age_years=30,
    ))
    answers = [
        ("no", ext(findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"})),
        ("no", ext(findings={"facial_droop": "absent"})),
        ("no", ext(findings={"foreign_body_ent_24h": "absent"})),
        ("about a 3", ext(pain_score=3, slot_updates={"severity": "3"})),
        ("yesterday", ext(slot_updates={"onset": "yesterday"})),
        ("one day", ext(slot_updates={"duration": "1 day"})),
        ("none of those", ext(findings={
            "hearing_loss": "absent", "ear_discharge": "absent",
            "tinnitus": "absent", "vertigo_positional": "absent",
        })),
    ]
    for text, extraction in answers:
        if r["classification"].get("classified"):
            break
        r = await j.turn(text, extraction)

    classification = r["classification"]
    assert classification["classified"] is True
    assert classification["department_code"] == "opd_general"
    assert classification["level"] in (4, 5)
    assert_reply_safe(r["reply"], "en", department_code="opd_general")


async def test_golden_en_child_routes_to_pediatrics(criteria):
    """EN: the same mild cough journey for an 8-year-old routes to
    opd_pediatrics (child<15 routing rule)."""

    j = Journey(criteria, "en", "g4")

    r = await j.turn("my son has a cough", ext(
        chief_complaint="cough", complaint_category="dyspnea_cough",
        findings={"cough": "present"},
    ))
    r = await j.turn("he is 8", ext(age_years=8))
    answers = [
        ext(findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"}),
        ext(findings={"severe_respiratory_distress": "absent", "blue_lips": "absent"}),
        ext(findings={"hemoptysis": "absent"}),
        ext(findings={"chest_pain": "absent"}),
        ext(findings={"fever": "absent", "high_fever": "absent"}),
        ext(distress_score=1),
        ext(slot_updates={"onset": "2 days ago"}),
        ext(slot_updates={"duration": "2 days"}),
    ]
    for extraction in answers:
        if r["classification"].get("classified"):
            break
        r = await j.turn("answer", extraction)

    classification = r["classification"]
    assert classification["classified"] is True
    assert classification["department_code"] == "opd_pediatrics"
    assert_reply_safe(r["reply"], "en", department_code="opd_pediatrics")
