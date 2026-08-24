"""Explain node: verbalize the validated routing (never the level).

LLM writes a warm explanation; the validator gates it; failures fall back to
the deterministic bilingual template. Ends at the department guidance — the
booth flow has no post-assessment contact step.
"""

from __future__ import annotations

import asyncio
from typing import Any
import logging
from time import perf_counter

from langchain_core.messages import HumanMessage

from .. import templates
from ..state import TurnOutput
from ..validator import validate_reply
from ..persona import persona_block
from .base import GraphDeps, GraphState, ainvoke_with_timeout

logger = logging.getLogger(__name__)

_EXPLAIN_PROMPT = {
    "en": (
        "{persona}\n"
        "The clinical rules engine has decided where this patient should go — your ONLY "
        "job is to explain it kindly in 2–4 short sentences. Do not name any other "
        "department.\n"
        "Patient's reported symptoms: {summary}\n"
        "Send the patient to: {department}\n"
        "{name_line}"
        "{urgency_line}"
        "{reference}"
        "{closing_line}"
    ),
    "th": (
        "{persona}\n"
        "ระบบเกณฑ์ทางคลินิกได้ตัดสินใจแล้วว่าผู้ป่วยควรไปที่แผนกใด หน้าที่ของคุณคืออธิบายอย่างสุภาพใน 2-4 ประโยคสั้น ๆ เท่านั้น "
        "ห้ามพูดถึงแผนกอื่น\n"
        "อาการที่ผู้ป่วยเล่า: {summary}\n"
        "ให้ผู้ป่วยไปที่: {department}\n"
        "{name_line}"
        "{urgency_line}"
        "{reference}"
        "{closing_line}"
    ),
}

# The farewell belongs to the END of the flow only. Non-emergency
# explanations are followed by the follow-up offer + the deterministic
# FOLLOW_UP_CLOSE ("Take care / ดูแลตัวเองด้วยนะคะ"), so a "get well soon"
# here would duplicate it (user-reported). Emergency explanations ARE the
# final message (no follow-up step), so they keep the warm close.
_CLOSING_EMERGENCY = {
    "en": (
        "Close warmly (e.g. wish them well). "
        "Do NOT ask any medical follow-up questions."
    ),
    "th": "ปิดท้ายอย่างอบอุ่น ห้ามถามคำถามทางการแพทย์เพิ่ม",
}

_CLOSING_NON_EMERGENCY = {
    "en": (
        "Do NOT say goodbye, wish them well, or add any farewell (no "
        "\"get well soon\", \"take care\", etc.) — the conversation is not "
        "over; a separate system step follows. Do NOT ask any medical "
        "follow-up questions either."
    ),
    "th": (
        "ห้ามกล่าวลา ห้ามอวยพร (เช่น ขอให้หายไว ๆ ดูแลตัวเองนะคะ) "
        "เพราะการสนทนายังไม่จบ ระบบมีขั้นตอนต่อจากนี้ "
        "และห้ามถามคำถามทางการแพทย์เพิ่ม"
    ),
}

# Retrieval budget: top-3 passages average ~3,000 chars; 1,200 used to throw
# most of it away. Separate from settings.rag_query_timeout_seconds (the
# index's own cap) — this is the whole-turn wall clock the explain node allows.
_RAG_TIMEOUT_S = 1.5
_RAG_MAX_CHARS = 2400

_REFERENCE_LINE = {
    "en": "Approved hospital guidance you may draw phrasing from (do not quote levels):\n{passages}\n",
    "th": "ข้อมูลอ้างอิงจากคู่มือโรงพยาบาลที่ใช้ประกอบได้ (ห้ามอ้างถึงระดับ):\n{passages}\n",
}

_URGENCY_LINE = {
    "en": "This is urgent — tell them to go immediately; staff have been notified.\n",
    "th": "กรณีเร่งด่วน ให้แจ้งว่าควรไปทันที เจ้าหน้าที่ได้รับแจ้งแล้ว\n",
}

# The patient's real name never goes to the model. We ask for a placeholder
# and substitute it into the finished reply, so the greeting still reads
# naturally while the wire carries no identifier — see docs/ai-model-io.md.
NAME_PLACEHOLDER = "[NAME]"

_NAME_LINE = {
    "en": (
        "Address the patient once, naturally, writing the literal token "
        f"{NAME_PLACEHOLDER} exactly where their name belongs (do not invent "
        "a name, do not translate the token).\n"
    ),
    "th": (
        "เรียกผู้ป่วยหนึ่งครั้งอย่างเป็นธรรมชาติ โดยเขียนโทเคน "
        f"{NAME_PLACEHOLDER} ตรงตำแหน่งที่ควรเป็นชื่อ "
        "(โทเคนนี้มีคำว่า 'คุณ' อยู่แล้ว อย่าเขียน 'คุณ' นำหน้าซ้ำ "
        "ห้ามแต่งชื่อขึ้นเอง และห้ามแปลโทเคนนี้)\n"
    ),
}


def fallback_explanation(state, deps: GraphDeps) -> str:
    language = state.language
    department_code = state.classification.get("department_code") or "opd_general"
    names = deps.department_names.get(department_code)
    department = (names or {}).get(language) or templates.department_display(
        department_code, language
    )
    if state.classification.get("level", 5) <= 2:
        body = templates.EMERGENCY_EXPLAIN[language]
    else:
        body = templates.OPD_EXPLAIN[language].format(department=department)
    polite = templates.polite_name(state.patient_name, language)
    if polite:
        body = f"{polite} — {body}" if language == "en" else f"{polite}คะ {body}"
    return body


def make_explain_node(deps: GraphDeps):
    async def explain(graph_state: GraphState) -> GraphState:
        state = graph_state["s"]
        audit = graph_state.get("audit") or []
        language = state.language
        classification = state.classification
        department_code = classification.get("department_code") or "opd_general"
        is_emergency = classification.get("level", 5) <= 2
        names = deps.department_names.get(department_code)
        department = (names or {}).get(language) or templates.department_display(
            department_code, language
        )

        reply = fallback_explanation(state, deps)
        if deps.model is not None:
            reference = ""
            # Grounding record for the audit trail + nurse view: was the
            # uploaded manual actually used, and if not, why not. Emergency
            # explanations never use it (fixed wording, no RAG by design).
            rag: dict[str, Any] = {
                "used": False,
                "reason": "emergency" if is_emergency else (
                    "no_retriever" if deps.rag_search is None else None
                ),
                "hits": [],
                "chars": 0,
                "latency_ms": 0,
            }
            if deps.rag_search is not None and not is_emergency:
                rag_started = perf_counter()
                try:
                    status = await asyncio.wait_for(
                        deps.rag_search(
                            classification.get("symptoms_summary") or "", language
                        ),
                        timeout=_RAG_TIMEOUT_S,
                    )
                    passages = str((status or {}).get("passages") or "").strip()
                    if (status or {}).get("available") and passages:
                        reference = _REFERENCE_LINE[language].format(
                            passages=passages[:_RAG_MAX_CHARS]
                        )
                        rag.update(
                            used=True,
                            hits=list((status or {}).get("hits") or [])[:5],
                            chars=min(len(passages), _RAG_MAX_CHARS),
                        )
                    else:
                        rag["reason"] = (status or {}).get("fallback_reason") or "empty"
                except asyncio.TimeoutError:
                    rag["reason"] = "timeout"
                except Exception:
                    logger.debug("rag grounding unavailable; explaining without it")
                    rag["reason"] = "error"
                rag["latency_ms"] = int((perf_counter() - rag_started) * 1000)
            polite = templates.polite_name(state.patient_name, language)
            closing = (
                _CLOSING_EMERGENCY if is_emergency else _CLOSING_NON_EMERGENCY
            )
            prompt = _EXPLAIN_PROMPT[language].format(
                persona=persona_block(language),
                summary=classification.get("symptoms_summary") or "-",
                department=department,
                name_line=_NAME_LINE[language] if polite else "",
                urgency_line=_URGENCY_LINE[language] if is_emergency else "",
                reference=reference,
                closing_line=closing[language],
            )
            started = perf_counter()
            ok = False
            violations_seen: list[str] = []
            messages = [HumanMessage(content=prompt)]
            for _attempt in (1, 2):
                try:
                    response = await ainvoke_with_timeout(
                        deps.model, messages, deps.model_timeout_s
                    )
                    # .text flattens plain-string and content-block replies
                    # (Gemini 3 returns a list of blocks, not a bare string).
                    candidate = (response.text or "").strip()
                    violations = validate_reply(
                        candidate,
                        language=language,
                        department_code=department_code,
                        department_names=deps.validator_department_names,
                        is_emergency=is_emergency,
                    )
                    if candidate and not violations:
                        reply = candidate
                        ok = True
                        break
                    violations_seen = [v.code for v in violations]
                    messages = [HumanMessage(content=(
                        prompt
                        + "\n\nYour previous reply was rejected for: "
                        + ", ".join(f"{v.code} ({v.detail})" for v in violations)
                        + ". Rewrite it following ALL the strict rules."
                    ))]
                except Exception:
                    logger.exception("explanation generation failed")
                    break
            audit.append({
                "call_site": "explain",
                "latency_ms": int((perf_counter() - started) * 1000),
                "ok": ok,
                "violations": violations_seen,
                # persisted into ai_inference_audit.rules_trace → /trace
                "rag": rag,
            })
            # Put the real name back. Unconditional, so a stray token can
            # never reach the patient: no name on file means the placeholder
            # is dropped rather than shown.
            reply = " ".join(
                reply.replace(NAME_PLACEHOLDER, polite or "").split()
            )
            # "คุณ [NAME]" + "คุณมาลี" → "คุณ คุณมาลี" (seen live); the
            # honorific lives in polite_name, so a doubled one is always noise.
            reply = reply.replace("คุณ คุณ", "คุณ").replace("คุณคุณ", "คุณ")

        # Non-emergency: append the follow-up offer and stay open for one more
        # turn. Emergency (level ≤ 2) skips follow-up — flow is complete now.
        reply_options: list[dict[str, str]] = []
        flow_complete = True
        if is_emergency:
            state.phase = "disposed"
        else:
            offer = templates.FOLLOW_UP_OFFER[language]
            reply = f"{reply.rstrip()} {offer}".strip()
            state.phase = "follow_up"
            flow_complete = False
            reply_options = list(
                templates.YES_NO_OPTIONS.get(language, templates.YES_NO_OPTIONS["en"])
            )

        return {
            "s": state,
            "audit": audit,
            "output": TurnOutput(
                reply=reply,
                classification=classification,
                reply_options=reply_options,
                flow_complete=flow_complete,
                post_disposition=False,
            ),
        }

    return explain
