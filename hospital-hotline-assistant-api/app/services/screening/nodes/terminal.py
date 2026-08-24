"""Terminal nodes: repeat guidance after completion, nurse escalation."""

from __future__ import annotations

from .. import templates
from ..state import TurnOutput
from .base import GraphDeps, GraphState
from .followup import _is_decline
from .question import _ACK_QUESTION_MARKERS

# "so where do I go?" / "ไปตรงไหนคะ" wants the guidance again, not a note.
_QUESTION_MARKERS = (*_ACK_QUESTION_MARKERS, "ที่ไหน", "ตรงไหน", "ยังไง", "อย่างไร", "where", "how ")


def make_repeat_node(deps: GraphDeps):
    async def repeat(graph_state: GraphState) -> GraphState:
        state = graph_state["s"]
        language = state.language
        code = (state.classification or {}).get("department_code") or "opd_general"
        names = deps.department_names.get(code)
        department = (names or {}).get(language) or templates.department_display(code, language)
        utterance = (graph_state.get("user_text") or "").strip()
        # Anything said after the disposition is kept for the nurse (it rides
        # in the SBAR with the follow-up note) — a retraction here is never
        # re-triaged, but it must not vanish either (measured 2026-08-22:
        # "พูดผิด ไม่ได้เจ็บหน้าอก" after an L2 got only the repeat line).
        low = utterance.lower()
        if (
            len(utterance) >= 2
            and not _is_decline(utterance)
            and not any(m in low for m in _QUESTION_MARKERS)
        ):
            state.patient_follow_up = (
                f"{state.patient_follow_up} | {utterance}"
                if state.patient_follow_up else utterance
            )
            reply = templates.POST_DISPOSITION_NOTED[language].format(department=department)
            return {
                "s": state,
                "output": TurnOutput(reply=reply, flow_complete=True, post_disposition=True),
            }
        reply = templates.REPEAT_GUIDANCE[language].format(department=department)
        return {"s": state, "output": TurnOutput(reply=reply)}

    return repeat


def make_escalate_node(deps: GraphDeps):
    async def escalate(graph_state: GraphState) -> GraphState:
        state = graph_state["s"]
        state.phase = "escalated_to_nurse"
        reply = templates.ESCALATION[state.language]
        audit = graph_state.get("audit") or []
        audit.append({"call_site": "escalation", "ok": True})
        return {"s": state, "audit": audit, "output": TurnOutput(reply=reply, escalated=True)}

    return escalate
