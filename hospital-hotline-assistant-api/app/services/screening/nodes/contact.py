"""Contact node: parse the post-assessment contact-preference reply.

LLM (or a deterministic heuristic fallback) only PARSES the answer; every
reply the patient sees is a fixed template. Output mirrors the legacy
``record_contact_preference`` dict so TriageService's contact state machine
works unchanged.
"""

from __future__ import annotations

import logging
import re
from time import perf_counter

from ..extraction import CONTACT_PROMPT, ContactAnswer
from .. import templates
from ..state import TurnOutput
from .base import GraphDeps, GraphState

logger = logging.getLogger(__name__)

_PHONE = re.compile(r"(?<!\d)(0\d{1,2}[- ]?\d{3}[- ]?\d{3,4})(?!\d)")
_YES = re.compile(
    r"^(?:yes|yeah|sure|ok(?:ay)?|please|y)\b|ต้องการ|ได้ค่ะ|ได้ครับ|โทรมา|ติดต่อมา|เอาค่ะ|เอาครับ|ครับผม|ค่ะ$",
    re.IGNORECASE,
)
_NO = re.compile(
    r"^(?:no|nope|n)\b|ไม่ต้อง|ไม่เอา|ไม่รับ|ไม่สะดวก|ไม่เป็นไร|ไปเอง",
    re.IGNORECASE,
)


def heuristic_contact_parse(text: str) -> ContactAnswer:
    stripped = text.strip()
    phone_match = _PHONE.search(stripped.replace(" ", "").replace("-", "")) or _PHONE.search(stripped)
    phone = phone_match.group(1).replace(" ", "").replace("-", "") if phone_match else None
    if phone:
        return ContactAnswer(requested=True, phone_number=phone)
    if _NO.search(stripped):
        return ContactAnswer(requested=False)
    if _YES.search(stripped):
        return ContactAnswer(requested=True)
    return ContactAnswer(requested=None)


def make_contact_node(deps: GraphDeps):
    async def contact(graph_state: GraphState) -> GraphState:
        state = graph_state["s"]
        user_text = graph_state["user_text"]
        audit = graph_state.get("audit") or []
        language = state.language

        answer: ContactAnswer | None = None
        if deps.model is not None:
            structured = deps.model.with_structured_output(ContactAnswer)
            started = perf_counter()
            try:
                answer = await structured.ainvoke(CONTACT_PROMPT.format(user_text=user_text))
                ok = True
            except Exception:
                logger.exception("contact parse failed; using heuristic")
                ok = False
            audit.append({
                "call_site": "contact",
                "latency_ms": int((perf_counter() - started) * 1000),
                "ok": ok,
            })
        if answer is None:
            answer = heuristic_contact_parse(user_text)

        # Merge with what previous contact turns already captured.
        prior = state.contact or {}
        requested = answer.requested if answer.requested is not None else prior.get("requested")
        phone = answer.phone_number or prior.get("phone_number")

        if requested is True and not phone:
            needs_followup = True
            followup = templates.CONTACT_ASK_PHONE[language]
            reply = followup
        elif requested is None:
            needs_followup = True
            followup = templates.CONTACT_CLARIFY[language]
            reply = followup
        else:
            needs_followup = False
            followup = None
            reply = (
                templates.CONTACT_CONFIRM_YES[language]
                if requested else templates.CONTACT_CONFIRM_NO[language]
            )
            state.phase = "done"

        state.contact = {
            "contact_preference_recorded": True,
            "requested": requested if isinstance(requested, bool) else None,
            "phone_number": phone,
            "preferred_time": answer.preferred_time or prior.get("preferred_time"),
            "relation": answer.relation or prior.get("relation"),
            "confidence": 1.0 if isinstance(requested, bool) else 0.0,
            "needs_followup": needs_followup,
            "followup_question": followup,
        }
        return {
            "s": state,
            "audit": audit,
            "output": TurnOutput(reply=reply, contact=state.contact),
        }

    return contact
