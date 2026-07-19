"""Post-disposition follow-up capture — pure keyword matcher, no LLM.

After a non-emergency disposition the explain node offers a follow-up. This
node handles the patient's reply: decline → close; bare yes → ask what to
note; anything else → record verbatim and acknowledge. Never answers medically.
"""

from __future__ import annotations

import re

from .. import templates
from ..state import TurnOutput
from .base import GraphDeps, GraphState

# A decline/affirmation is any sequence of the listed tokens separated by
# spaces or light punctuation ("No, nothing else." / "ไม่มีค่ะ ขอบคุณค่ะ").
# Anything with real content (incl. a "?") falls through to being recorded.
# Thai polite particles may ride along with either, but a decline needs at
# least one substantive negative token — a bare "ครับ/ค่ะ" is an affirmation.
_POLITE = r"(?:ครับผม|ครับ|ค่ะ|คะ|นะ|แล้ว|เลย|จ้ะ|จ้า)"
_NEG_CORE = (
    r"(?:no|nope|nothing(?:\s+else)?|none|not\s+really|that'?s\s+all|"
    r"all\s+good|i'?m\s+(?:good|fine|ok|okay)|no\s+thanks?|thanks|thank\s+you|"
    r"ไม่มีอะไร(?:จะถาม|เพิ่มเติม)?(?:แล้ว)?|ไม่มี|ไม่ต้องการ|ไม่เป็นไร|ไม่|"
    r"แค่นี้|พอแล้ว|ขอบคุณ)"
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

        if _is_decline(utterance):
            reply = templates.FOLLOW_UP_CLOSE[language].format(department=department)
            state.phase = "done"
            return {
                "s": state,
                "output": TurnOutput(
                    reply=reply,
                    classification=state.classification,
                    flow_complete=True,
                    post_disposition=True,
                ),
            }

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

        # Anything else is the note itself (or a direct question to record).
        if utterance:
            state.patient_follow_up = utterance
        reply = templates.FOLLOW_UP_ACK[language].format(department=department)
        state.phase = "done"
        return {
            "s": state,
            "output": TurnOutput(
                reply=reply,
                classification=state.classification,
                flow_complete=True,
                post_disposition=True,
                # Keep empty options on the closing turn.
            ),
        }

    return followup
