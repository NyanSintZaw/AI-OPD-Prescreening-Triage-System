"""The rewording guard (`nodes.question.wording_violations`) in both
languages — the cases that were wrong at some point while tuning it against
the real model's rewordings (evals/reports/question-wording-*.md).

Guarantee: a rewording that drops a symptom the template names, or changes
the question's shape, is refused; an everyday rewording that still names
every symptom is accepted. Never a model call."""

import pytest

from app.services.screening.nodes.question import _th_has, wording_violations
from app.services.screening.rules.question_policy import confirm_question_for


def _q(criteria, qid):
    for src in (criteria.universal_questions, criteria.pre_disposition_questions,
                *(t.questions for t in criteria.complaint_templates)):
        for q in src:
            if q.id == qid:
                return q
    return confirm_question_for(criteria, qid.removeprefix("confirm_"))


@pytest.mark.parametrize("qid,lang,text,expected", [
    # ── compound red flags: dropping one symptom is refused ──
    ("fv_danger", "en", "Are you feeling confused, having any trouble breathing, or do you have a stiff neck along with your fever?", []),
    ("fv_danger", "en", "Have you felt confused or short of breath with the fever?", ["missing:stiff_neck"]),
    ("fv_danger", "th", "ตอนนี้มีอาการซึม สับสน หายใจเหนื่อย หรือมีไข้ร่วมกับคอแข็งบ้างไหมคะ", []),
    ("fv_danger", "th", "มีอาการอื่นร่วมกับไข้ไหมคะ", ["missing:confusion", "missing:dyspnea", "missing:stiff_neck"]),
    # "fever" alone never stands in for "stiff neck with fever"
    ("hd_stiff_neck", "en", "Are you feeling feverish, or have you noticed any stiffness in your neck?", []),
    ("hd_stiff_neck", "en", "Are you feeling feverish?", ["missing:stiff_neck"]),
    # GI bleed: the shared "เป็นเลือด" of vomiting blood must not cover bloody stool
    ("ap_gi_bleed", "th", "ในช่วงสัปดาห์ที่ผ่านมา คุณมีอาการอาเจียนเป็นเลือด หรือถ่ายออกมาเป็นสีดำบ้างไหมคะ", ["missing:bloody_stool"]),
    ("gi_blood", "th", "คุณมีอาการอาเจียนออกมาเป็นเลือด ถ่ายเป็นเลือด หรือถ่ายอุจจาระเป็นสีดำบ้างไหมคะ", []),
    ("ap_gi_bleed", "en", "Have you noticed any blood when you vomit or go to the bathroom, or have you had black stools this past week?", []),
    # BEFAST: arm/leg weakness dropped
    ("hd_befast", "en", "Are you having any trouble with your speech, face movement, or arm strength, or are you unsteady?", ["missing:limb_weakness", "missing:sudden_vision_loss"]),
    # a template that paraphrases the finding loosely still guards it
    ("inj_mechanism", "en", "Could you tell me how you were stabbed?", ["missing:major_trauma_mechanism"]),
    ("msk_injury", "en", "Did you have a recent injury, or does anything look out of place?", ["missing:fracture_suspected"]),
    # a yes/no turned into a which-side question loses "one leg"
    ("lv_dvt", "th", "อาการบวมและปวดที่ขาของคุณ เป็นแค่ข้างเดียวหรือว่าเป็นทั้งสองข้างคะ", ["missing:unilateral_leg_swelling", "not_yes_no"]),
    # ── everyday rewordings that keep every symptom are accepted ──
    ("uq_breathing", "en", "Are you feeling breathless at all right now?", []),
    ("uq_breathing", "th", "ตอนนี้คุณรู้สึกเหนื่อยหอบหรือหายใจลำบากบ้างไหมคะ", []),
    ("ear_associated", "en", "Are you having any trouble hearing, ringing in your ears, fluid drainage, or dizziness when you move your head?", []),
    ("hd_associated", "en", "Are you having any vomiting or feeling like the room is spinning?", []),
    ("gyn_pelvic_pain", "en", "Are you feeling any intense pain in your lower belly or pelvic area?", []),
    ("dc_hemoptysis", "th", "เวลาไอออกมา มีเลือดปนออกมาบ้างไหมคะ", []),
    ("ear_fb", "th", "มีสิ่งของหรือแมลงเข้าไปติดอยู่ในหูบ้างไหมคะ", []),
    # ── shape ──
    ("ap_severity", "en", "How bad is the pain right now?", ["missing:scale_0_10"]),
    ("ap_severity", "en", "On a scale of zero to ten, how would you rate your pain right now?", []),
    ("ap_severity", "th", "ตอนนี้คุณรู้สึกปวดมากน้อยแค่ไหนคะ โดยให้คะแนนจาก 0 ถึง 10 ค่ะ", []),
    ("gen_onset", "th", "อาการที่คุณเล่ามานี้ เริ่มมีมานานแค่ไหนแล้วคะ", []),
    ("uq_gender", "th", "ขออนุญาตสอบถามเพศของคุณ เพื่อให้ข้อมูลที่เหมาะสมกับคุณที่สุดค่ะ", ["not_a_question"]),
    ("uq_gender", "th", "ขอถามหน่อยนะคะ ว่าคุณเป็นผู้ชายหรือผู้หญิงคะ", []),
    ("dc_severe_distress", "en", "Are you able to speak in full sentences, or are you struggling to breathe? Have you noticed blue lips?", ["question_count"]),
    ("uq_age", "en", "Could you please tell me your age?", []),
    ("uq_age", "en", "Could you tell me a little about yourself?", ["missing:age"]),
    # ── yes/no questions must stay yes/no ──
    ("confirm_chest_pain", "th", "ตอนนี้คุณยังรู้สึกเจ็บหรือแน่นหน้าอกอยู่มากน้อยแค่ไหนคะ", ["not_yes_no"]),
    ("lv_dvt", "en", "Which leg is swollen and painful?", ["not_yes_no"]),
    ("fv_danger", "en", "How confused are you, and is your neck stiff with the fever?", ["missing:dyspnea", "not_yes_no"]),
    ("fv_danger", "en", "How confused are you, and any trouble breathing or a stiff neck with the fever?", ["not_yes_no"]),
    # ── confirm questions (authored sentences) ──
    ("confirm_diaphoresis", "en", "Are you sweating a lot right now, like a cold sweat?", []),
    ("confirm_diaphoresis", "en", "Is that still happening?", ["missing:diaphoresis"]),
    ("confirm_chest_pain", "th", "ตอนนี้ยังแน่นหน้าอกอยู่ไหมคะ", []),
    ("confirm_chest_pain", "th", "ตอนนี้ยังเป็นอยู่ไหมคะ", ["missing:chest_pain"]),
])
def test_wording_guard(criteria, qid, lang, text, expected):
    q = _q(criteria, qid)
    verbatim = q.text_en if lang == "en" else q.text_th
    assert wording_violations(q, verbatim, text, criteria, lang) == expected


def test_thai_phrase_matching_tolerates_inserted_words_but_not_borrowed_ones():
    assert _th_has("ถ่ายดำ", "ถ่ายอุจจาระเป็นสีดำ")
    assert _th_has("อาเจียนเป็นเลือด", "อาเจียนออกมาเป็นเลือด")
    assert _th_has("น้ำไหลจากหู", "มีน้ำไหลออกจากหู")
    assert _th_has("ถ่ายเป็นเลือดสด", "ถ่ายเป็นเลือด")
    assert not _th_has("ถ่ายเป็นเลือดสด", "อาเจียนเป็นเลือด หรือถ่ายออกมาเป็นสีดำ")


def test_every_authored_confirm_sentence_is_guarded(criteria):
    """An authored confirm sentence must name its finding in a way the guard
    recognises — otherwise a rewording of it could drop the symptom freely."""
    from app.services.screening.nodes.question import _required_marks

    for fid, fdef in criteria.finding_catalog.items():
        if not fdef.confirm_en:
            continue
        q = confirm_question_for(criteria, fid)
        assert _required_marks(q, fid, q.text_en, criteria, "en"), f"{fid} en"
        assert _required_marks(q, fid, q.text_th, criteria, "th"), f"{fid} th"


def test_keep_line_lists_only_the_milder_grade_of_a_graded_pair(criteria):
    """uq_breathing checks dyspnea AND severe respiratory distress with one
    sentence; the prompt must not ask the model to keep 'severe … full
    sentences' (seen live: the reworded question raised the threshold)."""
    from app.services.screening.nodes.question import keep_terms_line

    q = next(x for x in criteria.universal_questions if x.id == "uq_breathing")
    line = keep_terms_line(q, q.text_en, criteria, "en")
    assert "breath" in line.lower()
    assert "severe" not in line.lower() and "full sentences" not in line.lower()
    line_th = keep_terms_line(q, q.text_th, criteria, "th")
    assert "พูดเป็นประโยคไม่ได้" not in line_th
