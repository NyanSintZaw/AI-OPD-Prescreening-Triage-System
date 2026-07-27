"""Explain node: verbalize the validated routing (never the level).

LLM writes a warm explanation; the validator gates it; failures fall back to
the deterministic bilingual template. Ends at the department guidance — the
booth flow has no post-assessment contact step.
"""

from __future__ import annotations

import asyncio
import logging
from time import perf_counter

from langchain_core.messages import HumanMessage

from .. import templates
from ..state import TurnOutput
from ..validator import validate_reply
from .base import GraphDeps, GraphState, ainvoke_with_timeout

logger = logging.getLogger(__name__)

_EXPLAIN_PROMPT = {
    "en": (
        "You are a warm, calm hospital screening assistant speaking English. The clinical "
        "rules engine has decided where this patient should go — your ONLY job is to "
        "explain it kindly in 2–4 short sentences.\n"
        "STRICT RULES: never mention triage levels, colors, scores, or classifications; "
        "never diagnose or name a suspected disease; never recommend medication; do not "
        "name any other department.\n"
        "Patient's reported symptoms: {summary}\n"
        "Send the patient to: {department}\n"
        "{name_line}"
        "{urgency_line}"
        "{reference}"
        "{closing_line}"
    ),
    "th": (
        "คุณเป็นผู้ช่วยคัดกรองของโรงพยาบาล พูดภาษาไทยอย่างอบอุ่นและใจเย็น "
        "ระบบเกณฑ์ทางคลินิกได้ตัดสินใจแล้วว่าผู้ป่วยควรไปที่แผนกใด หน้าที่ของคุณคืออธิบายอย่างสุภาพใน 2-4 ประโยคสั้น ๆ เท่านั้น\n"
        "ข้อห้ามเด็ดขาด: ห้ามพูดถึงระดับการคัดกรอง สี คะแนน หรือการจัดประเภท "
        "ห้ามวินิจฉัยหรือระบุชื่อโรคที่สงสัย ห้ามแนะนำยา และห้ามพูดถึงแผนกอื่น\n"
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

_REFERENCE_LINE = {
    "en": "Approved hospital guidance you may draw phrasing from (do not quote levels):\n{passages}\n",
    "th": "ข้อมูลอ้างอิงจากคู่มือโรงพยาบาลที่ใช้ประกอบได้ (ห้ามอ้างถึงระดับ):\n{passages}\n",
}

_URGENCY_LINE = {
    "en": "This is urgent — tell them to go immediately; staff have been notified.\n",
    "th": "กรณีเร่งด่วน ให้แจ้งว่าควรไปทันที เจ้าหน้าที่ได้รับแจ้งแล้ว\n",
}

_NAME_LINE = {
    "en": "Address the patient by name, once, naturally: {name}\n",
    "th": "เรียกชื่อผู้ป่วยหนึ่งครั้งอย่างเป็นธรรมชาติ: {name}\n",
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
            if deps.rag_search is not None and not is_emergency:
                try:
                    passages = await asyncio.wait_for(
                        deps.rag_search(classification.get("symptoms_summary") or ""),
                        timeout=1.5,
                    )
                    if passages and passages.strip():
                        reference = _REFERENCE_LINE[language].format(
                            passages=passages.strip()[:1200]
                        )
                except Exception:
                    logger.debug("rag grounding unavailable; explaining without it")
            polite = templates.polite_name(state.patient_name, language)
            closing = (
                _CLOSING_EMERGENCY if is_emergency else _CLOSING_NON_EMERGENCY
            )
            prompt = _EXPLAIN_PROMPT[language].format(
                summary=classification.get("symptoms_summary") or "-",
                department=department,
                name_line=_NAME_LINE[language].format(name=polite) if polite else "",
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
            })

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
