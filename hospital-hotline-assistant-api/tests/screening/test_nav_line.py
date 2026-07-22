"""Tests for patient-slip navigation line formatter."""

from app.services.screening.templates import nav_line


def test_nav_line_en_ent_third_floor():
    text = nav_line("ENT Clinic", language="en", floor="3")
    assert text == "Please proceed to the ENT Clinic, 3rd Floor."


def test_nav_line_en_opd_ent():
    text = nav_line("OPD ENT", language="en", floor="3")
    assert text == "Please proceed to OPD ENT, 3rd Floor."


def test_nav_line_th_with_floor():
    text = nav_line("แผนก OPD E.N.T (หู คอ จมูก)", language="th", floor="3")
    assert "กรุณาไปที่" in text
    assert "ชั้น 3" in text


def test_nav_hint_override():
    text = nav_line(
        "OPD ENT",
        language="en",
        floor="3",
        nav_hint="Please proceed to the ENT Clinic, 3rd Floor.",
    )
    assert text == "Please proceed to the ENT Clinic, 3rd Floor."


def test_nav_line_without_floor():
    assert nav_line("OPD General Practice", language="en") == (
        "Please proceed to OPD General Practice."
    )
