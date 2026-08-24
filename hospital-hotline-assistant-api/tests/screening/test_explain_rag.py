"""Explain node × RAG: manual passages reach the prompt only when the index
actually answered, and every outcome is recorded in the audit entry.

Regression: the old wiring returned a Thai "manual unavailable" sentence
instead of raising, and the node pasted it into the prompt as guidance.
"""

from __future__ import annotations

import asyncio

from app.services.screening.nodes.base import GraphDeps
from app.services.screening.nodes.explain import _RAG_MAX_CHARS, make_explain_node
from app.services.screening.state import ScreeningState

from .fakes import FakeChatModel

PASSAGE = "[Section: ไข้ | Page: 12]\nไข้ร่วมกับไอ ให้ส่งตรวจ OPD ทั่วไป"


def _status(available: bool, *, reason=None, passages="", hits=None):
    async def search(query: str, language: str) -> dict:
        search.calls.append((query, language))
        return {
            "available": available,
            "passages": passages,
            "hits": hits or [],
            "fallback_reason": reason,
            "language": language,
        }
    search.calls = []
    return search


def _deps(model, rag_search) -> GraphDeps:
    return GraphDeps(
        model=model,
        question_budget=8,
        department_names={
            "opd_general": {"en": "OPD General Practice", "th": "OPD เวชปฏิบัติทั่วไป"},
            "emergency": {"en": "the Emergency Department", "th": "ห้องฉุกเฉิน"},
        },
        validator_department_names={
            "opd_general": ["OPD General Practice", "OPD เวชปฏิบัติทั่วไป"],
            "emergency": ["the Emergency Department", "ห้องฉุกเฉิน"],
        },
        rag_search=rag_search,
    )


async def _run(rag_search, *, level=4, language="th"):
    model = FakeChatModel()
    model.text_replies.append("")  # force fallback; we inspect prompt + audit
    state = ScreeningState(
        session_id="explain-rag",
        language=language,  # type: ignore[arg-type]
        phase="disposed",  # type: ignore[arg-type]
        classification={
            "classified": True,
            "level": level,
            "department_code": "emergency" if level <= 2 else "opd_general",
            "symptoms_summary": "มีไข้ ไอ สองวัน",
        },
    )
    node = make_explain_node(_deps(model, rag_search))
    result = await node({"s": state, "user_text": "", "criteria": None, "audit": []})
    return model, result["audit"][-1]


async def test_available_passages_reach_the_prompt_and_audit_says_grounded():
    search = _status(True, passages=PASSAGE, hits=[{"title": "ไข้", "page": 12, "chars": 40}])
    model, entry = await _run(search)
    # (the fake stores repr(messages), so check the passage line by line)
    for line in PASSAGE.splitlines():
        assert line in model.prompts[0]
    assert search.calls == [("มีไข้ ไอ สองวัน", "th")]
    assert entry["call_site"] == "explain"
    assert entry["rag"]["used"] is True
    assert entry["rag"]["hits"] == [{"title": "ไข้", "page": 12, "chars": 40}]
    assert entry["rag"]["reason"] is None
    assert entry["rag"]["chars"] == len(PASSAGE)


async def test_unavailable_index_injects_nothing_and_records_the_reason():
    # The status fn reports it could not answer — the "passages" field may
    # even carry a human-readable fallback; it must never reach the prompt.
    search = _status(False, reason="empty_index_result", passages="ไม่พบข้อมูลจากคู่มือ")
    model, entry = await _run(search)
    assert "ไม่พบข้อมูลจากคู่มือ" not in model.prompts[0]
    assert "ข้อมูลอ้างอิงจากคู่มือ" not in model.prompts[0]
    assert entry["rag"] == {
        "used": False, "reason": "empty_index_result", "hits": [], "chars": 0,
        "latency_ms": entry["rag"]["latency_ms"],
    }


async def test_timeout_is_recorded_not_raised():
    async def slow(query, language):
        await asyncio.sleep(5)
        return {"available": True, "passages": PASSAGE}

    import app.services.screening.nodes.explain as explain_mod

    original = explain_mod._RAG_TIMEOUT_S
    explain_mod._RAG_TIMEOUT_S = 0.01
    try:
        model, entry = await _run(slow)
    finally:
        explain_mod._RAG_TIMEOUT_S = original
    assert "ให้ส่งตรวจ OPD ทั่วไป" not in model.prompts[0]
    assert entry["rag"]["used"] is False and entry["rag"]["reason"] == "timeout"


async def test_no_retriever_and_emergency_paths_never_call_rag():
    model, entry = await _run(None)
    assert entry["rag"]["used"] is False and entry["rag"]["reason"] == "no_retriever"

    search = _status(True, passages=PASSAGE)
    model, entry = await _run(search, level=1)
    assert search.calls == []          # emergency wording is fixed; no RAG
    assert "ให้ส่งตรวจ OPD ทั่วไป" not in model.prompts[0]
    assert entry["rag"]["reason"] == "emergency"


async def test_long_passages_are_capped_at_the_budget():
    long = "x" * (_RAG_MAX_CHARS + 500)
    search = _status(True, passages=long)
    model, entry = await _run(search)
    assert "x" * _RAG_MAX_CHARS in model.prompts[0]
    assert "x" * (_RAG_MAX_CHARS + 1) not in model.prompts[0]
    assert entry["rag"]["chars"] == _RAG_MAX_CHARS
