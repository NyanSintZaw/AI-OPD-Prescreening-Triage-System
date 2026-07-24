"""Unit tests for the shared bilingual yes/no classifier."""

from app.services.screening.nlu_yesno import classify_yes_no


def test_classify_yes_english():
    for text in ("yes", "Yes!", "yeah", "yep", "sure", "ok", "okay"):
        assert classify_yes_no(text) == "yes", text


def test_classify_yes_thai():
    for text in ("ใช่", "ใช่ค่ะ", "ใช่ครับ", "ครับ", "ค่ะ"):
        assert classify_yes_no(text) == "yes", text


def test_classify_no_english():
    for text in ("no", "Nope", "not really", "that's not me", "wrong person", "not me"):
        assert classify_yes_no(text) == "no", text


def test_classify_no_thai():
    for text in ("ไม่", "ไม่ใช่", "เปล่า", "ไม่ใช่ฉัน", "ชื่อผิด"):
        assert classify_yes_no(text) == "no", text


def test_classify_uncertain():
    for text in ("not sure", "I don't know", "maybe", "ไม่แน่ใจ", "ไม่แน่ใจเลยครับ"):
        assert classify_yes_no(text) == "uncertain", text


def test_classify_other_and_empty():
    assert classify_yes_no("") == "other"
    assert classify_yes_no("   ") == "other"
    assert classify_yes_no("I have a fever") == "other"
    assert classify_yes_no("ชื่อของฉันคือสมชาย") == "other"


def test_identity_confirm_phrases():
    assert classify_yes_no("that's me") == "yes"
    assert classify_yes_no("it's me") == "yes"
    assert classify_yes_no("ถูกแล้ว") == "yes"
    assert classify_yes_no("different person") == "no"


def test_identity_confirm_extra_phrasings():
    # From the July 22 live NLU battery.
    for text in ("แน่นอนครับ", "of course", "อือ"):
        assert classify_yes_no(text) == "yes", text
    assert classify_yes_no("nope, wrong one") == "no"


def test_identity_confirm_compounds_yes():
    # Natural-language affirmatives, not just bare tokens (meeting req #1).
    for text in (
        "yes that's me",
        "yeah, that's right",
        "yes it's me",
        "ใช่ค่ะ ฉันเอง",
        "ใช่แล้วค่ะ",
        "ถูกต้องครับ",
        "ใช่ครับผม",
    ):
        assert classify_yes_no(text) == "yes", text


def test_identity_confirm_compounds_no():
    for text in (
        "no that's not me",
        "no, wrong person",
        "No, that's wrong",
        "i am not",
        "ไม่ใช่ค่ะ",
        "ไม่ใช่ครับ คนละคน",
        "ไม่ถูกต้องค่ะ",
        "ผิดคนค่ะ",
    ):
        assert classify_yes_no(text) == "no", text


def test_identity_confirm_content_stays_other():
    # Replies carrying real content must reprompt, not silently confirm/reject.
    assert classify_yes_no("ไม่ใช่ค่ะ ฉันชื่อมาลี") == "other"
    assert classify_yes_no("my name is Somchai") == "other"
