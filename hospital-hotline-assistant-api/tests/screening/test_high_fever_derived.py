"""A measured high fever must set high_fever, not just fever.

`high_fever` is in the criteria catalog ("over 38.5°C") and in
disposition.SYSTEMIC_FINDINGS, where the resource band counts systemic
findings to decide level 3 vs 4. Nothing ever derived it: only `fever` came
off the thermometer, so a booth reading of 38.9 contributed ONE systemic
finding instead of two and held cases at level 4 (found 2026-08-10 across
two vignettes in the triage eval).
"""

from __future__ import annotations

import pytest

from app.services.screening.rules.disposition import SYSTEMIC_FINDINGS
from app.services.screening.state import ScreeningState
from app.services.screening.vitals import (
    FEVER_TEMP_C,
    HIGH_FEVER_TEMP_C,
    apply_objective_findings,
)


def _state(temp: float) -> ScreeningState:
    state = ScreeningState(session_id="s", language="th")
    state.measured_vitals = {"temp": temp}
    apply_objective_findings(state)
    return state


def test_high_fever_counts_as_its_own_systemic_finding():
    assert {"fever", "high_fever"} <= SYSTEMIC_FINDINGS


@pytest.mark.parametrize(
    "temp,expected",
    [
        (36.8, set()),
        (37.9, {"fever"}),
        (FEVER_TEMP_C, {"fever"}),
        (38.4, {"fever"}),
        (HIGH_FEVER_TEMP_C, {"fever", "high_fever"}),
        (38.9, {"fever", "high_fever"}),
    ],
)
def test_thermometer_derives_both_thresholds(temp, expected):
    present = {
        fid for fid, f in _state(temp).findings.items() if f.state == "present"
    }
    assert present == expected


def test_derived_high_fever_is_instrument_confirmed():
    """Confirmed, so the confirm-before-fire gate does not re-ask a number the
    booth measured."""
    finding = _state(39.2).findings["high_fever"]
    assert finding.confirmed is True
    assert "39.2" in (finding.value or "")
