"""LLM backstop behind the regex flow gates (followup / identity / resume).

Regex (``nlu_yesno``, ``nodes/followup``) stays the deterministic fast path.
This module is consulted ONLY when the regex verdict would trigger an
irreversible or risky action (storing a "note" that is really a decline,
consuming an identity retry, falling back to the resume chooser). One small
structured LLM call classifies the utterance; on ANY failure, timeout, or
invalid output the verdict is "unclear" and callers behave exactly as today —
the backstop can only help, never block.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Literal

from pydantic import BaseModel

from .nodes.base import ainvoke_with_timeout

logger = logging.getLogger(__name__)

# Hard cap per backstop call — a gate answer is worth at most this much delay.
BACKSTOP_TIMEOUT_S = 5.0

GateKind = Literal["followup_decline", "identity_yesno", "resume_choice"]


class GateResult(str):
    """Verdict string carrying audit metadata (latency, ok, raw verdict).

    Being a ``str`` subclass keeps call sites trivial (``verdict == "yes"``)
    while ``verdict.latency_ms`` / ``verdict.ok`` feed the audit trail.
    """

    latency_ms: int
    ok: bool
    raw: str | None

    def __new__(
        cls,
        verdict: str,
        *,
        latency_ms: int = 0,
        ok: bool = False,
        raw: str | None = None,
    ) -> "GateResult":
        self = super().__new__(cls, verdict)
        self.latency_ms = latency_ms
        self.ok = ok
        self.raw = raw
        return self


class _FollowupVerdict(BaseModel):
    verdict: Literal["decline", "content", "unclear"]


class _IdentityVerdict(BaseModel):
    verdict: Literal["yes", "no", "unclear"]


class _ResumeVerdict(BaseModel):
    verdict: Literal["continue", "start_over", "unclear"]


_SCHEMAS: dict[str, type[BaseModel]] = {
    "followup_decline": _FollowupVerdict,
    "identity_yesno": _IdentityVerdict,
    "resume_choice": _ResumeVerdict,
}

# Classification only — the model never generates patient-facing text.
# Utterances may be Thai or English regardless of the session language.
_PROMPTS: dict[str, str] = {
    "followup_decline": (
        "A hospital kiosk assistant just asked the patient (in Thai or "
        "English): 'Is there anything else you would like to ask, or "
        "anything to note for the doctor?'\n"
        "Classify the patient's reply below. Answer with exactly one "
        "verdict:\n"
        "- decline: the reply only declines or politely closes the "
        "conversation (e.g. 'No, nothing else', 'I'm done, thanks', "
        "'no worries, I'm all set', 'ไม่มีแล้วค่ะ ขอบคุณค่ะ')\n"
        "- content: the reply contains an actual question, symptom, or note "
        "the doctor should see\n"
        "- unclear: cannot tell\n"
        "Session language: {language}. Context: {context}\n"
        "Patient reply: {utterance!r}"
    ),
    # No name here on purpose: the task is "did they confirm or deny", which
    # the reply answers on its own. Sending the name would put an identifier
    # on the wire for nothing. See docs/ai-model-io.md.
    "identity_yesno": (
        "A hospital kiosk showed the patient the name on their record and "
        "asked 'is this you?'\n"
        "Classify the patient's reply below (Thai or English). Answer with "
        "exactly one verdict:\n"
        "- yes: the reply confirms it is them\n"
        "- no: the reply says it is not them / wrong name / wrong person\n"
        "- unclear: cannot tell (off-topic, ambiguous)\n"
        "Session language: {language}.\n"
        "Patient reply: {utterance!r}"
    ),
    "resume_choice": (
        "A hospital kiosk found the patient's earlier assessment "
        "(status: {context}) and asked whether they want to CONTINUE it or "
        "START OVER with a new one.\n"
        "Classify the patient's reply below (Thai or English). Answer with "
        "exactly one verdict:\n"
        "- continue: they want to pick up the earlier assessment\n"
        "- start_over: they want a fresh assessment from the beginning\n"
        "- unclear: cannot tell\n"
        "Session language: {language}.\n"
        "Patient reply: {utterance!r}"
    ),
}


async def confirm_gate(
    model,
    kind: GateKind,
    utterance: str,
    language: str,
    context: str = "",
) -> GateResult:
    """Ask the screening LLM to second-guess a regex gate verdict.

    Returns a gate-specific verdict (see ``_SCHEMAS``); "unclear" on any
    failure so callers can always fall through to today's behavior.
    """
    text = (utterance or "").strip()
    if model is None or not text:
        return GateResult("unclear")

    prompt = _PROMPTS[kind].format(
        utterance=text, language=language, context=context or "-"
    )
    started = perf_counter()
    try:
        result = await ainvoke_with_timeout(
            model.with_structured_output(_SCHEMAS[kind]), prompt, BACKSTOP_TIMEOUT_S
        )
        latency_ms = int((perf_counter() - started) * 1000)
        verdict = _SCHEMAS[kind].model_validate(result).verdict  # type: ignore[attr-defined]
        return GateResult(verdict, latency_ms=latency_ms, ok=True, raw=verdict)
    except Exception:
        latency_ms = int((perf_counter() - started) * 1000)
        logger.warning("gate backstop %s failed (fall through to regex)", kind,
                       exc_info=True)
        return GateResult("unclear", latency_ms=latency_ms, ok=False)
