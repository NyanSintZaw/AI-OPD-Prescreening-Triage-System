"""Output validator tests: level/color leaks (en+th), diagnosis, language."""

from app.services.screening.validator import validate_reply


def codes(reply, language="en", **kwargs):
    return {v.code for v in validate_reply(reply, language=language, **kwargs)}


def test_level_disclosure_english():
    assert "level_disclosure" in codes("Your triage level 2 means urgent care.")
    assert "level_disclosure" in codes("You are ESI level 3.")


def test_level_disclosure_thai():
    assert "level_disclosure" in codes("คุณอยู่ในระดับ 2 ต้องรีบไปห้องฉุกเฉินค่ะ", language="th")
    assert "level_disclosure" in codes("ผลคัดกรองอยู่ที่ระดับ ๓ ค่ะ", language="th")


def test_color_disclosure_in_triage_context():
    assert "color_disclosure" in codes("Your triage color is red, please hurry.")
    assert "color_disclosure" in codes("ผลการคัดกรองเป็นสีแดงค่ะ", language="th")


def test_color_words_without_triage_context_ok():
    assert "color_disclosure" not in codes("You mentioned a red rash on your arm.")
    assert "color_disclosure" not in codes("มีผื่นสีแดงที่แขนใช่ไหมคะ", language="th")


def test_diagnosis_patterns():
    assert "diagnosis" in codes("You probably have pneumonia.")
    assert "diagnosis" in codes("คุณน่าจะเป็นโรคปอดบวมค่ะ", language="th")


def test_you_have_to_is_not_diagnosis():
    assert "diagnosis" not in codes("You have to go to the emergency department now.")


def test_interrogative_you_have_is_not_diagnosis():
    """History-taking questions are legitimate — only declaratives diagnose."""
    assert "diagnosis" not in codes("Do you have chest pain or tightness with it?")
    assert "diagnosis" not in codes("Did you have a fever earlier today?")
    assert "diagnosis" not in codes("If you have trouble breathing, tell staff at once.")
    assert "diagnosis" in codes("You have a chest infection.")


def test_prescription_patterns():
    assert "prescription" in codes("Take 500 mg paracetamol every 6 hours.")
    assert "prescription" in codes("ทานยาพารา 2 เม็ดทุก 6 ชั่วโมงนะคะ", language="th")


def test_language_mismatch():
    assert "language_mismatch" in codes("Please go to the emergency room.", language="th")
    assert "language_mismatch" in codes("กรุณาไปห้องฉุกเฉินค่ะ", language="en")
    assert "language_mismatch" not in codes("กรุณาไป OPD ทั่วไปค่ะ", language="th")


def test_department_consistency():
    names = {
        "emergency": ["Emergency Department", "ห้องฉุกเฉิน"],
        "opd_ent": ["OPD ENT"],
        "opd_general": ["OPD General Practice"],
    }
    # emergency disposition must direct to ER
    assert "consistency" in codes(
        "Please rest at home and drink water.",
        department_code="emergency", department_names=names, is_emergency=True,
    )
    # naming a different department is inconsistent
    assert "consistency" in codes(
        "Please go to OPD ENT for your cough.",
        department_code="opd_general", department_names=names,
    )
    # correct department passes
    assert "consistency" not in codes(
        "Please go to OPD General Practice.",
        department_code="opd_general", department_names=names,
    )


def test_clean_reply_passes():
    assert codes("Thank you. Based on your symptoms, please proceed to OPD General Practice. Would you like the hospital to contact you afterwards? (yes/no)") == set()
    assert codes("ขอบคุณค่ะ กรุณาไปที่ OPD เวชปฏิบัติทั่วไปนะคะ ต้องการให้โรงพยาบาลติดต่อกลับไหมคะ", language="th") == set()
