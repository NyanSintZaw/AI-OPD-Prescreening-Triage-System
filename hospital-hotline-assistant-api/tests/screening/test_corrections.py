"""Mid-interview corrections — the patient restates, retracts or adds.

The engine is a belief state: every turn re-extracts and the rules re-decide.
These tests pin what must MOVE when the patient corrects themself (category,
chief complaint, severity, a retracted critical finding) and what must NOT
(a disposition already made, a device reading). The scripted extractions are
what Gemini returned live on 2026-08-22 for the same utterances
(docs/ai-quality-evaluation.md); here the fake model replays them so the
rules are tested in isolation.
"""

from app.services.screening import templates
from app.services.screening.extraction import ExtractionResult
from app.services.screening.nodes.ingest import _apply
from app.services.screening.rules.question_policy import (
    next_question,
    red_flags_resolved,
)
from app.services.screening.state import Finding, ScreeningState

from .test_golden_transcripts import Journey, ext
from .test_question_policy import inputs

# ---------------------------------------------------------------- _apply unit


def _state(category="abdominal_pain", chief="ปวดท้อง", **findings):
    state = ScreeningState(session_id="s", complaint_category=category, chief_complaint=chief)
    for fid, spec in findings.items():
        st, confirmed = (spec, False) if isinstance(spec, str) else spec
        state.findings[fid] = Finding(state=st, confirmed=confirmed)
    return state


def test_category_switches_when_its_anchor_is_retracted(criteria):
    """Probe A: "พูดผิด ไม่ได้ปวดท้อง แต่เจ็บแน่นหน้าอก" — the old finding
    goes absent, the new one present, the chief complaint is restated."""
    state = _state(abdominal_pain="present")
    _apply(state, criteria, ext(
        chief_complaint="เจ็บแน่นหน้าอก", complaint_category="chest_pain",
        findings={"abdominal_pain": "absent", "chest_pain": "present"},
    ))
    assert state.complaint_category == "chest_pain"
    assert state.chief_complaint == "เจ็บแน่นหน้าอก"
    assert state.complaint_history == [
        {"turn": 0, "category": "abdominal_pain", "chief_complaint": "ปวดท้อง"}
    ]


def test_category_switches_on_restated_complaint_with_new_anchor_present(criteria):
    """Probe H: "ปวดหัวคือเมื่ออาทิตย์ก่อน หายแล้ว วันนี้มาเรื่องผื่น" — the model
    may leave the old finding untouched; a restated chief complaint whose own
    finding is present still moves the interview."""
    state = _state(category="headache", chief="ปวดหัว", headache="present")
    _apply(state, criteria, ext(
        chief_complaint="ผื่นคันที่แขน", complaint_category="skin_rash",
        findings={"rash_itching": "present"},
    ))
    assert state.complaint_category == "skin_rash"
    assert state.chief_complaint == "ผื่นคันที่แขน"


def test_added_symptom_without_restatement_keeps_the_category(criteria):
    """Probe F: fever patient adds chest pain — no chief-complaint restatement,
    so the template stays fever (the chest red flags join via the policy)."""
    state = _state(category="fever", chief="มีไข้", fever="present")
    _apply(state, criteria, ext(
        complaint_category="chest_pain", findings={"chest_pain": "present"},
    ))
    assert state.complaint_category == "fever"
    assert state.chief_complaint == "มีไข้"
    assert state.complaint_history == []


def test_model_category_pick_alone_never_moves_a_specific_category(criteria):
    """The model re-picks a category every turn; without evidence (anchor
    retracted, or restated complaint + new anchor present) it is ignored."""
    state = _state(category="fever", chief="มีไข้", fever="present")
    _apply(state, criteria, ext(chief_complaint="ไอ", complaint_category="dyspnea_cough"))
    assert state.complaint_category == "fever"
    _apply(state, criteria, ext(complaint_category="generic"))
    assert state.complaint_category == "fever"


def test_chief_complaint_refreshes_when_anchor_retracted_without_new_category(criteria):
    state = _state(abdominal_pain="present")
    _apply(state, criteria, ext(
        chief_complaint="จุกแน่นลิ้นปี่", complaint_category="abdominal_pain",
        findings={"abdominal_pain": "absent"},
    ))
    assert state.complaint_category == "abdominal_pain"
    assert state.chief_complaint == "จุกแน่นลิ้นปี่"
    assert state.complaint_history[0]["chief_complaint"] == "ปวดท้อง"


def test_severity_slot_follows_a_corrected_score(criteria):
    """Probe D: "it's like a 7" then "I meant 4" — the slot text the nurse
    summary shows must follow the number, not keep the first answer."""
    state = _state(abdominal_pain="present")
    _apply(state, criteria, ext(pain_score=7, slot_updates={"severity": "it's like a 7"}))
    assert state.slots["severity"] == "7"
    _apply(state, criteria, ext(pain_score=4, slot_updates={"character": "dull ache"}))
    assert state.vitals["pain_score"] == 4
    assert state.slots["severity"] == "4"


def test_retracting_a_confirmed_critical_finding_is_flagged_for_confirm(criteria):
    state = _state(category="chest_pain", chief="แน่นหน้าอก",
                   chest_pain=("present", True), diaphoresis=("present", True))
    _apply(state, criteria, ext(findings={"diaphoresis": "absent"}))
    assert state.pending_retraction == ["diaphoresis"]
    assert state.findings["diaphoresis"].state == "absent"
    assert state.findings["diaphoresis"].confirmed is False


def test_retraction_not_flagged_for_unconfirmed_or_answered_findings(criteria):
    # unconfirmed (free-text) present → absent: just a correction, no confirm
    state = _state(category="chest_pain", chief="แน่นหน้าอก", diaphoresis="present")
    _apply(state, criteria, ext(findings={"diaphoresis": "absent"}))
    assert state.pending_retraction == []
    # answering the finding's own confirm question with "no" IS the confirm
    state = _state(category="chest_pain", chief="แน่นหน้าอก", diaphoresis=("present", True))
    state.pending_question_id = "confirm_diaphoresis"
    _apply(state, criteria, ext(findings={"diaphoresis": "absent"}))
    assert state.pending_retraction == []
    assert state.findings["diaphoresis"].confirmed is True


# ------------------------------------------------------------ policy unit


def test_second_complaint_red_flags_join_after_the_templates_own(criteria):
    fever_only = inputs(
        category="fever",
        findings={"fever": "present", "dyspnea": "absent",
                  "severe_respiratory_distress": "absent",
                  "confusion": "absent", "stiff_neck": "absent",
                  "recent_chemotherapy": "absent",
                  "rash_vesicles": "absent", "palm_sole_rash": "absent"},
        asked=("fv_danger", "fv_chemo", "fv_rash"),
        measured_vitals=("temp", "sbp"),
    )
    assert red_flags_resolved(criteria, fever_only)
    with_chest = inputs(
        category="fever",
        findings={**fever_only.findings, "chest_pain": "present"},
        asked=("fv_danger", "fv_chemo", "fv_rash"),
        measured_vitals=("temp", "sbp"),
    )
    assert not red_flags_resolved(criteria, with_chest)
    asked = []
    nxt = next_question(criteria, with_chest)
    while nxt is not None and nxt.kind == "red_flag":
        asked.append(nxt.id)
        with_chest = inputs(
            category="fever", findings=with_chest.findings,
            asked=("fv_danger", "fv_chemo", "fv_rash", *asked),
            ask_counts={q: 2 for q in asked},
            measured_vitals=("temp", "sbp"),
        )
        nxt = next_question(criteria, with_chest)
    assert asked == ["cp_radiating", "cp_diaphoresis"]  # cp_dyspnea already known
    assert red_flags_resolved(criteria, with_chest)


def test_second_template_contributes_only_red_flags(criteria):
    base = inputs(
        category="fever",
        findings={"fever": "present", "chest_pain": "present",
                  "dyspnea": "absent", "severe_respiratory_distress": "absent"},
        asked=("fv_danger", "fv_chemo", "fv_rash", "cp_radiating", "cp_diaphoresis"),
        ask_counts={"fv_danger": 2, "fv_chemo": 2, "fv_rash": 2,
                    "cp_radiating": 2, "cp_diaphoresis": 2},
        measured_vitals=("temp", "sbp"),
    )
    seen = []
    nxt = next_question(criteria, base)
    while nxt is not None:
        seen.append(nxt.id)
        base = inputs(
            category="fever", findings=base.findings,
            asked=(*base.asked_question_ids, nxt.id),
            ask_counts={**base.ask_counts, nxt.id: 2},
            answered_slots=(*base.answered_slots, nxt.slot) if nxt.slot else base.answered_slots,
            measured_vitals=(*base.measured_vitals, nxt.vital) if nxt.vital else base.measured_vitals,
            questions_asked=base.questions_asked + 1,
        )
        nxt = next_question(criteria, base)
    assert not any(q.startswith("cp_") for q in seen), seen


# ------------------------------------------------------- engine journeys


async def _universals(j: Journey):
    """Age, breathing, gender — the universal questions every journey below
    walks through first."""
    await j.turn("40", ext(age_years=40))
    await j.turn("ปกติค่ะ", ext(
        findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"},
    ))
    return await j.turn("หญิง", ext(gender="female"))


async def _confirm_until_disposed(j: Journey, session: str, turns: int = 4) -> dict:
    """Answer each pending confirm question with its finding present."""
    r: dict = {}
    for _ in range(turns):
        state = await j.engine._store.load(session)
        if state.phase != "history":
            break
        fid = (state.pending_question_id or "").removeprefix("confirm_")
        r = await j.turn("ใช่ค่ะ", ext(findings={fid: "present"}), is_emergency=True)
    return r


async def test_journey_a_retracted_complaint_moves_the_interview(criteria):
    """Probe A end to end: the emergency reply must name the CURRENT
    complaint, and the nurse summary must not carry the retracted one."""
    j = Journey(criteria, "th", "corr-a")
    await j.turn("ปวดท้องค่ะ ปวดมาตั้งแต่เมื่อวาน", ext(
        chief_complaint="ปวดท้อง", complaint_category="abdominal_pain",
        findings={"abdominal_pain": "present"},
        slot_updates={"onset": "ตั้งแต่เมื่อวาน"},
    ))
    await _universals(j)
    r = await j.turn(
        "เอ่อ ขอโทษค่ะ พูดผิด จริงๆ ไม่ได้ปวดท้องค่ะ แต่เจ็บแน่นหน้าอก เหงื่อแตกด้วย",
        ext(
            chief_complaint="เจ็บแน่นหน้าอก", complaint_category="chest_pain",
            findings={"abdominal_pain": "absent", "chest_pain": "present",
                      "diaphoresis": "present"},
        ),
    )
    state = await j.engine._store.load("corr-a")
    assert state.complaint_category == "chest_pain"
    assert state.chief_complaint == "เจ็บแน่นหน้าอก"
    # confirm-before-fire still gates the new complaint's red flag
    assert r["classification"] == {}
    assert state.pending_question_id in ("confirm_chest_pain", "cp_diaphoresis")
    r = await _confirm_until_disposed(j, "corr-a")
    assert r["classification"]["level"] == 2
    assert "ปวดท้อง" not in r["classification"]["symptoms_summary"]
    assert "เจ็บแน่นหน้าอก" in r["classification"]["symptoms_summary"]


async def test_journey_b_free_text_retraction_of_confirmed_finding_gets_one_confirm(criteria):
    """Probe B, hardened: a chip-tap yes confirmed sweating; a later free-text
    "not sweating" gets the verbatim confirm once before the rule stands
    down (an STT mis-hear must not cancel an emergency path silently)."""
    j = Journey(criteria, "en", "corr-b")
    await j.turn("chest pain", ext(
        chief_complaint="chest pain", complaint_category="chest_pain",
        findings={"chest_pain": "present"},
    ))
    await _universals(j)
    await j.turn("no", ext(findings={"chest_pain_radiating": "absent"}))
    state = await j.engine._store.load("corr-b")
    assert state.pending_question_id == "cp_diaphoresis"
    # The answer to cp_diaphoresis confirms diaphoresis; chest_pain is still
    # unconfirmed so the gate asks confirm_chest_pain rather than disposing.
    await j.turn("yes, sweating", ext(findings={"diaphoresis": "present"}))
    state = await j.engine._store.load("corr-b")
    assert state.findings["diaphoresis"].confirmed is True
    assert state.pending_question_id == "confirm_chest_pain"
    # Free-text retraction of the CONFIRMED finding while answering → one
    # verbatim confirm for diaphoresis, no disposition.
    r = await j.turn(
        "yes chest pain, but actually I'm not sweating, I just felt warm",
        ext(findings={"chest_pain": "present", "diaphoresis": "absent"}),
    )
    state = await j.engine._store.load("corr-b")
    assert r["classification"] == {}
    assert state.pending_question_id == "confirm_diaphoresis"
    assert state.pending_confirm == ["diaphoresis"]
    assert templates.department_display("emergency", "en") not in r["reply"]
    # "no" → absent, confirmed → interview continues, nothing fires
    r = await j.turn("no", ext(findings={"diaphoresis": "absent"}))
    state = await j.engine._store.load("corr-b")
    assert state.findings["diaphoresis"].state == "absent"
    assert state.findings["diaphoresis"].confirmed is True
    assert r["classification"] == {}
    assert state.phase == "history"


async def test_journey_c_post_disposition_retraction_is_recorded_not_retriaged(criteria):
    j = Journey(criteria, "th", "corr-c")
    await j.turn("แน่นหน้าอกเหมือนช้างเหยียบ เหงื่อแตกท่วมตัว", ext(
        chief_complaint="แน่นหน้าอก", complaint_category="chest_pain",
        findings={"chest_pain": "present", "diaphoresis": "present"},
    ))
    await j.turn("ใช่ค่ะ", ext(findings={"chest_pain": "present"}))
    r = await j.turn("ใช่ค่ะ", ext(findings={"diaphoresis": "present"}), is_emergency=True)
    assert r["classification"]["level"] == 2
    r = await j.turn(
        "เอ๊ะ เดี๋ยวค่ะ หนูพูดผิด ไม่ได้เจ็บหน้าอก แค่ปวดท้องค่ะ", is_emergency=True,
    )
    assert r["post_disposition"] is True
    assert r["patient_follow_up"] == "เอ๊ะ เดี๋ยวค่ะ หนูพูดผิด ไม่ได้เจ็บหน้าอก แค่ปวดท้องค่ะ"
    assert r["classification"] == {}  # sticky in TriageService; nothing re-decided
    assert "แจ้งเจ้าหน้าที่ไว้ให้แล้ว" in r["reply"]
    state = await j.engine._store.load("corr-c")
    assert state.phase == "disposed"
    assert state.disposition["level"] == 2
    # a wayfinding question still gets the guidance, and is not a note
    r = await j.turn("แล้วไปตรงไหนคะ", is_emergency=True)
    assert "การคัดกรองเสร็จสิ้นแล้ว" in r["reply"]
    assert r["patient_follow_up"] == "เอ๊ะ เดี๋ยวค่ะ หนูพูดผิด ไม่ได้เจ็บหน้าอก แค่ปวดท้องค่ะ"


async def test_journey_f_added_complaint_gets_its_red_flags(criteria):
    j = Journey(criteria, "th", "corr-f")
    await j.turn("มีไข้ ปวดเมื่อยตัว มาสองวันค่ะ", ext(
        chief_complaint="มีไข้", complaint_category="fever",
        findings={"fever": "present"}, slot_updates={"duration": "สองวัน"},
    ))
    await j.turn("40", ext(age_years=40))
    await j.turn("ไม่มีค่ะ แต่ว่าตอนนี้แน่นหน้าอกด้วยค่ะ", ext(
        findings={"dyspnea": "absent", "severe_respiratory_distress": "absent",
                  "chest_pain": "present"},
    ))
    asked: list[str] = []
    for _ in range(12):
        state = await j.engine._store.load("corr-f")
        if state.phase != "history":
            break
        qid = state.pending_question_id
        asked.append(qid)
        if qid == "uq_gender":
            await j.turn("หญิง", ext(gender="female"))
        elif qid in ("fv_temp", "fv_bp", "pd_weight_height"):
            vital = {"fv_temp": {"temp": 37.8}, "fv_bp": {"sbp": 120, "dbp": 80},
                     "pd_weight_height": {"weight": 60, "height": 165}}[qid]
            await j.turn("", ext(), turn_context={"vitals": vital})
        else:
            await j.turn("ไม่มีค่ะ", ext(findings={
                fid: "absent" for fid in _finding_ids(criteria, qid)
            }))
    assert state.complaint_category == "fever"
    assert "cp_radiating" in asked and "cp_diaphoresis" in asked
    assert asked.index("fv_rash") < asked.index("cp_radiating")
    assert "cp_onset" not in asked  # red flags only, no second OLDCARTS


def _finding_ids(criteria, qid):
    for q in [*criteria.universal_questions, *criteria.pre_disposition_questions,
              *(q for t in criteria.complaint_templates for q in t.questions)]:
        if q.id == qid:
            return q.finding_ids
    return []


def test_anchor_the_template_already_covers_is_not_a_second_complaint(criteria):
    """A febrile UTI is one complaint: urinary's own question checks fever,
    so the fever template's red flags must NOT pile on (they spent the
    budget before urinary's slots in the 2026-08-22 regression run)."""
    base = inputs(
        category="urinary",
        findings={"dysuria": "present", "fever": "present", "abdominal_pain": "present",
                  "dyspnea": "absent", "severe_respiratory_distress": "absent"},
        measured_vitals=("temp", "sbp"),
    )
    seen = []
    nxt = next_question(criteria, base)
    while nxt is not None and len(seen) < 20:
        seen.append(nxt.id)
        base = inputs(
            category="urinary", findings=base.findings,
            asked=(*base.asked_question_ids, nxt.id),
            ask_counts={**base.ask_counts, nxt.id: 2},
            answered_slots=(*base.answered_slots, nxt.slot) if nxt.slot else base.answered_slots,
            measured_vitals=(*base.measured_vitals, nxt.vital) if nxt.vital else base.measured_vitals,
            questions_asked=base.questions_asked + 1,
        )
        nxt = next_question(criteria, base)
    assert not any(q.startswith(("fv_", "ap_")) for q in seen), seen
