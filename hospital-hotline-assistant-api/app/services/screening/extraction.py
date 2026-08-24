"""LLM structured extraction of one patient utterance.

The model's only job here is mapping natural language (th/en) onto the
bounded finding vocabulary and OLDCARTS slots — it makes no clinical
decisions. Output is schema-constrained via ``with_structured_output``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .rules.criteria_models import ScreeningCriteria
from .rules.question_policy import get_template
from .rules.red_flags import critical_finding_ids
from .state import ScreeningState


class FindingUpdate(BaseModel):
    """One finding the patient's message resolves."""

    id: str = Field(description="Canonical finding id from the provided catalog")
    state: Literal["present", "absent"] = Field(
        description="present if the patient confirms it, absent if they deny it"
    )
    value: str | None = Field(
        default=None, description="Optional detail, e.g. '3 days' or 'left side'"
    )
    evidence: str | None = Field(
        default=None,
        description="The exact words from the patient's message that state this "
        "finding, copied verbatim (same language, no paraphrase)",
    )


class ExtractionResult(BaseModel):
    """Structured reading of a single patient message."""

    # Description deliberately unchanged from v1: measured 2026-08-22, a
    # longer description here ("…or when they explicitly correct/replace
    # their main problem…") flipped gemini-3.1-flash-lite's turn-1 category
    # for epigastric pain (abdominal_pain -> gi, 4/4) and its finding
    # (abdominal_pain -> chest_pain). The correction semantics live in the
    # prompt rules, which measured clean.
    chief_complaint: str | None = Field(
        default=None,
        description="Patient's main problem in their own words, only when newly stated",
    )
    complaint_category: str | None = Field(
        default=None,
        description="Best matching complaint category from the provided list, or null",
    )
    finding_updates: list[FindingUpdate] = Field(default_factory=list)
    slot_updates: dict[str, str] = Field(
        default_factory=dict,
        description="OLDCARTS slots this message answers (onset, location, duration, "
        "character, aggravating, relieving, timing, severity) mapped to the answer text",
    )
    age_years: float | None = Field(
        default=None, description="Patient age in years when stated (0.5 = 6 months)"
    )
    gender: Literal["male", "female"] | None = Field(
        default=None,
        description="The patient's sex ONLY when they explicitly state it "
        "(e.g. 'male', 'female', 'ชาย', 'หญิง', typically answering the gender "
        "question). Never guess it from the name, symptoms, or wording; null "
        "when unstated or declined",
    )
    pain_score: int | None = Field(
        default=None, ge=0, le=10, description="0-10 pain score when stated"
    )
    distress_score: int | None = Field(
        default=None, ge=0, le=10, description="0-10 breathing difficulty score when stated"
    )
    temperature_c: float | None = Field(
        default=None, description="Body temperature in Celsius when stated"
    )
    spo2_percent: float | None = Field(
        default=None,
        description="Blood oxygen saturation percentage when the patient states a "
        "reading they measured themselves (e.g. a home pulse oximeter)",
    )
    is_question_to_assistant: bool = Field(
        default=False,
        description="True when the message is a question to the assistant rather than "
        "an answer about symptoms",
    )
    wants_human: bool = Field(
        default=False, description="True when the patient asks for a human/nurse"
    )


def _catalog_lines(criteria: ScreeningCriteria, state: ScreeningState) -> list[str]:
    """Bounded finding vocabulary for the prompt: the active template's
    red-flag/associated targets plus every finding referenced by rules that
    could fire next, with bilingual labels and synonyms."""

    template = get_template(criteria, state.complaint_category)
    wanted: set[str] = set(template.associated_finding_ids)
    for question in [*criteria.universal_questions, *template.questions]:
        wanted.update(question.finding_ids)
    # Findings referenced by tuples/rules keyed to already-present findings
    present = {fid for fid, f in state.findings.items() if f.state == "present"}
    for tup in criteria.triage_tuples:
        if present & set(tup.findings_all):
            wanted.update(tup.findings_all)
            wanted.update(tup.risk_factors_any)
    # Always offer every finding a level-1/2 rule references, so an
    # unprompted "อ้วกเป็นเลือด" or a BEFAST opener is never dropped for
    # want of vocabulary. The Aug 5 extraction eval measured the previous
    # hand-maintained list at 30/60 on critical phrasings — worse, the model
    # substituted the nearest OFFERED id (a cold pale leg → the level-1
    # shock-skin finding). Criteria-derived, so new rules extend it for free.
    wanted.update(critical_finding_ids(criteria))
    # Every template's anchor finding(s), always: a patient who replaces their
    # complaint mid-interview ("that was my mother's fall — I'm here for a
    # sore throat") must be able to name the new one, and retract the old
    # one, in a vocabulary bounded to the current template. ~20 ids.
    for other in criteria.complaint_templates:
        wanted.update(other.anchor_finding_ids)
    # Turn 1 has no template yet, and the patient may open with ANY complaint.
    # A bounded vocabulary there is a chicken-and-egg: the finding that would
    # select the template is the one not offered. Measured 2026-08-10 — a Thai
    # "เวียนหัว" (dizziness) opener extracted NOTHING, because vertigo belongs
    # to the ear template and turn 1 never offers it.
    #
    # So on turn 1 we offer every finding any template asks about, derived from
    # the criteria rather than hand-listed: a hand-listed set is what scored
    # 30/60 in the Aug 5 eval, and it goes stale the moment a template changes.
    # ~+41 findings on the first prompt only; later turns stay bounded, which
    # is where precision matters.
    if not state.complaint_category:
        for other in criteria.complaint_templates:
            wanted.update(other.associated_finding_ids)
            for question in other.questions:
                wanted.update(question.finding_ids)
        # Two openers no template lists as an associated finding, but which
        # patients lead with constantly.
        wanted.update({"headache", "ear_pain"})

    # Labels in the session language only. The ids stay English (they are
    # identifiers, so code-switched "มี fever" still lands); the prose the
    # model matches against is the language the patient is speaking. Halves
    # the catalog, which is prefill time on a local model and option-list
    # noise for a small one. Measured 2026-08-21 (run_extraction_eval): no
    # change in pass rate against the bilingual catalog.
    thai = state.language == "th"
    lines = []
    for fid in sorted(wanted):
        entry = criteria.finding_catalog.get(fid)
        if entry is None:
            continue
        label = entry.label_th if thai else entry.label_en
        synonyms = ", ".join((entry.synonyms_th if thai else entry.synonyms_en)[:6])
        line = f"- {fid}: {label}"
        if synonyms:
            line += f" (also: {synonyms})"
        lines.append(line)
    return lines


def _pending_question_finding_ids(
    criteria: ScreeningCriteria, state: ScreeningState
) -> list[str]:
    """Finding ids the pending question checks, so a bare yes/no/'none of
    these' can be mapped mechanically instead of inferred from wording."""

    qid = state.pending_question_id
    if not qid:
        return []
    if qid.startswith("confirm_"):
        # Synthesized confirm-before-fire question — checks exactly one finding.
        return [qid.removeprefix("confirm_")]
    all_questions = [
        *criteria.universal_questions,
        *criteria.pre_disposition_questions,
        *(q for t in criteria.complaint_templates for q in t.questions),
    ]
    for question in all_questions:
        if question.id == qid:
            return list(question.finding_ids)
    return []


def build_extraction_prompt(
    criteria: ScreeningCriteria,
    state: ScreeningState,
    user_text: str,
    pending_question_text: str | None,
) -> str:
    categories = ", ".join(t.category for t in criteria.complaint_templates)
    catalog = "\n".join(_catalog_lines(criteria, state))
    context_lines = []
    if state.chief_complaint:
        context_lines.append(f"Chief complaint so far: {state.chief_complaint}")
    if pending_question_text:
        context_lines.append(f"The assistant just asked: {pending_question_text}")
        pending_fids = _pending_question_finding_ids(criteria, state)
        if pending_fids:
            context_lines.append(
                "That question checks exactly these finding ids: "
                + ", ".join(pending_fids)
            )
    context = "\n".join(context_lines) or "This is the first message."

    # Static part first (instructions, categories, catalog, rules), per-turn
    # part last: an OpenAI-compatible server with prefix caching (vLLM,
    # Ollama) then reuses the ~90% that does not change between turns.
    return f"""You are a clinical intake scribe for a Thai hospital. Read ONE patient message
(Thai or English) and extract ONLY what the patient actually said into the
structured schema. Never guess, never diagnose, never infer findings that were
not stated. If the message answers the assistant's pending question, record
that answer (as finding updates with state "absent" when the patient denies,
or slot/score updates).

Allowed complaint categories (copy ONE id verbatim — never invent or combine ids): {categories}
Pick the category from what the patient HAS, never from what they deny: "I have
a fever but no headache" / "มีไข้ แต่ไม่ปวดหัว" is fever, not headache.

Finding catalog (use ONLY these ids):
{catalog}

Rules:
- A denial ("no", "ไม่มีค่ะ", "none of these", "ไม่มีอาการเหล่านี้") of the pending
  question -> ALL of that question's finding ids with state "absent". A bare
  denial applies ONLY to the pending question's finding ids — never to other
  findings the question wording mentioned in passing.
- Explicit negations the patient volunteers anywhere in the message ("no fever
  though", "no trouble breathing", "แต่ไม่มีไข้", "หายใจปกติดี") -> those findings
  with state "absent" — including in the very first message. This applies to
  "X but no Y" sentences too: "I've had a fever since yesterday but no cough"
  -> fever "present" AND cough "absent"; "มีไข้ แต่ไม่ไอ ไม่เจ็บคอ" -> fever
  "present", cough "absent", sore_throat "absent". Never drop the negated
  finding just because the sentence also reports a positive one.
- A correction: when the patient says an earlier symptom was a mistake, has gone
  away, or was about someone else ("พูดผิด ไม่ได้ปวดท้อง", "หายแล้ว", "ไม่ได้เป็นแล้ว",
  "that was my mother, not me", "I was wrong about the sweating") -> that finding
  with state "absent", evidence = those words. If they replace their main problem
  ("จริงๆ แล้วมาเรื่องผื่น", "I'm actually here for a sore throat") -> also fill
  chief_complaint with the new problem and complaint_category with its category.
  Do NOT fill chief_complaint when they only add a symptom to the one they have.
- A bare affirmation ("yes", "ใช่", "มี") of a pending question that checks exactly
  ONE finding -> that finding id with state "present".
- A bare affirmation of a pending question that checks SEVERAL findings:
  if they are severity grades of the SAME symptom (e.g. dyspnea vs
  severe_respiratory_distress) -> record only the mildest as "present";
  if they are DISTINCT symptoms (e.g. confusion vs stiff_neck) -> record NO
  finding updates (the assistant will ask which one). When the patient names
  specific symptoms, record exactly those as "present".
- For EVERY finding update, fill evidence with the exact words from the
  patient's message that state it — copied verbatim, never paraphrased or
  translated. If you cannot quote supporting words, do not record the finding.
- Numbers 0-10 answering a pain/breathing question -> pain_score or distress_score.
- A timeframe answering when it started or how long it has lasted (e.g.
  "2-3 days", "since yesterday") -> fill BOTH slot_updates.onset and
  slot_updates.duration when the phrasing covers both, so neither is re-asked.
- Ages like "6 เดือน" -> age_years 0.5.
- complaint_category: whenever the patient states any symptom, pick the SINGLE
  closest category from the allowed list. If more than one could fit (e.g.
  sore throat + cough), pick the one matching the symptom they said first.
  Use null only when no category fits at all (e.g. a greeting or a question).
- wants_human=true only when they explicitly ask for a person/nurse/staff.

Context:
{context}

Patient message:
{user_text}"""
