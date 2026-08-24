"""Question node: deterministic selection, LLM-rendered delivery.

Every question goes through one structured render call that returns a short
acknowledgement of what the patient just said, the question, and 3–4
tappable answer choices. Only ``slot``/``associated`` questions may be
reworded; red-flag, scale, measurement and confirm questions keep their
nurse-approved text verbatim (the code enforces it — the model's copy is
ignored) and only gain the acknowledgement in front. Everything is
validated; any failure falls back to the verbatim template + deterministic
chips, exactly as before.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from time import perf_counter

from pydantic import BaseModel, Field

from .. import templates
from ..persona import persona_block
from ..rules.criteria_models import QuestionTemplate
from ..rules.question_policy import (
    InterviewInputs,
    confirm_question_for,
    next_question,
)
from ..state import TurnOutput
from ..validator import validate_reply
from .base import GraphDeps, GraphState, ainvoke_with_timeout

logger = logging.getLogger(__name__)

# Every question may be reworded except a measurement request (it names a
# device action). Red-flag / scale / confirm rewordings are accepted only when
# ``wording_violations`` finds nothing — the paraphrase must still name every
# symptom the template names, keep the 0–10 scale, and ask exactly one
# question — otherwise the template goes out verbatim. The answer is mapped by
# finding id either way (extraction is told which ids the question checks,
# and the chips below carry the ids), so wording can lose a symptom but can
# never change what a yes/no means.
PARAPHRASABLE_KINDS = {"slot", "associated", "red_flag", "scale", "age", "gender", "intake"}
# Chips the model may author: only for the conversational kinds. Red-flag,
# scale and confirm chips stay deterministic because their ids ARE the
# answer mapping (one chip per finding, 0–10).
LLM_OPTION_KINDS = {"slot", "associated"}

_EN_STOPWORDS = {
    "with", "from", "that", "this", "than", "your", "have", "been", "more",
    "less", "very", "when", "into", "over", "past", "week", "today", "hours",
    "days", "right", "now", "any", "the", "and", "you", "are", "within",
    "symptoms", "signs", "other", "something", "someone", "sudden", "ever",
    "feeling", "feel", "after", "before", "since", "will", "would", "could",
    "should", "might", "does", "doing",
}
_SCALE_TOKENS = (("0", "zero", "ศูนย์"), ("10", "ten", "สิบ"))
# Kinds without finding ids still have one thing the rewording must keep.
_KIND_TERMS = {
    "age": {"en": ("age", "old"), "th": ("อายุ", "ปี")},
    "gender": {"en": ("male", "female", "sex", "gender"), "th": ("ชาย", "หญิง", "เพศ")},
}
# Thai marks a question with a particle, not word order: ไหม / หรือ… / a
# question word (ไหน covers แค่ไหน, ตรงไหน, ระดับไหน), or the rising-tone
# sentence-final คะ (ค่ะ with the tone mark is the statement particle).
_TH_QUESTION_MARKERS = ("ไหม", "มั้ย", "หรือเปล่า", "หรือไม่", "หรือยัง", "อะไร", "กี่", "เท่าไหร่", "เท่าไร", "เมื่อไหร่", "ไหน", "ยังไง", "อย่างไร", "?")
# A red-flag / associated question is answered yes/no (the chips carry the
# finding ids): a rewording that turns it into "how much / which / when"
# breaks the answer mapping — "ยังแน่นหน้าอกอยู่มากน้อยแค่ไหนคะ" (seen live).
_POLAR_KINDS = {"red_flag", "associated"}
_TH_WH = ("แค่ไหน", "เท่าไหร่", "เท่าไร", "อย่างไร", "ยังไง", "อะไร", "เมื่อไหร่", "ตรงไหน", "ที่ไหน", "กี่", "ข้างไหน", "ส่วนไหน", "แบบไหน")
_TH_POLAR = ("ไหม", "มั้ย", "หรือเปล่า", "หรือไม่", "หรือยัง")
# Sentence-initial only ("When did it start?" yes; "blood when you vomit" no).
_EN_WH = re.compile(r"(?:^|[.?!,;:—–-]\s*)(how|what|which|when|where|why|who)\b", re.IGNORECASE)


def _is_polar(text: str, language: str) -> bool:
    if language == "th":
        return not any(w in text for w in _TH_WH) and any(m in text for m in _TH_POLAR)
    return not _EN_WH.search(text)


def _norm(text: str) -> str:
    return "".join((text or "").split()).casefold()


def _stems(text: str) -> frozenset[str]:
    """Crude English stems (4-char prefixes of content words): 'confusion'
    and 'confused' meet at 'conf', 'stop' and 'stopping' at 'stop'."""
    return frozenset(
        w[:4] for w in re.findall(r"[a-z]+", text.lower())
        if len(w) >= 4 and w not in _EN_STOPWORDS
    )


# Words that name a symptom's CONTEXT rather than the symptom, so "fever"
# alone can never stand in for "stiff neck with fever".
_GENERIC_EN = frozenset({"feve", "pain", "bloo", "seve", "sudd", "rece", "hour", "inju", "symp", "usua", "norm"})
_GENERIC_TH = frozenset({"ไข้", "ปวด", "เลือด", "อาการ", "รุนแรง", "ฉับพลัน", "ชั่วโมง", "วัน"})
# "ร่วมกับไข้" is context ("with fever"), not a symptom: strip the connective too.
_TH_PREFIXES = ("ร่วมกับ", "มีอาการ", "รู้สึก", "อาการ", "มี", "เป็น")
_TH_SPLIT = re.compile(r"[/,;()\s]+")


def _th_cores(fdef) -> list[str]:
    """Thai 'cores': label / synonym parts with the verb-ish prefixes that
    Thai adds freely ("มีไข้" → "ไข้", "มีอาการซึม" → "ซึม") stripped."""
    cores: list[str] = []
    for item in [fdef.label_th, *fdef.synonyms_th]:
        for part in _TH_SPLIT.split(item or ""):
            part = part.strip()
            for pre in _TH_PREFIXES:
                if part.startswith(pre) and len(part) - len(pre) >= 2:
                    part = part[len(pre):]
                    break
            if len(part) >= 2 and part not in cores:
                cores.append(part)
    return cores


def _lcs_len(a: str, b: str) -> int:
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _th_has(core: str, text: str) -> bool:
    """Thai names ``core`` when it appears verbatim; when ≥ 70 % of it appears
    as ONE contiguous run ("ถ่ายเป็นเลือดสด" ↔ "ถ่ายเป็นเลือด"); or when it can
    be cut in two and both pieces appear in order, close together ("ถ่ายดำ" ↔
    "ถ่ายอุจจาระเป็นสีดำ", "อาเจียนเป็นเลือด" ↔ "อาเจียนออกมาเป็นเลือด" — Thai
    inserts words mid-phrase). Every cut is tried (no syllable segmenter);
    a cut inside a syllable just fails to match. The shared "เป็นเลือด" of
    vomiting-blood does NOT cover bloody stool under any of the three."""
    c, t = _norm(core), _norm(text)
    if c in t:
        return True
    n = len(c)
    if n >= 4 and _lcs_len(c, t) / n >= 0.7:
        return True
    min_half = 2 if n <= 6 else 3
    for k in range(min_half, n - min_half + 1):
        a, b = c[:k], c[k:]
        i = t.find(a)
        while i != -1:
            j = t.find(b, i + len(a))
            if j != -1 and j - i <= 3 * n:
                return True
            i = t.find(a, i + 1)
    return False


def finding_terms(fdef, language: str) -> list[str]:
    """Ways a sentence can name one finding (for the prompt's keep-line)."""
    if language == "th":
        return _th_cores(fdef)
    terms: list[str] = []
    for item in [fdef.label_en, *fdef.synonyms_en]:
        for part in re.split(r"[/,;()]", item or ""):
            part = part.strip()
            if len(part) >= 2 and part not in terms:
                terms.append(part)
    return terms


def _required_marks(question, fid: str, verbatim: str, criteria, language: str) -> frozenset[str]:
    return _marks(question, fid, verbatim, criteria, language)[1]


def _marks(question, fid: str, verbatim: str, criteria, language: str) -> tuple[frozenset[str], frozenset[str]]:
    """The distinctive marks of finding ``fid`` that the TEMPLATE uses —
    English stems / Thai cores from its label + synonyms that occur in the
    verbatim question, minus context words and minus anything shared with
    the question's other findings. Empty = the template never names it, so
    nothing is required for it (uq_breathing never says 'severe respiratory
    distress')."""

    fdef = criteria.finding_catalog.get(fid) if criteria is not None else None
    if fdef is None:
        return frozenset(), frozenset()
    others = [
        criteria.finding_catalog.get(o) for o in question.finding_ids
        if o != fid and criteria.finding_catalog.get(o) is not None
    ]
    if language == "th":
        all_marks = set(_th_cores(fdef))
        in_template = {c for c in all_marks if _th_has(c, verbatim)}
        shared = {c for o in others for c in _th_cores(o)}
        generic = _GENERIC_TH
    else:
        all_marks = set()
        for term in finding_terms(fdef, language):
            all_marks |= _stems(term)
        in_template = all_marks & _stems(verbatim)
        shared = set().union(*(_stems(" ".join(finding_terms(o, language))) for o in others)) if others else set()
        generic = _GENERIC_EN
    if not in_template:
        return frozenset(), frozenset()  # the template never names it → unguarded
    # What the template used for THIS finding, preferring marks that are
    # neither another finding's nor pure context — but a finding whose only
    # mark is a "context" word (fever itself) keeps that mark.
    required = in_template - shared - generic
    if not required:
        required = in_template - shared
    if not required:
        required = in_template
    # …and the rewording may instead name it by any other distinctive mark
    # of its own ("trouble hearing" for a template that said "hearing loss").
    return frozenset(in_template), frozenset(required | (all_marks - shared - generic))


def _names_any(marks: frozenset[str], text: str, language: str) -> bool:
    if language == "th":
        return any(_th_has(m, text) for m in marks)
    return bool(marks & _stems(text))


def wording_violations(question, verbatim: str, paraphrase: str, criteria, language: str) -> list[str]:
    """Why a rewording of ``question`` may NOT replace the template.

    Deterministic, no model: every finding the TEMPLATE names (by label or
    synonym) must still be named in the paraphrase; a scale keeps its 0 and
    10; exactly one question; bounded length. Empty list = acceptable."""

    p = _norm(paraphrase)
    problems: list[str] = []
    if not p:
        return ["empty"]
    for fid in question.finding_ids:
        marks = _required_marks(question, fid, verbatim, criteria, language)
        if marks and not _names_any(marks, paraphrase, language):
            problems.append(f"missing:{fid}")
    # Only when the template itself is yes/no (inj_mechanism is "how did it
    # happen" by design).
    if question.kind in _POLAR_KINDS and _is_polar(verbatim, language) and not _is_polar(paraphrase, language):
        problems.append("not_yes_no")
    if question.kind == "scale" and not all(
        any(tok in paraphrase.lower() for tok in group) for group in _SCALE_TOKENS
    ):
        problems.append("missing:scale_0_10")
    for term_lang, terms in _KIND_TERMS.get(question.kind, {}).items():
        if term_lang == language and not any(_norm(t) in p for t in terms):
            problems.append(f"missing:{question.kind}")
    if language == "th":
        if not (
            any(m in paraphrase for m in _TH_QUESTION_MARKERS)
            or paraphrase.rstrip(" .!").endswith("คะ")
        ):
            problems.append("not_a_question")
    elif paraphrase.count("?") != 1:
        problems.append("question_count")
    if len(paraphrase) > max(2 * len(verbatim), len(verbatim) + 80):
        problems.append("too_long")
    return problems

_MAX_OPTION_CHARS = 40
_MAX_OPTIONS = 4


class PhrasedQuestion(BaseModel):
    """Structured render: acknowledgement + question + tappable answers."""

    ack: str = Field(
        default="",
        description=(
            "One short clause acknowledging what the patient just said, with no "
            "question in it; empty when there is nothing to acknowledge"
        ),
    )
    question: str = Field(description="The screening question to ask next")
    options: list[str] = Field(
        default_factory=list,
        description=(
            "3 or 4 short, mutually distinct answer choices the patient "
            "could tap, in the same language as the question"
        ),
    )


_PARAPHRASE_PROMPT = {
    "en": (
        "{persona}\n"
        "You are in the middle of a screening conversation. Recent exchange:\n{recent}\n"
        "Patient context: {context}\n"
        "Already answered — do not re-ask: {known}\n"
        "First, write `ack`: one short clause (under 12 words) that acknowledges what "
        "the patient just said, warmly and without repeating it back at length. It must "
        "not contain a question, advice, or reassurance about the outcome. Vary it — "
        "never reuse the wording of your previous line; a single word or nothing at "
        "all is often best. Leave it empty if there is nothing to acknowledge.\n"
        "{instruction}\n"
        "Also provide 3 or 4 short answer choices (max 30 characters each) the patient "
        "could tap to answer, in English, mutually distinct, covering the most likely "
        "answers; never include diagnoses, levels, or medication.\n"
        "Question: {question}"
    ),
    "th": (
        "{persona}\n"
        "คุณกำลังอยู่ระหว่างการสนทนาคัดกรอง บทสนทนาล่าสุด:\n{recent}\n"
        "บริบทผู้ป่วย: {context}\n"
        "ข้อมูลที่ผู้ป่วยตอบแล้ว ห้ามถามซ้ำ: {known}\n"
        "ขั้นแรก เขียน `ack`: วลีสั้น ๆ หนึ่งวลี (ไม่เกิน 15 คำ) ที่รับรู้สิ่งที่ผู้ป่วยเพิ่งบอกอย่างอบอุ่น "
        "โดยไม่ทวนซ้ำยาว ห้ามมีคำถาม คำแนะนำ หรือคำปลอบใจเรื่องผลลัพธ์ "
        "เปลี่ยนถ้อยคำทุกครั้ง ห้ามใช้คำเดิมกับประโยคก่อนหน้าของคุณ บ่อยครั้งคำเดียว (เช่น ค่ะ เข้าใจค่ะ) "
        "หรือไม่ต้องมีเลยจะดีที่สุด เว้นว่างไว้หากไม่มีอะไรต้องรับรู้\n"
        "{instruction}\n"
        "พร้อมกันนี้ให้เสนอตัวเลือกคำตอบสั้น ๆ 3 หรือ 4 ตัวเลือก (ไม่เกิน 30 ตัวอักษรต่อตัวเลือก) "
        "เป็นภาษาไทย แตกต่างกันชัดเจน ครอบคลุมคำตอบที่เป็นไปได้ "
        "ห้ามมีการวินิจฉัย ระดับการคัดกรอง หรือชื่อยา\n"
        "คำถาม: {question}"
    ),
}

# What to do with the question text, by kind.
_REPHRASE_INSTRUCTION = {
    "en": (
        "Then write `question`: rephrase the question below conversationally, preserving "
        "its exact clinical meaning. Exactly ONE question, one or two short sentences, "
        "no lists, no medical jargon. Do NOT re-ask anything already answered."
    ),
    "th": (
        "จากนั้นเขียน `question`: เรียบเรียงคำถามด้านล่างให้เป็นธรรมชาติ โดยคงความหมายทางคลินิกเดิมทุกประการ "
        "ถามเพียงหนึ่งคำถาม ความยาวหนึ่งถึงสองประโยคสั้น ๆ ห้ามใช้ศัพท์แพทย์ ห้ามถามซ้ำสิ่งที่ตอบแล้ว"
    ),
}
# Appended for red-flag / scale rewordings: the words the check will look for.
_KEEP_TERMS_LINE = {
    "en": "Keep every one of these symptoms in the question, in these words or their everyday equivalents: {terms}",
    "th": "คำถามต้องยังคงถามถึงอาการเหล่านี้ทุกข้อ ใช้คำเหล่านี้หรือคำพูดทั่วไปที่มีความหมายเดียวกัน: {terms}",
}


def keep_terms_line(question, verbatim: str, criteria, language: str) -> str:
    """The symptom words a rewording must keep, for the prompt ('' if none)."""
    names: list[str] = []
    said: set[str] = set()  # what the template says about findings listed so far
    for fid in question.finding_ids:
        in_template, marks = _marks(question, fid, verbatim, criteria, language)
        fdef = criteria.finding_catalog.get(fid) if criteria is not None else None
        if not marks or fdef is None:
            continue
        # A finding the template names only with words already used for an
        # earlier one is a severity grade of the same symptom (uq_breathing:
        # dyspnea / severe respiratory distress). Hand the model only the
        # first — listing the severe grade's terms made it ask "severe
        # trouble breathing … full sentences?", which a mildly breathless
        # patient answers "no".
        if in_template <= said:
            continue
        said |= in_template
        if language == "th":
            present = sorted(marks, key=len, reverse=True)
        else:
            present = [t for t in finding_terms(fdef, language) if _stems(t) & marks]
        if present:
            names.append(" / ".join(present[:3]))
    if question.kind == "scale":
        names.append("0–10")
    if not names:
        return ""
    return _KEEP_TERMS_LINE[language].format(terms="; ".join(names))
_VERBATIM_INSTRUCTION = {
    "en": (
        "Then copy the question below into `question` EXACTLY as written — it is "
        "nurse-approved wording and must not be changed."
    ),
    "th": (
        "จากนั้นคัดลอกคำถามด้านล่างลงใน `question` ให้ตรงตามต้นฉบับทุกตัวอักษร "
        "เป็นถ้อยคำที่พยาบาลอนุมัติแล้ว ห้ามแก้ไข"
    ),
}

_ROLE_LABEL = {
    "en": {"patient": "Patient", "assistant": "You"},
    "th": {"patient": "ผู้ป่วย", "assistant": "คุณ"},
}
# An acknowledgement must never smuggle in a second question.
_ACK_QUESTION_MARKERS = ("?", "ไหม", "มั้ย", "หรือเปล่า", "หรือไม่", "ใช่ไหม", "หรือยัง")
_ACK_MAX_CHARS = 90


def recent_exchange_lines(state, language: str) -> str:
    """The last exchanges as labelled lines for the render prompt ('-' when
    the conversation has only just started)."""
    labels = _ROLE_LABEL.get(language, _ROLE_LABEL["en"])
    lines = [
        f"{labels.get(turn.get('role', 'patient'), turn.get('role'))}: {turn.get('text', '')}"
        for turn in (state.recent_turns or [])
        if turn.get("text")
    ]
    return "\n".join(lines) or "-"


def clean_ack(raw: str | None, language: str) -> str:
    """Accept the model's acknowledgement only when it is short and carries
    no question; otherwise drop it (the question still goes out)."""
    ack = (raw or "").strip()
    if not ack or len(ack) > _ACK_MAX_CHARS:
        return ""
    if any(marker in ack for marker in _ACK_QUESTION_MARKERS):
        return ""
    if validate_reply(ack, language=language):
        return ""
    return ack


def interview_inputs(state, deps: GraphDeps) -> InterviewInputs:
    return InterviewInputs(
        complaint_category=state.complaint_category,
        findings=state.finding_states(),
        answered_slots=state.answered_slots(),
        asked_question_ids=frozenset(state.asked_question_ids),
        age_known=state.age_years is not None,
        age_years=state.age_years,
        measured_vitals=frozenset(state.vitals),
        questions_asked=state.questions_asked,
        question_budget=deps.question_budget,
        # duplicates appear when a red flag is re-asked (list, not set)
        ask_counts=Counter(state.asked_question_ids),
        gender=state.gender,
    )


def known_answers_line(state) -> str:
    """Summarize what the patient already told us, so the paraphrase never
    re-asks it (the demo showed onset re-asked as duration)."""

    parts = [f"{slot}: {answer}" for slot, answer in state.slots.items()]
    present = [fid for fid, f in state.findings.items() if f.state == "present"]
    if present:
        parts.append("reported: " + ", ".join(present))
    return "; ".join(parts) or "-"


def localize_options(
    question: QuestionTemplate, language: str, criteria=None
) -> list[dict[str, str]]:
    """Deterministic reply chips (authored/default) — used for verbatim kinds
    and as the fallback when the structured paraphrase yields no usable options.
    Measurement questions never get chips."""

    if question.kind == "measurement":
        return []
    if question.options:
        return [
            {
                "id": opt.id,
                "label": opt.text_th if language == "th" else opt.text_en,
            }
            for opt in question.options
        ]
    if question.kind in ("red_flag", "associated") or question.id == "uq_breathing":
        # A compound red flag ("confusion, trouble breathing, or stiff neck?")
        # answered with a bare Yes is unmappable — a live demo undertriaged a
        # yes-to-meningitis-signs to level 4 because no finding was recorded.
        # Offer one chip per finding plus "None of these" so a tap is always
        # unambiguous.
        # uq_breathing's findings are severity grades of one symptom — plain
        # Yes/No reads naturally and extraction maps a bare yes to the milder
        # grade; per-finding chips are for questions bundling DISTINCT symptoms.
        if (
            question.kind == "red_flag"
            and question.id != "uq_breathing"
            and criteria is not None
            and len(question.finding_ids) > 1
        ):
            chips: list[dict[str, str]] = []
            for fid in question.finding_ids:
                fdef = criteria.finding_catalog.get(fid)
                if fdef is None:
                    break
                chips.append({
                    "id": fid,
                    "label": fdef.label_th if language == "th" else fdef.label_en,
                })
            else:
                chips.append({
                    "id": "none_of_these",
                    "label": templates.NONE_OF_THESE.get(
                        language, templates.NONE_OF_THESE["en"]
                    ),
                })
                return chips
        return list(templates.YES_NO_OPTIONS.get(language, templates.YES_NO_OPTIONS["en"]))
    if question.kind == "scale":
        return [{"id": str(i), "label": str(i)} for i in range(11)]
    return []


def _accept_options(raw: list[str], language: str) -> list[dict[str, str]]:
    """Keep LLM options only when they're clean, short, and 2–4 distinct."""

    cleaned: list[str] = []
    for item in raw:
        label = (item or "").strip()
        if not label or len(label) > _MAX_OPTION_CHARS:
            continue
        if validate_reply(label, language=language):
            continue  # validator violation (level/diagnosis leak) — drop all
        if label.lower() in (c.lower() for c in cleaned):
            continue
        cleaned.append(label)
        if len(cleaned) == _MAX_OPTIONS:
            break
    if len(cleaned) < 2:
        return []
    return [{"id": f"opt_{i + 1}", "label": label} for i, label in enumerate(cleaned)]


def make_question_node(deps: GraphDeps):
    async def question(graph_state: GraphState) -> GraphState:
        state = graph_state["s"]
        criteria = graph_state["criteria"]
        audit = graph_state.get("audit") or []

        is_confirm = bool(state.pending_confirm)
        if is_confirm:
            # Confirm-before-fire: a level-1/2 verdict is waiting on this
            # extraction-sourced finding. Its confirm question may be reworded
            # like any red flag (the meaning check keeps the symptom named);
            # the answer maps by finding id either way.
            selected = confirm_question_for(
                criteria, state.pending_confirm[0], state.complaint_category
            )
        else:
            selected = next_question(criteria, interview_inputs(state, deps))
        if selected is None:
            # Router guarantees a question exists; guard anyway.
            state.phase = "history"
            return {"s": state, "audit": audit}

        verbatim = selected.text_en if state.language == "en" else selected.text_th
        reply = verbatim
        reply_options = localize_options(selected, state.language, criteria)

        # Re-asking for a value we just refused: lead with the nurse-approved
        # reason, verbatim, so the patient knows what was wrong instead of
        # seeing the same question again.
        rejection = (
            state.rejected_vitals.get(selected.vital or "")
            if selected.kind == "measurement"
            else None
        )
        if rejection:
            key = "text_en" if state.language == "en" else "text_th"
            explanation = str(rejection.get(key) or "").strip()
            if explanation:
                reply = f"{explanation}\n\n{verbatim}"

        paraphrasable = selected.kind in PARAPHRASABLE_KINDS
        # A refused-value re-ask keeps its nurse-approved lead-in and goes out
        # as-is; everything else is rendered (ack + question) by the model.
        if deps.model is not None and not rejection:
            instruction_text = (
                _REPHRASE_INSTRUCTION if paraphrasable else _VERBATIM_INSTRUCTION
            )[state.language]
            if paraphrasable:
                keep = keep_terms_line(selected, verbatim, criteria, state.language)
                if keep:
                    instruction_text = f"{instruction_text}\n{keep}"
            prompt = _PARAPHRASE_PROMPT[state.language].format(
                persona=persona_block(state.language),
                recent=recent_exchange_lines(state, state.language),
                context=state.chief_complaint or "-",
                known=known_answers_line(state),
                instruction=instruction_text,
                question=verbatim,
            )
            started = perf_counter()
            ok = False
            ack_used = False
            paraphrased = False
            rejected: list[str] = []
            try:
                structured = deps.model.with_structured_output(PhrasedQuestion)
                phrased = await ainvoke_with_timeout(
                    structured, prompt, deps.model_timeout_s
                )
                ack = clean_ack(phrased.ack, state.language)
                question_text = verbatim
                if paraphrasable and (phrased.question or "").strip():
                    candidate_q = phrased.question.strip()
                    rejected = wording_violations(
                        selected, verbatim, candidate_q, criteria, state.language
                    )
                    if not rejected:
                        question_text = candidate_q
                candidate = " ".join(part for part in (ack, question_text) if part)
                if not validate_reply(candidate, language=state.language):
                    reply = candidate
                    ok = True
                    ack_used = bool(ack)
                    paraphrased = question_text != verbatim
                    if selected.kind in LLM_OPTION_KINDS:
                        llm_options = _accept_options(phrased.options, state.language)
                        if llm_options:
                            reply_options = llm_options
            except Exception:
                logger.exception("question render failed; using verbatim template")
            audit.append({
                "call_site": "question",
                "latency_ms": int((perf_counter() - started) * 1000),
                "ok": ok,
                "question_id": selected.id,
                "ack_used": ack_used,
                "paraphrased": paraphrased,
                # Why the model's rewording was refused (template used instead).
                **({"paraphrase_rejected": rejected} if rejected else {}),
            })

        state.asked_question_ids.append(selected.id)
        # Measurement requests don't count against the interview budget: they
        # are booth actions, not questions the patient must think about, and
        # the policy's ask-count cap guarantees each fires at most twice. The
        # budget must stay a cap on cognitive burden, not on readings.
        if selected.kind != "measurement":
            state.questions_asked += 1
        state.pending_question_id = selected.id
        # A measurement question asks the booth to take a reading (e.g.
        # temperature); the transport layer pops a numeric input for it.
        state.awaiting_measurement = selected.vital if selected.kind == "measurement" else None
        state.phase = "history"
        return {
            "s": state,
            "audit": audit,
            "output": TurnOutput(
                reply=reply,
                awaiting_measurement=state.awaiting_measurement,
                reply_options=reply_options,
            ),
        }

    return question
