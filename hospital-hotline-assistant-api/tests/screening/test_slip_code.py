"""Slip code derivation must match the frontend (PatientIdPass.shortVisitId)."""

from app.services.slip_code import slip_code_for


def test_slip_code_long_uuid():
    # mirrors: clean.slice(0,4) + clean.slice(-4), uppercased, hyphens stripped
    assert slip_code_for("2f8a1c9b-4d3e-4f21-9a7c-1b2c3d4e5f60") == "MCH-2F8A-5F60"


def test_slip_code_short_input_returned_whole():
    assert slip_code_for("abc123") == "ABC123"


def test_slip_code_strips_non_alphanumeric():
    assert slip_code_for("a-b-c-1-2-3-4-5-6-7-8-9") == "MCH-ABC1-6789"
