"""The screening interview graph.

One bounded invocation per chat turn. All routing decisions are pure
functions over state + criteria (the LLM never chooses the path):

    entry ─┬─ phase escalated ─────────► escalate ─► END
           ├─ phase follow_up ─────────► followup ─► END
           ├─ phase disposed/done ─────► repeat ─► END
           └─ else ─► ingest ─┬─ escalated ─► escalate ─► END
                              ├─ complete (incl. red-flag L1/L2) ─► dispose ─► explain ─► END
                              └─ else ─► question ─► END
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes.base import GraphDeps, GraphState
from .nodes.dispose import make_dispose_node
from .nodes.explain import make_explain_node
from .nodes.followup import make_followup_node
from .nodes.ingest import make_ingest_node
from .nodes.question import interview_inputs, make_question_node
from .nodes.terminal import make_escalate_node, make_repeat_node
from .rules.disposition import decide
from .rules.question_policy import is_interview_complete, next_question


def build_screening_graph(deps: GraphDeps):
    graph = StateGraph(GraphState)
    graph.add_node("ingest", make_ingest_node(deps))
    graph.add_node("question", make_question_node(deps))
    graph.add_node("dispose", make_dispose_node(deps))
    graph.add_node("explain", make_explain_node(deps))
    graph.add_node("followup", make_followup_node(deps))
    graph.add_node("repeat", make_repeat_node(deps))
    graph.add_node("escalate", make_escalate_node(deps))

    def route_entry(gs: GraphState) -> str:
        phase = gs["s"].phase
        if phase == "escalated_to_nurse":
            return "escalate"
        if phase == "follow_up":
            return "followup"
        if phase in ("disposed", "done"):
            return "repeat"
        return "ingest"

    graph.set_conditional_entry_point(
        route_entry,
        {
            "escalate": "escalate",
            "followup": "followup",
            "repeat": "repeat",
            "ingest": "ingest",
        },
    )

    def route_after_ingest(gs: GraphState) -> str:
        state = gs["s"]
        criteria = gs["criteria"]
        if state.phase == "escalated_to_nurse":
            return "escalate"
        # Red-flag gate + completeness gate, both deterministic. decide()
        # puts level-1/2 red-flag hits first, and is_interview_complete
        # returns True immediately for a provisional level <= 2.
        provisional = decide(
            findings=state.finding_states(),
            vitals=state.vitals,
            age_years=state.age_years,
            complaint_category=state.complaint_category,
            criteria=criteria,
        )
        inputs = interview_inputs(state, deps)
        if is_interview_complete(criteria, inputs, provisional.level):
            return "dispose"
        if next_question(criteria, inputs) is None:
            return "dispose"
        return "question"

    graph.add_conditional_edges(
        "ingest",
        route_after_ingest,
        {"escalate": "escalate", "dispose": "dispose", "question": "question"},
    )
    graph.add_edge("dispose", "explain")
    for terminal in ("question", "explain", "followup", "repeat", "escalate"):
        graph.add_edge(terminal, END)

    return graph.compile()
