"""Terminal nodes: repeat guidance after completion, nurse escalation."""

from __future__ import annotations

from .. import templates
from ..state import TurnOutput
from .base import GraphDeps, GraphState


def make_repeat_node(deps: GraphDeps):
    async def repeat(graph_state: GraphState) -> GraphState:
        state = graph_state["s"]
        language = state.language
        code = (state.classification or {}).get("department_code") or "opd_general"
        names = deps.department_names.get(code)
        department = (names or {}).get(language) or templates.department_display(code, language)
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
