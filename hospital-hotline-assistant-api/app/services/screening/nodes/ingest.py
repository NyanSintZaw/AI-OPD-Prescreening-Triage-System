"""Ingest node: LLM structured extraction of the patient's message."""

from __future__ import annotations

import logging
import re
from time import perf_counter

from ..extraction import ExtractionResult, build_extraction_prompt
from ..nlu_yesno import BARE_AFFIRMATION, BARE_DENIAL, BARE_UNCERTAINTY, UNC_CORE_RE
from ..rules.question_policy import GENERIC_CATEGORY, get_template
from ..rules.red_flags import critical_finding_ids
from ..state import OLDCARTS_SLOTS, Finding
from ..vitals import (
    FEVER_TEMP_C,
    apply_objective_findings,
    check_vitals,
    effective_vitals,
    record_rejections,
)
from .base import GraphDeps, GraphState, ainvoke_with_timeout

logger = logging.getLogger(__name__)

MAX_EXTRACTION_FAILURES = 2


def _pending_question(state, criteria):
    if not state.pending_question_id:
        return None
    if state.pending_question_id.startswith("confirm_"):
        # Synthesized confirm-before-fire question (single finding).
        from ..rules.question_policy import confirm_question_for

        return confirm_question_for(
            criteria,
            state.pending_question_id.removeprefix("confirm_"),
            state.complaint_category,
        )
    template = get_template(criteria, state.complaint_category)
    questions = [
        *criteria.universal_questions,
        *template.questions,
        *criteria.pre_disposition_questions,
        # The complaint category can move mid-interview (a new symptom
        # re-routes the template), so search every template — the answer must
        # still map back to the question that was actually asked.
        *(q for t in criteria.complaint_templates for q in t.questions),
    ]
    for question in questions:
        if question.id == state.pending_question_id:
            return question
    return None


def _pending_question_text(state, criteria) -> str | None:
    question = _pending_question(state, criteria)
    if question is None:
        return None
    return question.text_en if state.language == "en" else question.text_th


def strip_ambiguous_affirmation(result: ExtractionResult, pending, user_text: str) -> None:
    """A bare "yes" to a compound red flag cannot say WHICH bundled symptom is
    present — models mark them ALL (observed live: one Yes recorded confusion,
    dyspnea AND stiff_neck as present). Drop those updates deterministically so
    the policy re-asks the question with one chip per finding. uq_breathing is
    exempt: its findings are severity grades and the mildest-grade rule applies.
    """

    if (
        pending is None
        or pending.kind != "red_flag"
        or pending.id == "uq_breathing"
        or len(pending.finding_ids) <= 1
        or not BARE_AFFIRMATION.match(user_text)
    ):
        return
    ambiguous = set(pending.finding_ids)
    result.finding_updates = [
        u for u in result.finding_updates if u.id not in ambiguous
    ]


def strip_uncertain_answer(result: ExtractionResult, user_text: str) -> None:
    """"Not sure" / "ไม่แน่ใจ" answers nothing — observed live (th): the model
    recorded all three GI-bleed red-flag findings as absent for
    "ไม่แน่ใจเลยครับ". Findings must stay unknown so the policy re-asks."""

    if BARE_UNCERTAINTY.match(user_text) and UNC_CORE_RE.search(user_text):
        result.finding_updates = []
        result.slot_updates = {}


def strip_unscoped_denial(result: ExtractionResult, pending, user_text: str) -> None:
    """A bare denial answers only the question that was asked. Models extend
    it to findings merely mentioned in the paraphrase — observed live: "No"
    to the fever-associated question flipped fever (established on turn 1,
    37.9 °C measured) to absent, changing the triage level."""

    if pending is None or not BARE_DENIAL.match(user_text):
        return
    allowed = set(pending.finding_ids)
    result.finding_updates = [
        u for u in result.finding_updates if u.id in allowed
    ]


_ASCII_RE = re.compile(r"^[\x00-\x7f]+$")

# NegEx-style backward scope. A symptom the patient DENIED must not be read as
# evidence for anything — observed live: "มีไข้ แต่ไม่ปวดหัว" scored fever and
# headache one hit each, tied, and left the category unresolved, so the
# interview fell back to the generic question set and re-asked what the
# patient had already answered.
_NEG_CUES_TH = ("ไม่มี", "ไม่ได้", "ไม่ค่อย", "ไม่")
_NEG_CUES_EN = ("no ", "not ", "n't ", "without ", "denies ", "never ")
# A cue's scope ends here: "ไม่ไอ แต่ปวดหัว" denies the cough, not the headache.
_SCOPE_END_TH = ("แต่", "แต่ว่า", "และ", "ส่วน")
_SCOPE_END_EN = ("but ", "however ", "although ", ", ", "; ")
# Thai runs together, so the window is characters, not words. Long enough for
# "ไม่มีอาการ" + a qualifier, short enough not to reach the previous clause.
_NEG_WINDOW = 22


def _is_negated(text: str, start: int) -> bool:
    """True when the keyword at ``start`` sits inside a negation's scope."""
    window = text[max(0, start - _NEG_WINDOW):start]
    low = window.lower()
    cue_at = max(
        (window.rfind(c) for c in _NEG_CUES_TH),
        default=-1,
    )
    cue_at = max(cue_at, max((low.rfind(c) for c in _NEG_CUES_EN), default=-1))
    if cue_at < 0:
        return False
    # A scope terminator between the cue and the keyword ends the negation.
    end_at = max(
        max((window.rfind(t) for t in _SCOPE_END_TH), default=-1),
        max((low.rfind(t) for t in _SCOPE_END_EN), default=-1),
    )
    return end_at <= cue_at


def _keyword_hits(text: str, keyword: str, ascii_word: bool) -> int:
    """Occurrences of ``keyword`` that the patient did NOT deny."""
    hits = 0
    if ascii_word:
        for match in re.finditer(rf"\b{re.escape(keyword)}\b", text.lower()):
            if not _is_negated(text, match.start()):
                hits += 1
        return hits
    start = text.find(keyword)
    while start != -1:
        if not _is_negated(text, start):
            hits += 1
        start = text.find(keyword, start + 1)
    return hits


def _keyword_category(user_text: str, criteria) -> str | None:
    """Deterministic net under the LLM's category choice: when extraction
    yields no usable category, match the utterance against the criteria's own
    keyword lists (observed live: en "kinda dizzy, room was spining" went to
    generic, skipping the BEFAST stroke screen the th run got). Unique
    best-scoring category wins; ties or zero hits stay unresolved."""

    scores: list[tuple[int, str]] = []
    for template in criteria.complaint_templates:
        if template.category == "generic":
            continue
        hits = 0
        for keyword in [*template.keywords_en, *template.keywords_th]:
            keyword = keyword.lower().strip()
            if not keyword:
                continue
            hits += min(
                1, _keyword_hits(user_text, keyword, bool(_ASCII_RE.match(keyword)))
            )
        if hits:
            scores.append((hits, template.category))
    scores.sort(reverse=True)
    if not scores:
        return None
    if len(scores) > 1 and scores[1][0] == scores[0][0]:
        return None  # tie — don't guess
    return scores[0][1]


_CATEGORY_SCHEMA_CACHE: dict[tuple[str, ...], type] = {}


def _category_constrained_schema(criteria) -> type:
    """ExtractionResult with complaint_category pinned to the known ids.

    Only used when deps.constrain_category is set. Cached per vocabulary: the
    categories change only when the criteria version does, and rebuilding a
    pydantic model per turn would be pure waste.
    """
    from typing import Literal, Optional

    from pydantic import Field, create_model

    cats = tuple(sorted({t.category for t in criteria.complaint_templates}))
    cached = _CATEGORY_SCHEMA_CACHE.get(cats)
    if cached is not None:
        return cached
    model = create_model(
        "ExtractionResultConstrained",
        __base__=ExtractionResult,
        complaint_category=(
            Optional[Literal[cats]],  # type: ignore[valid-type]
            Field(default=None,
                  description="Best matching complaint category, or null"),
        ),
    )
    _CATEGORY_SCHEMA_CACHE[cats] = model
    return model


def _closest_category(raw: str, known: set[str]) -> str | None:
    """Deterministically map a near-miss category id to a known one.

    Models sometimes merge ids (gemini-3.1-flash-lite reliably returns
    'ear_nose_throat' for a sore-throat+cough message). Score known ids by
    token overlap and accept only a unique best match — an ambiguous or
    zero-overlap id stays unmapped, so the intake question fires instead.
    """
    tokens = set(raw.lower().replace("-", "_").split("_"))
    scores = sorted(
        ((len(tokens & set(k.split("_"))), k) for k in known), reverse=True
    )
    if not scores or scores[0][0] == 0:
        return None
    if len(scores) > 1 and scores[1][0] == scores[0][0]:
        return None  # tie — don't guess
    return scores[0][1]


def _normalize_for_evidence(text: str | None) -> str:
    """Whitespace-free casefold, so a quote check survives spacing/case drift
    (Thai has no spaces; English quotes may differ only in casing)."""
    return "".join((text or "").split()).casefold()


def _known_category(criteria, raw: str | None) -> str | None:
    if not raw:
        return None
    known = {t.category for t in criteria.complaint_templates}
    # routing-only categories (no bespoke template) are also legal
    known |= {e.complaint_category for e in criteria.routing_table}
    return raw if raw in known else _closest_category(raw, known)


def _anchors(criteria, category: str | None) -> set[str]:
    for template in criteria.complaint_templates:
        if template.category == category:
            return set(template.anchor_finding_ids)
    return set()


def _apply_category(state, criteria, result: ExtractionResult, user_text: str,
                    flipped_absent: set[str]) -> None:
    """Which template the interview follows. Runs AFTER the findings merge so
    it sees this turn's retractions."""

    turn = state.turn_count
    category = _known_category(criteria, result.complaint_category)
    current = state.complaint_category
    if current in (None, "", GENERIC_CATEGORY):
        # First specific category wins; a vague opener ("ไม่สบาย") lands on
        # generic and a later explicit complaint ("มีไข้") must be allowed to
        # upgrade it — otherwise the patient gets generic's catch-all red
        # flags instead of their complaint's screen (live finding: fever
        # patient asked the generic self-harm question). Never specific →
        # generic.
        if category:
            state.complaint_category = category
        # Keyword net: a missing or generic category is upgraded when the
        # utterance matches exactly one category's criteria keywords, so the
        # specific red-flag screen (e.g. BEFAST) runs.
        if user_text and state.complaint_category in (None, "", GENERIC_CATEGORY):
            keyword_category = _keyword_category(user_text, criteria)
            if keyword_category:
                state.complaint_category = keyword_category
        return

    # Specific → other specific only on evidence the rules can see, never on
    # the model's category pick alone (it re-picks every turn). Either the
    # complaint the template is built on was retracted this turn ("พูดผิด
    # ไม่ได้ปวดท้อง") and nothing of it remains, or the patient restated
    # their main problem AND the new complaint's own finding is present.
    # Measured 2026-08-22: extraction already returns exactly this — the
    # old finding absent, the new one present, chief_complaint re-stated —
    # and the write-once rule here was what discarded it (patient then heard
    # "เข้าใจแล้วค่ะว่ามีอาการปวดท้อง" in the emergency reply for chest pain).
    anchors = _anchors(criteria, current)
    anchor_gone = bool(anchors & flipped_absent) and not any(
        f.state == "present" for fid, f in state.findings.items() if fid in anchors
    )
    restated = bool(result.chief_complaint) and any(
        f.state == "present"
        for fid, f in state.findings.items()
        if fid in _anchors(criteria, category)
    )
    if category and category not in (current, GENERIC_CATEGORY) and (anchor_gone or restated):
        state.complaint_history.append(
            {"turn": turn, "category": current, "chief_complaint": state.chief_complaint}
        )
        state.complaint_category = category
        state.chief_complaint = result.chief_complaint or None
    elif anchor_gone and result.chief_complaint and result.chief_complaint != state.chief_complaint:
        # Same template, but the complaint text the nurse/HIS see was just
        # retracted ("ไม่ได้ปวดท้องแล้ว แต่จุกๆ") — keep the summary honest.
        state.complaint_history.append(
            {"turn": turn, "category": current, "chief_complaint": state.chief_complaint}
        )
        state.chief_complaint = result.chief_complaint


def _apply(state, criteria, result: ExtractionResult, user_text: str = "") -> None:
    turn = state.turn_count
    state.pending_retraction = []
    if result.chief_complaint and not state.chief_complaint:
        state.chief_complaint = result.chief_complaint

    measured_temp = effective_vitals(state).get("temp")
    # Findings the pending question explicitly checks: answering it (chip tap
    # or spoken yes/no) CONFIRMS those findings — everything else in this
    # message is free-text extraction and stays unconfirmed until asked.
    pending = _pending_question(state, criteria)
    pending_fids = set(pending.finding_ids) if pending is not None else set()
    normalized_text = _normalize_for_evidence(user_text)
    critical = critical_finding_ids(criteria)
    flipped_absent: set[str] = set()  # present before this turn, absent now
    for update in result.finding_updates:
        if update.id in criteria.finding_catalog:
            if (
                update.id == "fever"
                and update.state == "absent"
                and measured_temp is not None
                and float(measured_temp) >= FEVER_TEMP_C
            ):
                continue  # the booth thermometer outranks chat extraction
            previous = state.findings.get(update.id)
            if previous is not None and previous.state == "present" and update.state == "absent":
                flipped_absent.add(update.id)
                # A confirmed critical finding retracted in free text (not as
                # the answer to its own question): the graph asks the verbatim
                # confirm once before the retraction stands down a rule.
                if (
                    previous.confirmed
                    and update.id not in pending_fids
                    and update.id in critical
                ):
                    state.pending_retraction.append(update.id)
            evidence = (update.evidence or "").strip() or None
            state.findings[update.id] = Finding(
                state=update.state, value=update.value, source_turn=turn,
                confirmed=(
                    update.id in pending_fids
                    # A re-extraction must not silently demote a finding the
                    # patient already confirmed (same state only — a flip
                    # starts over as unconfirmed).
                    or (previous is not None
                        and previous.confirmed
                        and previous.state == update.state)
                ),
                evidence=evidence,
                evidence_verified=(
                    _normalize_for_evidence(evidence) in normalized_text
                    if evidence and normalized_text
                    else None
                ),
            )
    _apply_category(state, criteria, result, user_text, flipped_absent)
    for slot, value in result.slot_updates.items():
        if slot in OLDCARTS_SLOTS and value and str(value).strip():
            state.slots[slot] = str(value).strip()

    # Spoken numbers go through the same plausibility gate as the cuff — an
    # impossible value is rejected with a re-ask, never silently dropped.
    spoken = {
        "age_years": result.age_years,
        "pain_score": result.pain_score,
        "distress_score": result.distress_score,
        # A booth reading outranks speech, so don't even offer a spoken temp
        # (or a home-oximeter number) when the instrument already spoke.
        "temp": result.temperature_c if "temp" not in state.measured_vitals else None,
        "spo2": result.spo2_percent if "spo2" not in state.measured_vitals else None,
    }
    accepted, rejected = check_vitals(
        {k: v for k, v in spoken.items() if v is not None}, criteria
    )
    if rejected:
        record_rejections(state, rejected, source="reported")
    if "age_years" in accepted:
        state.age_years = accepted.pop("age_years")
    if result.gender in ("male", "female") and state.gender == "unknown":
        # Fill-only: a patient's answer establishes an unknown gender, but a
        # later utterance never flips an HIS-recorded / already-given value
        # mid-interview (that correction is a nurse action, not extraction).
        state.gender = result.gender
    for name, value in accepted.items():
        state.vitals[name] = value
    for name in ("pain_score", "distress_score"):
        if name in accepted:
            # Assignment, not setdefault: "I meant 4, not 7" must replace the
            # text the first answer left here, or the nurse summary keeps 7.
            state.slots["severity"] = str(int(accepted[name]))
    apply_objective_findings(state)


def make_ingest_node(deps: GraphDeps):
    async def ingest(graph_state: GraphState) -> GraphState:
        state = graph_state["s"]
        criteria = graph_state["criteria"]
        user_text = graph_state["user_text"]
        audit = graph_state.get("audit") or []

        # Clear any prior measurement request; the question node re-sets it
        # if it asks for another reading this turn. (turn_context has already
        # merged a supplied reading into state.vitals before the graph ran.)
        state.awaiting_measurement = None

        if deps.model is None:
            # No model configured — cannot extract; escalate to a nurse.
            state.extraction_failures = MAX_EXTRACTION_FAILURES
            state.phase = "escalated_to_nurse"
            return {"s": state, "audit": audit}

        prompt = build_extraction_prompt(
            criteria, state, user_text, _pending_question_text(state, criteria),
        )
        schema = (
            _category_constrained_schema(criteria)
            if deps.constrain_category
            else ExtractionResult
        )
        structured = deps.model.with_structured_output(schema)
        started = perf_counter()
        result: ExtractionResult | None = None
        for attempt in (1, 2):
            try:
                result = await ainvoke_with_timeout(structured, prompt, deps.model_timeout_s)
                break
            except Exception:
                logger.exception("extraction attempt %d failed", attempt)
        latency_ms = int((perf_counter() - started) * 1000)

        if result is None:
            audit.append({
                "call_site": "extraction", "latency_ms": latency_ms, "ok": False,
            })
            state.extraction_failures += 1
            if state.extraction_failures >= MAX_EXTRACTION_FAILURES:
                state.phase = "escalated_to_nurse"
            return {"s": state, "audit": audit}

        state.extraction_failures = 0
        pending = _pending_question(state, criteria)
        raw_findings = [(u.id, u.state) for u in result.finding_updates]
        strip_uncertain_answer(result, user_text)
        strip_unscoped_denial(result, pending, user_text)
        strip_ambiguous_affirmation(result, pending, user_text)
        kept = {u.id for u in result.finding_updates}
        audit.append({
            "call_site": "extraction", "latency_ms": latency_ms, "ok": True,
            "extracted": {
                "category": result.complaint_category,
                "findings": [
                    {"id": fid, "state": st, **({} if fid in kept else {"dropped": True})}
                    for fid, st in raw_findings
                ],
                "slots": dict(result.slot_updates),
                "age_years": result.age_years,
                "gender": result.gender,
            },
        })
        _apply(state, criteria, result, user_text)
        if result.wants_human:
            state.phase = "escalated_to_nurse"
        else:
            # The pending question was addressed (even if vaguely) — it is
            # resolved by being asked; never repeat it.
            state.pending_question_id = None
            if state.phase == "intake":
                state.phase = "history"
        return {"s": state, "audit": audit}

    return ingest
