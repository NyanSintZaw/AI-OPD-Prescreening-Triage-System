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

from collections import Counter

from langgraph.graph import END, StateGraph

from .nodes.base import GraphDeps, GraphState
from .nodes.dispose import make_dispose_node
from .nodes.explain import make_explain_node
from .nodes.followup import make_followup_node
from .nodes.ingest import make_ingest_node
from .nodes.question import interview_inputs, make_question_node
from .nodes.terminal import make_escalate_node, make_repeat_node
from .rules.disposition import HIGH_RISK_PAIN_FINDINGS, decide
from .rules.question_policy import (
    confirm_question_for,
    is_interview_complete,
    next_question,
)
from .rules.red_flags import evaluate_red_flags, hit_finding_ids
from .vitals import effective_vitals


def _confirmation_targets(state, criteria, provisional) -> list[str]:
    """Present-but-unconfirmed finding ids the level-1/2 verdict rests on.

    Empty when the verdict survives on confirmed findings + vitals alone —
    then there is nothing to gate and the disposition proceeds."""

    confirmed = {
        fid: f.state for fid, f in state.findings.items() if f.confirmed
    }
    confirmed_hits = evaluate_red_flags(
        findings=confirmed,
        vitals=effective_vitals(state),
        age_years=state.age_years,
        criteria=criteria,
    )
    if any(h.level <= 2 for h in confirmed_hits):
        return []

    unconfirmed_present = {
        fid
        for fid, f in state.findings.items()
        if f.state == "present" and not f.confirmed
    }
    targets: list[str] = []
    for hit in provisional.rule_hits:
        if hit.level > 2:
            continue
        for fid in sorted(hit_finding_ids(criteria, hit) & unconfirmed_present):
            if fid not in targets:
                targets.append(fid)
    if not targets and not provisional.rule_hits:
        # Level <= 2 via the pain/distress scale escalation: the scale value
        # is a structured answer, but its high-risk CONTEXT finding may be
        # extraction-sourced — confirm that context.
        targets = sorted(unconfirmed_present & HIGH_RISK_PAIN_FINDINGS)
    return targets[:3]


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
            vitals=effective_vitals(state),
            age_years=state.age_years,
            complaint_category=state.complaint_category,
            criteria=criteria,
        )
        # Confirm-before-fire: an emergency is never declared from free-text
        # extraction alone. If the level-1/2 verdict evaporates when only
        # CONFIRMED findings are evaluated (measured vitals always count),
        # ask the driving findings' verbatim confirm questions instead of
        # disposing. A yes fires the rule next turn; a no corrects the
        # extraction; two non-answers accept it (fail-safe: over-triage).
        state.pending_confirm = []
        if provisional.level <= 2:
            need = _confirmation_targets(state, criteria, provisional)
            if need:
                counts = Counter(state.asked_question_ids)
                pending: list[str] = []
                for fid in need:
                    qid = confirm_question_for(
                        criteria, fid, state.complaint_category
                    ).id
                    if counts.get(qid, 0) >= 2:
                        # Patient wouldn't clarify twice — accept the
                        # extraction so the safety rule can still fire.
                        state.findings[fid].confirmed = True
                    else:
                        pending.append(fid)
                if pending:
                    state.pending_confirm = pending
                    return "question"
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
