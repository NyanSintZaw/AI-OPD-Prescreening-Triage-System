"""Unit tests for app.services.ai.rag_query — query engine and search tool.

All tests are offline: LlamaIndex vector store and embedding model are mocked.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_node(text: str, title: str = "Section", page: int = 5) -> MagicMock:
    node = MagicMock()
    node.node.text = text
    node.node.metadata = {"title": title, "page": page}
    return node


def _make_response(nodes: list[MagicMock], synthesised: str = "") -> MagicMock:
    r = MagicMock()
    r.source_nodes = nodes
    r.__str__ = lambda self: synthesised
    return r


@pytest.mark.asyncio
async def test_status_returns_available_passages_for_english(caplog):
    caplog.set_level(logging.INFO)
    node = _make_node("Emergency level criteria.", "Level 2", page=3)
    mock_engine = AsyncMock()
    mock_engine.aquery.return_value = _make_response([node])

    with patch(
        "app.services.ai.rag_query._query_index_with_timeout",
        new=AsyncMock(return_value=mock_engine.aquery.return_value),
    ):
        from app.services.ai.rag_query import search_triage_manual_status

        result = await search_triage_manual_status("vision changes", language="en")

    assert result["available"] is True
    assert result["source"] == "indexed_triage_manual"
    assert "Emergency level criteria." in str(result["passages"])
    assert result["fallback_reason"] is None
    assert result["language"] == "en"
    assert "Indexed triage manual search found" in caplog.text


@pytest.mark.asyncio
async def test_status_passes_thai_query_verbatim():
    thai = "ปวดหัวและมองเห็นไม่ชัด"
    mock_engine = AsyncMock()
    mock_engine.aquery.return_value = _make_response([
        _make_node("เกณฑ์คัดกรองฉุกเฉิน", "แนวทาง", page=7)
    ])

    with patch(
        "app.services.ai.rag_query._query_index_with_timeout",
        new=AsyncMock(return_value=mock_engine.aquery.return_value),
    ) as mock_query:
        from app.services.ai.rag_query import search_triage_manual_status

        result = await search_triage_manual_status(thai, language="th")

    mock_query.assert_called_once()
    assert mock_query.call_args.args[0] == thai
    assert result["available"] is True
    assert result["language"] == "th"
    assert "เกณฑ์คัดกรองฉุกเฉิน" in str(result["passages"])


@pytest.mark.asyncio
async def test_status_empty_index_result_falls_back(caplog):
    mock_engine = AsyncMock()
    mock_engine.aquery.return_value = _make_response([])

    with patch(
        "app.services.ai.rag_query._query_index_with_timeout",
        new=AsyncMock(return_value=mock_engine.aquery.return_value),
    ):
        from app.services.ai.rag_query import search_triage_manual_status

        result = await search_triage_manual_status("headache", language="en")

    assert result["available"] is False
    assert result["source"] == "static_fallback"
    assert result["fallback_reason"] == "empty_index_result"
    assert "returned no passages" in caplog.text


@pytest.mark.asyncio
async def test_status_exception_falls_back_with_warning(caplog):
    mock_engine = AsyncMock()
    mock_engine.aquery.side_effect = Exception("pgvector unavailable")

    with patch(
        "app.services.ai.rag_query._query_index_with_timeout",
        new=AsyncMock(side_effect=Exception("pgvector unavailable")),
    ):
        from app.services.ai.rag_query import search_triage_manual_status

        result = await search_triage_manual_status("chest pain", language="en")

    assert result["available"] is False
    assert result["source"] == "static_fallback"
    assert "pgvector unavailable" in str(result["fallback_reason"])
    assert "Indexed triage manual search unavailable" in caplog.text


@pytest.mark.asyncio
async def test_status_timeout_falls_back_without_waiting_for_index(caplog):
    with patch(
        "app.services.ai.rag_query._query_index_with_timeout",
        side_effect=TimeoutError(),
    ):
        from app.services.ai.rag_query import search_triage_manual_status

        result = await search_triage_manual_status("chest pain", language="en")

    assert result["available"] is False
    assert result["source"] == "static_fallback"
    assert result["fallback_reason"] == "index_timeout"
    assert "timed out" in caplog.text


@pytest.mark.asyncio
async def test_start_prewarm_reuses_existing_task(monkeypatch):
    from app.services.ai import rag_query

    rag_query.get_rag_query_engine.cache_clear()
    monkeypatch.setattr(rag_query, "_ENGINE_PREWARM_TASK", None)

    async def slow_prewarm():
        await asyncio.sleep(0.1)
        return True

    monkeypatch.setattr(rag_query, "prewarm_rag_query_engine", slow_prewarm)

    task_one = rag_query.start_rag_query_engine_prewarm()
    task_two = rag_query.start_rag_query_engine_prewarm()

    assert task_one is task_two
    assert task_one is not None
    task_one.cancel()
    await asyncio.gather(task_one, return_exceptions=True)


@pytest.mark.asyncio
async def test_returns_formatted_passages():
    node = _make_node("Cardiac arrest procedures.", "triage level 1", page=2)
    mock_engine = AsyncMock()
    mock_engine.aquery.return_value = _make_response([node])

    with patch("app.services.ai.rag_query.get_rag_query_engine", return_value=mock_engine):
        from app.services.ai.rag_query import search_triage_manual
        result = await search_triage_manual("cardiac arrest")

    assert "Cardiac arrest procedures." in result
    assert "[Section: triage level 1 | Page: 2]" in result


@pytest.mark.asyncio
async def test_multiple_nodes_separated_by_divider():
    nodes = [_make_node("First", "A", 1), _make_node("Second", "B", 4)]
    mock_engine = AsyncMock()
    mock_engine.aquery.return_value = _make_response(nodes)

    with patch("app.services.ai.rag_query.get_rag_query_engine", return_value=mock_engine):
        from app.services.ai.rag_query import search_triage_manual
        result = await search_triage_manual("symptoms")

    assert "First" in result
    assert "Second" in result
    assert "---" in result


@pytest.mark.asyncio
async def test_empty_nodes_returns_synthesised_text():
    mock_engine = AsyncMock()
    mock_engine.aquery.return_value = _make_response([], "Fallback answer")

    with patch("app.services.ai.rag_query.get_rag_query_engine", return_value=mock_engine):
        from app.services.ai.rag_query import search_triage_manual
        result = await search_triage_manual("query")

    assert result == "Fallback answer"


@pytest.mark.asyncio
async def test_exception_returns_fallback_message():
    mock_engine = AsyncMock()
    mock_engine.aquery.side_effect = Exception("DB gone")

    with patch("app.services.ai.rag_query.get_rag_query_engine", return_value=mock_engine):
        from app.services.ai.rag_query import search_triage_manual
        result = await search_triage_manual("chest pain")

    assert "unavailable" in result.lower() or "ไม่พบข้อมูล" in result


@pytest.mark.asyncio
async def test_thai_query_passed_verbatim():
    thai = "ปวดหน้าอกรุนแรง"
    mock_engine = AsyncMock()
    mock_engine.aquery.return_value = _make_response([])

    with patch("app.services.ai.rag_query.get_rag_query_engine", return_value=mock_engine):
        from app.services.ai.rag_query import search_triage_manual
        await search_triage_manual(thai)

    mock_engine.aquery.assert_called_once_with(thai)


@pytest.mark.asyncio
async def test_section_header_in_passage():
    node = _make_node("Level 3 criteria", "แนวทางการดูแล", page=10)
    mock_engine = AsyncMock()
    mock_engine.aquery.return_value = _make_response([node])

    with patch("app.services.ai.rag_query.get_rag_query_engine", return_value=mock_engine):
        from app.services.ai.rag_query import search_triage_manual
        result = await search_triage_manual("level 3")

    assert "แนวทางการดูแล" in result
    assert "Page: 10" in result


def test_query_engine_is_cached():
    mock_index = MagicMock()
    singleton = MagicMock()
    mock_index.as_query_engine.return_value = singleton

    with (
        patch("app.services.ai.rag_query._build_vector_store", return_value=MagicMock()),
        patch("app.services.ai.rag_query.HuggingFaceEmbedding"),
        patch("app.services.ai.rag_query.LlamaSettings"),
        patch("app.services.ai.rag_query.VectorStoreIndex.from_vector_store", return_value=mock_index),
    ):
        from app.services.ai.rag_query import get_rag_query_engine
        get_rag_query_engine.cache_clear()
        a = get_rag_query_engine()
        b = get_rag_query_engine()
        assert a is b
        get_rag_query_engine.cache_clear()


def test_cache_clear_creates_new_instance():
    mock_index = MagicMock()
    mock_index.as_query_engine.side_effect = [MagicMock(), MagicMock()]

    with (
        patch("app.services.ai.rag_query._build_vector_store", return_value=MagicMock()),
        patch("app.services.ai.rag_query.HuggingFaceEmbedding"),
        patch("app.services.ai.rag_query.LlamaSettings"),
        patch("app.services.ai.rag_query.VectorStoreIndex.from_vector_store", return_value=mock_index),
    ):
        from app.services.ai.rag_query import get_rag_query_engine
        get_rag_query_engine.cache_clear()
        a = get_rag_query_engine()
        get_rag_query_engine.cache_clear()
        b = get_rag_query_engine()
        assert a is not b
        get_rag_query_engine.cache_clear()
