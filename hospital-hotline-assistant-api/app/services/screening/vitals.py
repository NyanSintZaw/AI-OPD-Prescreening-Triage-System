"""Normalize kiosk/HIS vitals into the canonical keys the rules engine uses.

The blood-pressure kiosk and the HIS record vitals as ``systolic`` /
``diastolic`` / ``pulse_bpm`` / ``temperature``; the criteria conditions
(danger vitals) read ``sbp`` / ``dbp`` / ``hr`` / ``rr`` / ``map``. This is
the single place that bridge is defined.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .rules.criteria_models import (
    BMI_MAX,
    BMI_MIN,
    CrossCheck,
    VitalBound,
    default_cross_checks,
    default_vital_bounds,
)

# raw kiosk/HIS key -> canonical rules-engine key
_ALIASES: dict[str, str] = {
    "systolic": "sbp",
    "sbp": "sbp",
    "diastolic": "dbp",
    "dbp": "dbp",
    "pulse": "hr",
    "pulse_bpm": "hr",
    "hr": "hr",
    "heart_rate": "hr",
    "rr": "rr",
    "respiratory_rate": "rr",
    "temperature": "temp",
    "temp": "temp",
    "spo2": "spo2",
    "pain_score": "pain_score",
    "distress_score": "distress_score",
    # Not a booth measurement, but it is bounds-checked on the same rail.
    "age_years": "age_years",
    "weight": "weight",
    "weight_kg": "weight",
    "height": "height",
    "height_cm": "height",
}


@dataclass(frozen=True)
class Rejection:
    """One implausible value, kept for the re-ask prompt and the nurse review.

    ``value`` is the number as reported — nurse review shows it flagged rather
    than blank, so "the patient said 50 °C" never reads as "not measured".
    """

    vital: str
    value: float
    reason: str          # bound id ("out_of_range") or cross-check id
    text_en: str
    text_th: str

    def text(self, language: str) -> str:
        return self.text_en if language == "en" else self.text_th

    def as_dict(self) -> dict[str, Any]:
        return {
            "vital": self.vital,
            "value": self.value,
            "reason": self.reason,
            "text_en": self.text_en,
            "text_th": self.text_th,
        }


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# Standard clinical fever threshold; the criteria's own severity cutoffs
# still decide how MUCH it matters.
FEVER_TEMP_C = 37.8
# The catalog defines high_fever as "over 38.5°C" and the resource band counts
# it as its own systemic finding — so a thermometer that reads 38.9 has to set
# it. Before this only `fever` was derived, and a measured high fever counted
# once instead of twice, holding cases at level 4 that the band would
# otherwise have taken to 3.
HIGH_FEVER_TEMP_C = 38.5


def effective_vitals(state) -> dict[str, float]:
    """Vitals as the rules must see them: measured (cuff/HIS) beats spoken."""
    return {**state.vitals, **state.measured_vitals}


def apply_objective_findings(state) -> None:
    """Derive findings from measured vitals so instrument evidence beats chat
    extraction (a booth thermometer at 37.9 °C means fever, whatever the
    patient later says in passing)."""
    from .state import Finding  # local import: state.py imports nothing from here

    temp = effective_vitals(state).get("temp")
    if temp is None:
        return
    reading = float(temp)
    for finding_id, threshold in (
        ("fever", FEVER_TEMP_C),
        ("high_fever", HIGH_FEVER_TEMP_C),
    ):
        if reading < threshold:
            continue
        existing = state.findings.get(finding_id)
        if existing is None or existing.state != "present":
            state.findings[finding_id] = Finding(
                state="present",
                value=f"measured {reading:.1f}C",
                source_turn=state.turn_count,
                confirmed=True,  # instrument reading, not inference
            )


def normalize_vitals(raw: Mapping[str, Any] | None) -> dict[str, float]:
    """Return canonical numeric vitals, dropping unusable/absent values.

    Derives mean arterial pressure (``map``) from sbp/dbp when both are
    present, matching how the manual's danger-vital rules reference it.
    """
    if not raw:
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        canonical = _ALIASES.get(str(key).lower())
        if canonical is None:
            continue
        num = _to_float(value)
        if num is not None:
            out[canonical] = num
    if "sbp" in out and "dbp" in out and "map" not in out:
        out["map"] = round(out["dbp"] + (out["sbp"] - out["dbp"]) / 3, 1)
    return out


def _bounds(criteria) -> dict[str, VitalBound]:
    return getattr(criteria, "vital_bounds", None) or default_vital_bounds()


def _cross_checks(criteria) -> dict[str, CrossCheck]:
    return getattr(criteria, "cross_checks", None) or default_cross_checks()


def check_vitals(
    raw: Mapping[str, Any] | None, criteria=None
) -> tuple[dict[str, float], list[Rejection]]:
    """Split incoming vitals into physiologically possible and impossible.

    The single plausibility gate for every rail — cuff, HIS, kiosk form, and
    speech. Rejected keys are simply absent from the accepted map, and
    ``evaluator`` already treats a missing vital as never satisfying a rule
    leaf, so an impossible value is inert rather than merely unused.

    Bounds are an input filter, NOT a triage threshold: a systolic of 250 is
    accepted here and left to fire the hypertensive-crisis rule.
    """

    values = normalize_vitals(raw)
    bounds = _bounds(criteria)
    checks = _cross_checks(criteria)
    rejected: list[Rejection] = []

    for name in sorted(values):
        bound = bounds.get(name)
        if bound is None or bound.contains(values[name]):
            continue
        rejected.append(Rejection(
            vital=name, value=values[name], reason="out_of_range",
            text_en=bound.retry_text_en, text_th=bound.retry_text_th,
        ))

    def drop(*names: str, reason: str) -> None:
        check = checks.get(reason)
        for name in names:
            if name not in values or any(r.vital == name for r in rejected):
                continue
            rejected.append(Rejection(
                vital=name, value=values[name], reason=reason,
                text_en=check.text_en if check else "",
                text_th=check.text_th if check else "",
            ))

    # Blood pressure is ONE measurement reported as two numbers. If either half
    # is impossible the cycle itself failed (slipped cuff, pulled off early),
    # so the surviving half is not trustworthy evidence either — without this,
    # a 300/220 leaves sbp=300 standing and fires the hypertensive-crisis rule.
    bad_bp = {r.vital for r in rejected} & {"sbp", "dbp"}
    if bad_bp:
        partner_text = next(r for r in rejected if r.vital in bad_bp)
        for name in ({"sbp", "dbp"} - bad_bp) & set(values):
            rejected.append(Rejection(
                vital=name, value=values[name], reason="out_of_range",
                text_en=partner_text.text_en, text_th=partner_text.text_th,
            ))
    # Swapped or nonsensical cuff entry: the top number must exceed the bottom.
    elif "sbp" in values and "dbp" in values and values["sbp"] <= values["dbp"]:
        drop("sbp", "dbp", reason="sbp_le_dbp")
    # Unit mix-up guard (height in metres, weight in pounds) via implied BMI.
    if "weight" in values and "height" in values and values["height"] > 0:
        bmi = values["weight"] / (values["height"] / 100) ** 2
        if not BMI_MIN <= bmi <= BMI_MAX:
            drop("weight", "height", reason="bmi_implausible")

    bad = {r.vital for r in rejected}
    accepted = {k: v for k, v in values.items() if k not in bad}
    # ``map`` is derived, so it must not outlive the readings it came from.
    if bad & {"sbp", "dbp"}:
        accepted.pop("map", None)
    return accepted, rejected


def record_rejections(state, rejections: list[Rejection], source: str) -> None:
    """Persist rejections on the state, counting repeat offences per vital."""

    for rejection in rejections:
        prior = state.rejected_vitals.get(rejection.vital) or {}
        state.rejected_vitals[rejection.vital] = {
            **rejection.as_dict(),
            "source": source,
            "attempts": int(prior.get("attempts", 0)) + 1,
            "turn": state.turn_count,
        }


# Vitals a triage nurse expects before trusting a disposition. The kiosk
# measures BP (+pulse via cuff), temperature, and SpO2 (+pulse via the
# oximeter — asked only once breathing difficulty is present), so rr is always
# absent and hr/spo2 often are — surfaced as an explicit "not measured" caution
# in nurse review so missing data never reads as reassuring (undertriage guard).
CORE_TRIAGE_VITALS = ("hr", "rr", "spo2", "temp", "sbp")


def missing_core_vitals(measured: Mapping[str, Any] | None) -> list[str]:
    """Core vitals never instrument-measured this session, in canonical keys."""
    measured = measured or {}
    return [key for key in CORE_TRIAGE_VITALS if measured.get(key) is None]
