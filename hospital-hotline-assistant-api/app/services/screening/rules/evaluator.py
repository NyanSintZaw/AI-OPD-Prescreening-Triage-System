"""Pure evaluation of criteria conditions over structured findings.

No I/O, no LLM. Same inputs always produce the same result — this is the
determinism contract the tests pin.
"""

from __future__ import annotations

from typing import Mapping

from .criteria_models import AgeBand, CriterionCondition

# When the patient's age is unknown we evaluate adult rules (and flag the
# assumption in the rules trace) rather than silently skipping every
# age-restricted rule. Pediatric bands never match an unknown age.
ASSUMED_ADULT_AGE_YEARS = 30.0


def age_in_band(age_years: float | None, band: AgeBand) -> bool:
    effective = ASSUMED_ADULT_AGE_YEARS if age_years is None else age_years
    if effective < band.min_years:
        return False
    if band.max_years is not None and effective >= band.max_years:
        return False
    return True


def evaluate_condition(
    condition: CriterionCondition,
    *,
    findings: Mapping[str, str],
    vitals: Mapping[str, float],
    age_years: float | None,
    age_bands: Mapping[str, AgeBand],
) -> bool:
    """Evaluate a condition AST.

    ``findings`` maps finding id -> "present" | "absent"; ids not in the map
    are unknown and never satisfy a leaf (unknown is not absent).
    Missing vitals never satisfy a vital leaf.
    """

    if condition.age_band is not None:
        band = age_bands.get(condition.age_band)
        if band is None or not age_in_band(age_years, band):
            return False

    if condition.finding_id is not None:
        return findings.get(condition.finding_id) == condition.state

    if condition.vital is not None:
        if condition.vital == "age_years":
            actual: float | None = age_years
        else:
            actual = vitals.get(condition.vital)
        if actual is None or condition.op is None or condition.value is None:
            return False
        ops = {
            "lt": actual < condition.value,
            "le": actual <= condition.value,
            "gt": actual > condition.value,
            "ge": actual >= condition.value,
            "eq": actual == condition.value,
        }
        return ops[condition.op]

    # composite: all_of must all hold; any_of (when present) needs at least one
    kwargs = dict(findings=findings, vitals=vitals, age_years=age_years, age_bands=age_bands)
    if condition.all_of and not all(evaluate_condition(c, **kwargs) for c in condition.all_of):
        return False
    if condition.any_of and not any(evaluate_condition(c, **kwargs) for c in condition.any_of):
        return False
    return bool(condition.all_of or condition.any_of)
