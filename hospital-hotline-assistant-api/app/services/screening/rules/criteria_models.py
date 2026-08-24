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

from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, model_validator

VitalName = Literal[
    "hr", "rr", "sbp", "dbp", "map", "spo2", "temp",
    "pain_score", "distress_score", "age_years",
    "weight", "height",
]

CompareOp = Literal["lt", "le", "gt", "ge", "eq"]

FindingState = Literal["present", "absent"]

# Closed gender set for predicates. The session value may also be "unknown";
# a predicate can only name a definite gender — see the fail-safe semantics
# on CriterionCondition.gender.
Gender = Literal["male", "female"]


class VitalBound(BaseModel):
    """Physiologically possible range for one vital — an INPUT FILTER.

    This is not a triage threshold. A systolic of 250 is inside the bound
    (accepted) *and* a hypertensive crisis (level 2); a systolic of 400 is
    outside it and is discarded before any rule can see it. Keeping the two
    axes separate is what stops a garbage cuff reading from disposing an
    emergency.

    ``retry_text_*`` is nurse-approved, patient-facing wording shown verbatim
    when a value is rejected — measurement questions are never LLM-paraphrased.
    """

    min: float
    max: float
    unit: str = ""
    retry_text_en: str
    retry_text_th: str

    def contains(self, value: float) -> bool:
        return self.min <= value <= self.max


# Cross-field checks whose logic lives in code (they compare two vitals, which
# the single-vital bound table can't express) but whose wording stays here.
CrossCheckId = Literal["sbp_le_dbp", "bmi_implausible"]


class CrossCheck(BaseModel):
    """Patient-facing wording for a cross-field plausibility rejection."""

    text_en: str
    text_th: str


def default_vital_bounds() -> dict[str, VitalBound]:
    """Bounds applied when a criteria document doesn't author its own.

    Every stored document — including v1, which is the currently active
    version — gets a working plausibility layer without being re-authored.
    """

    return {
        "sbp": VitalBound(
            min=50, max=300, unit="mmHg",
            retry_text_en="That blood pressure reading doesn't look right. A systolic reading is normally between 50 and 300 mmHg — could you check and enter it again?",
            retry_text_th="ค่าความดันตัวบนดูไม่ถูกต้องนะคะ ปกติจะอยู่ระหว่าง 50 ถึง 300 mmHg รบกวนตรวจสอบและกรอกใหม่อีกครั้งนะคะ",
        ),
        "dbp": VitalBound(
            min=20, max=200, unit="mmHg",
            retry_text_en="That blood pressure reading doesn't look right. A diastolic reading is normally between 20 and 200 mmHg — could you check and enter it again?",
            retry_text_th="ค่าความดันตัวล่างดูไม่ถูกต้องนะคะ ปกติจะอยู่ระหว่าง 20 ถึง 200 mmHg รบกวนตรวจสอบและกรอกใหม่อีกครั้งนะคะ",
        ),
        "hr": VitalBound(
            min=20, max=250, unit="bpm",
            retry_text_en="That pulse doesn't look right. A pulse is normally between 20 and 250 beats per minute — could you check and enter it again?",
            retry_text_th="ค่าชีพจรดูไม่ถูกต้องนะคะ ปกติจะอยู่ระหว่าง 20 ถึง 250 ครั้งต่อนาที รบกวนตรวจสอบและกรอกใหม่อีกครั้งนะคะ",
        ),
        "rr": VitalBound(
            min=4, max=80, unit="/min",
            retry_text_en="That breathing rate doesn't look right. It is normally between 4 and 80 breaths per minute — could you check and enter it again?",
            retry_text_th="ค่าอัตราการหายใจดูไม่ถูกต้องนะคะ ปกติจะอยู่ระหว่าง 4 ถึง 80 ครั้งต่อนาที รบกวนตรวจสอบและกรอกใหม่อีกครั้งนะคะ",
        ),
        "spo2": VitalBound(
            min=50, max=100, unit="%",
            retry_text_en="That oxygen reading doesn't look right. It is normally between 50 and 100 percent — could you check and enter it again?",
            retry_text_th="ค่าออกซิเจนดูไม่ถูกต้องนะคะ ปกติจะอยู่ระหว่าง 50 ถึง 100 เปอร์เซ็นต์ รบกวนตรวจสอบและกรอกใหม่อีกครั้งนะคะ",
        ),
        "temp": VitalBound(
            min=30, max=45, unit="°C",
            retry_text_en="That temperature doesn't look right. A body temperature is normally between 30 and 45 °C — could you measure again and tell me the number?",
            retry_text_th="ค่าอุณหภูมิดูไม่ถูกต้องนะคะ อุณหภูมิร่างกายปกติจะอยู่ระหว่าง 30 ถึง 45 องศาเซลเซียส รบกวนวัดใหม่แล้วบอกตัวเลขอีกครั้งนะคะ",
        ),
        "weight": VitalBound(
            min=1, max=400, unit="kg",
            retry_text_en="That weight doesn't look right. Please enter your weight in kilograms (between 1 and 400).",
            retry_text_th="ค่าน้ำหนักดูไม่ถูกต้องนะคะ รบกวนกรอกน้ำหนักเป็นกิโลกรัม (ระหว่าง 1 ถึง 400) นะคะ",
        ),
        "height": VitalBound(
            min=30, max=272, unit="cm",
            retry_text_en="That height doesn't look right. Please enter your height in centimetres (between 30 and 272).",
            retry_text_th="ค่าส่วนสูงดูไม่ถูกต้องนะคะ รบกวนกรอกส่วนสูงเป็นเซนติเมตร (ระหว่าง 30 ถึง 272) นะคะ",
        ),
        "age_years": VitalBound(
            min=0, max=120, unit="years",
            retry_text_en="I didn't catch your age correctly. Could you tell me your age in years again?",
            retry_text_th="ขอโทษค่ะ ไม่แน่ใจเรื่องอายุ รบกวนบอกอายุเป็นปีอีกครั้งนะคะ",
        ),
        "pain_score": VitalBound(
            min=0, max=10, unit="",
            retry_text_en="Please give your pain a number from 0 to 10.",
            retry_text_th="รบกวนให้คะแนนความเจ็บปวดเป็นตัวเลข 0 ถึง 10 นะคะ",
        ),
        "distress_score": VitalBound(
            min=0, max=10, unit="",
            retry_text_en="Please give your breathing difficulty a number from 0 to 10.",
            retry_text_th="รบกวนให้คะแนนความเหนื่อยหอบเป็นตัวเลข 0 ถึง 10 นะคะ",
        ),
    }


def default_cross_checks() -> dict[str, CrossCheck]:
    return {
        "sbp_le_dbp": CrossCheck(
            text_en="The blood pressure numbers look swapped — the top number should be higher than the bottom one. Could you check and enter them again?",
            text_th="ค่าความดันดูเหมือนสลับกันนะคะ ตัวบนควรมากกว่าตัวล่าง รบกวนตรวจสอบและกรอกใหม่อีกครั้งนะคะ",
        ),
        "bmi_implausible": CrossCheck(
            text_en="The weight and height don't seem to match up. Could you check both numbers and enter them again?",
            text_th="ค่าน้ำหนักและส่วนสูงดูไม่สอดคล้องกันนะคะ รบกวนตรวจสอบทั้งสองค่าและกรอกใหม่อีกครั้งนะคะ",
        ),
    }


# Implied-BMI window for the weight/height cross-check. Deliberately far wider
# than any clinical band — this rejects unit mix-ups (height typed in metres,
# weight in pounds), not unusual bodies.
BMI_MIN = 5.0
BMI_MAX = 150.0


class CriterionCondition(BaseModel):
    """Evaluable condition AST over structured findings, vitals, and age.

    A condition is either a leaf (exactly one of ``finding_id`` or ``vital``)
    or a composite (``all_of`` / ``any_of``). Leaf vital conditions compare a
    numeric vital with ``op``/``value``. ``age_band`` restricts any condition
    to sessions whose age falls inside the named band from
    ``ScreeningCriteria.age_bands``.

    ``gender`` restricts a condition to sessions with that RECORDED gender —
    but fail-safe: an unknown, missing, or unexpected session gender always
    MATCHES the predicate (evaluator.py). Gender data is exactly the kind
    that is missing or wrong, so the predicate can narrow a rule only when a
    definite opposite value is on record; it can never silently switch a rule
    off for a patient whose gender we don't know. Consequently it must NEVER
    be used on any rule that escalates (level 1–2) — it cannot make such a
    rule safer, only blind it for definitely-recorded patients.
    """

    finding_id: str | None = None
    state: FindingState = "present"
    vital: VitalName | None = None
    op: CompareOp | None = None
    value: float | None = None
    age_band: str | None = None
    gender: Gender | None = None
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
    "intake", "red_flag", "slot", "associated", "scale", "age", "gender",
    "measurement",
]

OldcartsSlot = Literal[
    "onset", "location", "duration", "character",
    "aggravating", "relieving", "timing", "severity",
]


class QuestionOption(BaseModel):
    """Deterministic quick-reply chip for a question (localized labels)."""

    id: str
    text_en: str
    text_th: str


class QuestionOption(BaseModel):
    """One tappable quick-reply answer shown under the question. The label
    is nurse-approved wording; tapping sends it as the patient's reply."""

    id: str
    text_en: str
    text_th: str


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
    # For kind="measurement": only ask patients at/above this age (e.g. the
    # BP always-measure guard for age >= 60 on otherwise-minor complaints).
    # Unknown age also skips (resolved) so we never block the interview on it.
    min_age_years: float | None = None
    # Skip this question when the session's RECORDED gender equals this value
    # (e.g. don't ask a patient recorded male about pregnancy). Unknown gender
    # never matches, so unknown always still gets asked — the skip is an
    # efficiency for definite records only, never a safety gate.
    skip_for_gender: Gender | None = None
    # Authored quick-reply options; kinds without authored options fall back
    # to engine defaults (yes/no for red_flag/associated).
    options: list[QuestionOption] = Field(default_factory=list)
    text_en: str
    text_th: str
    priority: int = 100  # lower asks earlier within its kind
    citation: str = ""  # source standard for red-flag questions (docs/criteria-standards.md)

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
    # The finding(s) that ARE this complaint (chest_pain -> chest_pain). Two
    # uses, both deterministic: the category may move to another template
    # once every anchor is absent (the patient retracted the complaint), and
    # another template's red-flag questions join the interview while one of
    # its anchors is present (a second complaint added mid-interview). Empty
    # = neither happens for this template.
    anchor_finding_ids: list[str] = Field(default_factory=list)


class FindingDef(BaseModel):
    """Catalog entry for one canonical finding id."""

    label_en: str
    label_th: str
    synonyms_en: list[str] = Field(default_factory=list)
    synonyms_th: list[str] = Field(default_factory=list)
    # Nurse-authored yes/no sentence used to confirm this finding before a
    # level-1/2 rule fires on it ("Just to be sure — is your chest hurting or
    # feeling tight right now?"). Without one the engine synthesizes
    # "do you have this right now: <label>?". Must name the finding with a
    # label/synonym word so the rewording guard can calibrate on it.
    confirm_en: str | None = None
    confirm_th: str | None = None
    is_risk_factor: bool = False


class SourceStandard(BaseModel):
    """One published standard the criteria document is derived from
    (rendered with a link in the admin Screening Criteria tab)."""

    name: str
    edition: str = ""
    url: str = ""


class ScreeningCriteria(BaseModel):
    """Complete, versioned rule set driving the screening engine."""

    schema_version: int = 1
    source_standards: list[SourceStandard] = Field(default_factory=list)
    age_bands: dict[str, AgeBand] = Field(default_factory=dict)
    # Plausibility filter for incoming values (patient-reported and instrument
    # alike). Defaults apply to documents that don't author their own, so every
    # stored version gets the filter without being rewritten.
    vital_bounds: dict[str, VitalBound] = Field(default_factory=default_vital_bounds)
    cross_checks: dict[str, CrossCheck] = Field(default_factory=default_cross_checks)
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
    # universal questions asked LAST, after the template's own questions —
    # typically booth measurements (weight/height) collected before disposing
    pre_disposition_questions: list[QuestionTemplate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> "ScreeningCriteria":
        known = set(self.finding_catalog)

        for name, bound in self.vital_bounds.items():
            if name not in get_args(VitalName):
                raise ValueError(f"vital_bounds references unknown vital {name!r}")
            if bound.min >= bound.max:
                raise ValueError(f"vital_bounds[{name!r}] has min >= max")
        for check_id in self.cross_checks:
            if check_id not in get_args(CrossCheckId):
                raise ValueError(f"cross_checks references unknown check {check_id!r}")

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
            for fid in [*template.associated_finding_ids, *template.anchor_finding_ids]:
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
        for question in [*self.universal_questions, *self.pre_disposition_questions]:
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
        # Department codes must be ones the engine can name: a typo here used
        # to pass validation and surface only as a silently dropped
        # recommendation in TriageService. DEPARTMENT_NAMES is the canonical
        # code set (engine, validator, rule book and eval all derive from it).
        from ..templates import DEPARTMENT_NAMES

        def check_dept(owner: str, code: str | None) -> None:
            if code is not None and code not in DEPARTMENT_NAMES:
                raise ValueError(f"{owner} references unknown department {code!r}")

        for rule in [*self.department_rules, *self.fast_tracks]:
            check_dept(f"rule {rule.id!r}", rule.department_code)
        for entry in self.routing_table:
            check_dept(f"routing entry {entry.complaint_category!r}", entry.department_code)
            check_dept(
                f"routing entry {entry.complaint_category!r} fallback",
                entry.fallback_department_code,
            )
        return self


def parse_criteria(payload: dict[str, Any]) -> ScreeningCriteria:
    """Validate a raw JSONB payload into a ScreeningCriteria document."""

    return ScreeningCriteria.model_validate(payload)
