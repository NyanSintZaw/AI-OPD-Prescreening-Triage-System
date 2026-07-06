"""Dispose node: run the deterministic rules and build the classification.

The classification dict intentionally mirrors the legacy
``classify_triage_level`` tool output so TriageService persistence and the
frontend contract stay unchanged.
"""

from __future__ import annotations

from dataclasses import asdict

from ..rules.disposition import DispositionResult, decide
from .base import GraphDeps, GraphState


def _summary(state) -> str:
    parts = []
    if state.chief_complaint:
        parts.append(state.chief_complaint)
    present = [fid for fid, f in state.findings.items() if f.state == "present"]
    if present:
        parts.append("findings: " + ", ".join(sorted(present)))
    for slot in ("onset", "duration", "location"):
        value = state.slots.get(slot)
        if value:
            parts.append(f"{slot}: {value}")
    return "; ".join(parts) or "no structured findings collected"


def build_classification(state, disposition: DispositionResult) -> dict:
    language = state.language
    key_reason = "; ".join(
        (r.text_th if language == "th" else r.text_en)
        for r in disposition.reasons[:3]
    )
    red_flags = [h.rule_id for h in disposition.rule_hits]
    distress = state.vitals.get("distress_score")
    pain = state.vitals.get("pain_score")
    return {
        "classified": True,
        "level": disposition.level,
        "color": disposition.color,
        "label": disposition.label,
        "key_reason": key_reason,
        "department_code": disposition.department_code,
        "response_time": disposition.response_time,
        "needs_emergency_contact": False,
        "symptoms_summary": _summary(state),
        "pain_score": int(pain) if pain is not None else None,
        "pain_location": state.slots.get("location"),
        "distress_score": int(distress) if distress is not None else None,
        "distress_type": "breathing_difficulty" if distress is not None else None,
        "red_flags": red_flags,
    }


def make_dispose_node(deps: GraphDeps):
    async def dispose(graph_state: GraphState) -> GraphState:
        state = graph_state["s"]
        criteria = graph_state["criteria"]
        audit = graph_state.get("audit") or []

        disposition = decide(
            findings=state.finding_states(),
            vitals=state.vitals,
            age_years=state.age_years,
            complaint_category=state.complaint_category,
            criteria=criteria,
        )
        state.disposition = {
            "level": disposition.level,
            "department_code": disposition.department_code,
            "age_assumed": disposition.age_assumed,
            "reasons": [asdict(r) for r in disposition.reasons],
            "rule_hits": [asdict(h) for h in disposition.rule_hits],
        }
        state.classification = build_classification(state, disposition)
        state.phase = "disposed"
        audit.append({
            "call_site": "disposition",
            "ok": True,
            "level": disposition.level,
            "department_code": disposition.department_code,
            "fired_rules": [h.rule_id for h in disposition.rule_hits],
        })
        return {"s": state, "audit": audit}

    return dispose
