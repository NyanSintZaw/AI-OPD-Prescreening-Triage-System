"""Post-disposition follow-up capture — keyword matcher + LLM backstop.

After a non-emergency disposition the explain node offers a follow-up. This
node handles the patient's reply: decline → close; bare yes → ask what to
note; anything else → record verbatim and acknowledge. Never answers medically.
Before storing a "note" (which is later pushed to HIS) the LLM backstop
double-checks it isn't a free-phrased decline the regex missed.
"""

from __future__ import annotations

import re

from .. import templates
from ..nlu_backstop import confirm_gate
from ..state import TurnOutput
from .base import GraphDeps, GraphState

# A decline/affirmation is any sequence of the listed tokens separated by
# spaces or light punctuation ("No, nothing else." / "ไม่มีค่ะ ขอบคุณค่ะ").
# Anything with real content (incl. a "?") falls through to being recorded.
# Thai polite particles may ride along with either, but a decline needs at
# least one substantive negative token — a bare "ครับ/ค่ะ" is an affirmation.
_POLITE = r"(?:ครับผม|ครับ|ค่ะ|คะ|นะ|แล้ว|เลย|จ้ะ|จ้า)"
_NEG_CORE = (
    r"(?:no|nope|nothing(?:\s+else)?|none|not\s+really|that'?s\s+(?:all|it)|"
    r"there\s+(?:isn'?t|is\s+not?)\s+anything(?:\s+else)?|"
    r"there'?s\s+nothing(?:\s+else)?|"
    r"i\s+(?:don'?t|do\s+not)\s+have\s+any(?:thing)?(?:\s+else)?|"
    r"(?:i'?m|i\s+am|we'?re)\s+done|nothing\s+to\s+(?:ask|add|tell|say)|"
    r"all\s+good|i'?m\s+(?:good|fine|ok|okay)|no\s+thanks?|thanks|thank\s+you|"
    r"ไม่มีอะไร(?:จะถาม|จะบอก|เพิ่มเติม)?(?:แล้ว)?|ไม่มี|ไม่ต้องการ|ไม่เป็นไร|ไม่|"
    r"แค่นี้|พอแล้ว|เสร็จแล้ว|จบแล้ว|ขอบคุณ)"
)
_NEG_TOKEN = rf"(?:{_NEG_CORE}|{_POLITE})"
_AFF_TOKEN = (
    r"(?:yes|yeah|yep|sure|ok|okay|please|i\s+do|"
    r"i\s+have\s+(?:a\s+)?(?:question|one)|"
    rf"มีคำถาม|อยากถาม|มี|ใช่|ได้|{_POLITE})"
)
# Optional separator: Thai writes polite particles without spaces
# ("ไม่มีค่ะ" = ไม่มี + ค่ะ), so tokens may join directly.
_SEP = r"[\s,.!]*"
_NEGATIVE = re.compile(
    rf"^\s*{_NEG_TOKEN}(?:{_SEP}{_NEG_TOKEN})*[\s,.!]*$", re.IGNORECASE
)
_NEG_CORE_RE = re.compile(_NEG_CORE, re.IGNORECASE)
_AFFIRMATIVE = re.compile(
    rf"^\s*{_AFF_TOKEN}(?:{_SEP}{_AFF_TOKEN})*[\s,.!]*$", re.IGNORECASE
)


def _is_decline(utterance: str) -> bool:
    return bool(_NEGATIVE.match(utterance) and _NEG_CORE_RE.search(utterance))


def _department_label(state, deps: GraphDeps) -> str:
    code = state.classification.get("department_code") or "opd_general"
    names = deps.department_names.get(code)
    return (names or {}).get(state.language) or templates.department_display(
        code, state.language
    )


def make_followup_node(deps: GraphDeps):
    async def followup(graph_state: GraphState) -> GraphState:
        state = graph_state["s"]
        language = state.language
        utterance = (graph_state.get("user_text") or "").strip()
        department = _department_label(state, deps)
        audit = graph_state.get("audit") or []

        def close_declined() -> GraphState:
            state.phase = "done"
            return {
                "s": state,
                "audit": audit,
                "output": TurnOutput(
                    reply=templates.follow_up_close(
                        state.patient_name, department, language
                    ),
                    classification=state.classification,
                    flow_complete=True,
                    post_disposition=True,
                ),
            }

        if _is_decline(utterance):
            return close_declined()

        if _AFFIRMATIVE.match(utterance):
            # Stay in follow_up waiting for the actual note; no Yes/No chips.
            return {
                "s": state,
                "output": TurnOutput(
                    reply=templates.FOLLOW_UP_PROMPT[language],
                    classification=state.classification,
                    flow_complete=False,
                    post_disposition=True,
                ),
            }

        # Sub-2-char scraps ("k", ".", a stray "ๆ") carry no note worth
        # pushing to HIS — close them as a decline-equivalent ack.
        if len(utterance) < 2:
            return close_declined()

        # Regex says content and we're about to store it as the HIS note —
        # the LLM backstop rescues free-phrased declines the regex vocabulary
        # misses (live 2026-07-27: "ไม่มีแล้วค่ะ ขอบคุณค่ะ" was noted for the
        # doctor). "content"/"unclear"/failure → store exactly as today.
        if deps.model is not None:
            verdict = await confirm_gate(
                deps.model, "followup_decline", utterance, language
            )
            audit.append({
                "call_site": "gate_backstop",
                "latency_ms": verdict.latency_ms,
                "ok": verdict.ok,
                "kind": "followup_decline",
                "regex_verdict": "content",
                "llm_verdict": str(verdict),
            })
            if verdict == "decline":
                return close_declined()

        # Anything else is the note itself (or a direct question to record).
        state.patient_follow_up = utterance
        reply = templates.follow_up_ack(state.patient_name, department, language)
        state.phase = "done"
        return {
            "s": state,
            "audit": audit,
            "output": TurnOutput(
                reply=reply,
                classification=state.classification,
                flow_complete=True,
                post_disposition=True,
                # Keep empty options on the closing turn.
            ),
        }

    return followup
