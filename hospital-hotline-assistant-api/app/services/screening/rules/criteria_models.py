"""Versioned screening criteria schema.

The active ``ScreeningCriteria`` document is the single source of truth for
every deterministic decision the screening engine makes: red-flag detection,
MOPH ED Triage level disposition, department routing, and question selection.
Documents are stored as JSONB rows in ``screening_criteria_versions`` and are
hand-authored or extracted from nurse-uploaded manuals, then reviewed and
activated by head nurses.

Bilingual fields (``*_en`` / ``*_th``) are mandatory so a criteria version can
never be activated that would leave one session language without approved
wording.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

VitalName = Literal[
    "hr", "rr", "sbp", "dbp", "map", "spo2", "temp",
    "pain_score", "distress_score", "age_years",
]

CompareOp = Literal["lt", "le", "gt", "ge", "eq"]

FindingState = Literal["present", "absent"]


class CriterionCondition(BaseModel):
    """Evaluable condition AST over structured findings, vitals, and age.

    A condition is either a leaf (exactly one of ``finding_id`` or ``vital``)
    or a composite (``all_of`` / ``any_of``). Leaf vital conditions compare a
    numeric vital with ``op``/``value``. ``age_band`` restricts any condition
    to sessions whose age falls inside the named band from
    ``ScreeningCriteria.age_bands``.
    """

    finding_id: str | None = None
    state: FindingState = "present"
    vital: VitalName | None = None
    op: CompareOp | None = None
    value: float | None = None
    age_band: str | None = None
    all_of: list["CriterionCondition"] = Field(default_factory=list)
    any_of: list["CriterionCondition"] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_shape(self) -> "CriterionCondition":
        is_finding = self.finding_id is not None
        is_vital = self.vital is not None
        is_composite = bool(self.all_of or self.any_of)
        if sum([is_finding, is_vital, is_composite]) != 1:
            raise ValueError(
                "condition must be exactly one of: finding, vital comparison, "
                f"or composite (got finding_id={self.finding_id!r}, "
                f"vital={self.vital!r}, all_of={len(self.all_of)}, "
                f"any_of={len(self.any_of)})"
            )
        if is_vital and (self.op is None or self.value is None):
            raise ValueError(f"vital condition {self.vital!r} requires op and value")
        return self


class RuleBase(BaseModel):
    """Common shape for citable, bilingual rules."""

    id: str
    label_en: str
    label_th: str
    condition: CriterionCondition
    citation: str = ""  # section of the source manual, shown to nurses


class Level1Criterion(RuleBase):
    """Life-threatening organ failure — immediate ER (MOPH level 1)."""


class DangerVitalRule(RuleBase):
    """Dangerous vital-sign pattern (MOPH level 2 unless stated)."""

    level: int = 2


class AgeBand(BaseModel):
    """Named age interval in years; ``max_years`` exclusive."""

    min_years: float = 0.0
    max_years: float | None = None


class DeptRedFlagRule(RuleBase):
    """Department-specific red flag forcing a minimum acuity level."""

    department_code: str
    min_level: int = 2


class TriageTuple(BaseModel):
    """Finding combinations that force a minimum level (Infermedica pattern).

    Fires when all of ``findings_all`` are present and, if given, at least one
    of ``risk_factors_any`` is present.
    """

    id: str
    label_en: str
    label_th: str
    findings_all: list[str]
    risk_factors_any: list[str] = Field(default_factory=list)
    force_min_level: int
    citation: str = ""


class FastTrack(RuleBase):
    """Hospital fast-track pathway (e.g. Stroke BEFAST, MI)."""

    department_code: str
    level: int = 2


class RoutingEntry(BaseModel):
    """Chief-complaint category → destination department.

    ``specialty_conditions``: when non-empty, at least one must hold for the
    patient to go directly to the specialty clinic; otherwise they are routed
    to ``fallback_department_code`` (the MFU "fails ENT criteria → general
    OPD first" pattern).
    """

    complaint_category: str
    department_code: str
    specialty_conditions: list[CriterionCondition] = Field(default_factory=list)
    fallback_department_code: str = "opd_general"
    citation: str = ""


QuestionKind = Literal[
    "intake", "red_flag", "slot", "associated", "scale", "age", "measurement"
]

OldcartsSlot = Literal[
    "onset", "location", "duration", "character",
    "aggravating", "relieving", "timing", "severity",
]


class QuestionTemplate(BaseModel):
    """One nurse-approved interview question.

    ``red_flag`` and ``scale`` questions are always rendered verbatim;
    ``slot`` and ``associated`` questions may be LLM-paraphrased (validated).
    """

    id: str
    kind: QuestionKind
    slot: OldcartsSlot | None = None
    vital: VitalName | None = None  # for kind="measurement": the vital to collect
    finding_ids: list[str] = Field(default_factory=list)  # findings this question resolves / gates on
    text_en: str
    text_th: str
    priority: int = 100  # lower asks earlier within its kind

    @model_validator(mode="after")
    def _check_target(self) -> "QuestionTemplate":
        if self.kind == "slot" and self.slot is None:
            raise ValueError(f"slot question {self.id!r} requires slot")
        if self.kind in ("red_flag", "associated") and not self.finding_ids:
            raise ValueError(f"{self.kind} question {self.id!r} requires finding_ids")
        if self.kind == "measurement" and self.vital is None:
            raise ValueError(f"measurement question {self.id!r} requires vital")
        return self


class ComplaintTemplate(BaseModel):
    """Interview template for one chief-complaint category."""

    category: str
    label_en: str
    label_th: str
    keywords_en: list[str] = Field(default_factory=list)
    keywords_th: list[str] = Field(default_factory=list)
    questions: list[QuestionTemplate] = Field(default_factory=list)
    # minimum answered OLDCARTS slots per provisional level before disposing
    min_slots_by_level: dict[int, int] = Field(default_factory=lambda: {3: 4, 4: 4, 5: 3})
    associated_finding_ids: list[str] = Field(default_factory=list)


class FindingDef(BaseModel):
    """Catalog entry for one canonical finding id."""

    label_en: str
    label_th: str
    synonyms_en: list[str] = Field(default_factory=list)
    synonyms_th: list[str] = Field(default_factory=list)
    is_risk_factor: bool = False


class ScreeningCriteria(BaseModel):
    """Complete, versioned rule set driving the screening engine."""

    schema_version: int = 1
    age_bands: dict[str, AgeBand] = Field(default_factory=dict)
    finding_catalog: dict[str, FindingDef]
    level1_criteria: list[Level1Criterion]
    danger_vitals: list[DangerVitalRule]
    department_rules: list[DeptRedFlagRule]
    triage_tuples: list[TriageTuple] = Field(default_factory=list)
    fast_tracks: list[FastTrack] = Field(default_factory=list)
    routing_table: list[RoutingEntry]
    complaint_templates: list[ComplaintTemplate]
    # universal red-flag questions asked for every complaint before anything else
    universal_questions: list[QuestionTemplate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> "ScreeningCriteria":
        known = set(self.finding_catalog)

        def walk(cond: CriterionCondition) -> None:
            if cond.finding_id is not None and cond.finding_id not in known:
                raise ValueError(f"condition references unknown finding {cond.finding_id!r}")
            if cond.age_band is not None and cond.age_band not in self.age_bands:
                raise ValueError(f"condition references unknown age band {cond.age_band!r}")
            for child in [*cond.all_of, *cond.any_of]:
                walk(child)

        for rule in [
            *self.level1_criteria, *self.danger_vitals,
            *self.department_rules, *self.fast_tracks,
        ]:
            walk(rule.condition)
        for entry in self.routing_table:
            for cond in entry.specialty_conditions:
                walk(cond)
        for tup in self.triage_tuples:
            for fid in [*tup.findings_all, *tup.risk_factors_any]:
                if fid not in known:
                    raise ValueError(f"tuple {tup.id!r} references unknown finding {fid!r}")
        for template in self.complaint_templates:
            for fid in template.associated_finding_ids:
                if fid not in known:
                    raise ValueError(
                        f"template {template.category!r} references unknown finding {fid!r}"
                    )
            for question in template.questions:
                for fid in question.finding_ids:
                    if fid not in known:
                        raise ValueError(
                            f"question {question.id!r} references unknown finding {fid!r}"
                        )
        categories = {t.category for t in self.complaint_templates}
        for entry in self.routing_table:
            if entry.complaint_category not in categories and entry.complaint_category != "*":
                # routing entries may target categories without a bespoke
                # template (they fall back to the generic template), but the
                # category name must still be intentional — warn via error only
                # when no generic template exists.
                if "generic" not in categories:
                    raise ValueError(
                        f"routing entry {entry.complaint_category!r} has no template "
                        "and no generic fallback template exists"
                    )
        return self


def parse_criteria(payload: dict[str, Any]) -> ScreeningCriteria:
    """Validate a raw JSONB payload into a ScreeningCriteria document."""

    return ScreeningCriteria.model_validate(payload)
