"""Deterministic OPD screening engine (v2).

LangGraph-orchestrated interview loop where the LLM only converses,
extracts structured findings, and explains validated results. All
urgency (MOPH ED Triage 5-level, internal only) and department routing
decisions are made by the deterministic rules in
:mod:`app.services.screening.rules` against versioned, nurse-approved
criteria. The triage level is never disclosed to the patient.
"""
