"""SBAR handover built from session metadata — pure, no DB.

The two rules worth guarding: it must be Thai even when the patient spoke
English, and the triage level must be IN it (SBAR is clinician-facing, so the
patient-facing redaction does not apply).
"""
from app.services.screening.his.sbar import build_sbar, disposition_reason_texts

METADATA = {
    "slip_code": "MCH-A1B2-C3D4",
    "visit": {"visit_id": "VN-1", "age_years": 58},
    "vitals": {
        "systolic": 158, "diastolic": 94, "pulse_bpm": 96,
        "temperature": 36.8, "weight_kg": 72.5, "height_cm": 165,
        # Cuff for BP/pulse; the patient told us the rest.
        "sources": {
            "systolic": "device", "diastolic": "device", "pulse_bpm": "device",
            "temperature": "patient_input", "weight_kg": "patient_input",
            "height_cm": "patient_input",
        },
    },
    "patient_history": {
        "chronic_conditions": "ความดันโลหิตสูง",
        "allergies": "ไม่มี",
        "is_first_time": False,
    },
    "triage_classification": {
        "level": 3,
        "label": "Urgent",
        "symptoms_summary": "แน่นหน้าอก 2 ชั่วโมง",
        "key_reason": "Chest pain with cardiac risk factors",  # English!
        "response_time": "30 นาที",
        "pain_score": 6,
        "disposition_reasons": [
            {
                "rule_id": "cp_risk",
                "text_en": "Chest pain with risk factors",
                "text_th": "เจ็บหน้าอกร่วมกับปัจจัยเสี่ยง",
                "citation": "คู่มือคัดกรอง MFU ข้อ 4.2",
            }
        ],
    },
}


def _build(**kw):
    return build_sbar(METADATA, department_th="แผนก OPD MED (อายุรกรรม)", **kw)


def test_situation_uses_engine_summary_and_age():
    sbar = _build()
    assert "แน่นหน้าอก" in sbar["situation"]
    assert "58" in sbar["situation"]


def test_nurse_complaint_overrides_engine_summary():
    sbar = _build(chief_complaint="พยาบาลแก้ไข: เจ็บหน้าอก")
    assert sbar["situation"].startswith("พยาบาลแก้ไข")


def test_assessment_carries_vitals_and_the_triage_level():
    """SBAR is clinician-facing: the level belongs here. The patient-facing
    redaction in validator.py / triage_payloads.py must NOT be applied."""
    assessment = _build()["assessment"]
    assert "158/94" in assessment
    assert "ระดับคัดกรอง 3" in assessment
    assert "Urgent" in assessment


def test_measured_and_stated_vitals_are_grouped_separately():
    """A cuff reading and a number the patient said are different evidence.
    Before this, one `source` flag covered the whole dict, so a patient-stated
    weight beside a cuff BP was reported to the clinician as booth-measured."""
    assessment = _build()["assessment"]
    measured, stated = assessment.split(" | ")[0], assessment.split(" | ")[1]
    assert measured.startswith("วัดที่บูธ:")
    assert "158/94" in measured and "ชีพจร 96" in measured
    assert stated.startswith("ผู้ป่วยแจ้ง:")
    assert "น้ำหนัก 72.5" in stated and "ส่วนสูง 165" in stated
    # the cuff reading must never end up on the patient-stated side
    assert "158/94" not in stated


def test_legacy_whole_dict_source_still_understood():
    """Sessions recorded before per-vital provenance existed."""
    meta = {"vitals": {"systolic": 158, "diastolic": 94, "source": "manual"}}
    assert "ผู้ป่วยแจ้ง:" in build_sbar(meta, department_th="x")["assessment"]


def test_problem_uses_thai_reasons_with_citation_not_english_key_reason():
    """key_reason is language-selected when the engine builds it, so an
    English session would otherwise ship an English handover."""
    problem = _build()["assessment_problem"]
    assert "เจ็บหน้าอกร่วมกับปัจจัยเสี่ยง" in problem
    assert "คู่มือคัดกรอง MFU ข้อ 4.2" in problem
    assert "Chest pain with cardiac risk factors" not in problem


def test_key_reason_is_the_fallback_only_when_no_structured_reasons():
    meta = {
        **METADATA,
        "triage_classification": {
            **METADATA["triage_classification"],
            "disposition_reasons": [],
        },
    }
    assert "Chest pain" in build_sbar(meta, department_th="x")["assessment_problem"]


def test_background_lists_history_segments():
    background = _build()["background"]
    assert "โรคประจำตัว: ความดันโลหิตสูง" in background
    assert "แพ้ยา" in background


def test_recommend_names_the_department_and_flags_a_reroute():
    assert "แผนก OPD MED" in _build()["recommend"]
    assert "พยาบาลปรับแผนก" in _build(rerouted=True)["recommend"]
    assert "พยาบาลปรับแผนก" not in _build()["recommend"]


def test_equipment_is_never_auto_filled():
    """Deciding what equipment to prepare is a clinical judgement our system
    does not make — the nurse owns this field."""
    assert _build()["assessment_equipment"] is None


def test_documentation_carries_the_slip_code():
    assert "MCH-A1B2-C3D4" in _build()["documentation"]


def test_empty_metadata_never_raises_and_yields_all_seven_keys():
    sbar = build_sbar({}, department_th="แผนก X")
    assert set(sbar) == {
        "situation", "background", "assessment", "assessment_problem",
        "assessment_equipment", "recommend", "documentation",
    }
    assert sbar["situation"] is None
    assert sbar["recommend"]  # the destination is always known


def test_reason_flattener_language_preference():
    c = METADATA["triage_classification"]
    assert disposition_reason_texts(c)[0].startswith("Chest pain")
    assert disposition_reason_texts(c, prefer_thai=True)[0].startswith("เจ็บหน้าอก")
