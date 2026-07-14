"""RAG query interface — loads the triage-manual vector index and exposes an
async search function used as a pydantic-ai tool in triage_rag_agent.py.

Usage::

    from app.services.ai.rag_query import search_triage_manual

    passages = await search_triage_manual("chest pain with shortness of breath")
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from llama_index.core import VectorStoreIndex
from llama_index.core.query_engine import BaseQueryEngine
from llama_index.core.settings import Settings as LlamaSettings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.postgres import PGVectorStore

from app.config import settings

logger = logging.getLogger(__name__)

_ENGINE_PREWARM_TASK: asyncio.Task[bool] | None = None


# ---------------------------------------------------------------------------
# pgvector store helpers
# ---------------------------------------------------------------------------

def _parse_pg_user(dsn: str) -> str:
    """Extract the username from a postgresql:// DSN string."""
    try:
        return dsn.split("://")[1].split(":")[0]
    except IndexError:
        return "postgres"


def _parse_pg_password(dsn: str) -> str:
    """Extract the password from a postgresql:// DSN string."""
    try:
        credentials = dsn.split("://")[1].split("@")[0]
        return credentials.split(":")[1]
    except IndexError:
        return "postgres"


def _build_vector_store() -> PGVectorStore:
    """Construct a LlamaIndex PGVectorStore connected to the application database."""
    return PGVectorStore.from_params(
        database="hospital_hotline",
        host="localhost",
        port=5432,
        user=_parse_pg_user(settings.database_url),
        password=_parse_pg_password(settings.database_url),
        table_name=settings.pgvector_table,
        embed_dim=settings.pgvector_embed_dim,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_rag_query_engine(similarity_top_k: int = 3) -> BaseQueryEngine:
    """Return a cached LlamaIndex query engine backed by the pgvector store.

    Args:
        similarity_top_k: Number of nearest-neighbour chunks to retrieve.

    Returns:
        A LlamaIndex ``BaseQueryEngine`` ready for ``aquery()`` calls.
    """
    embed_model = HuggingFaceEmbedding(
        model_name=settings.embed_model,
        query_instruction="query: ",
        text_instruction="passage: ",
    )
    LlamaSettings.embed_model = embed_model
    LlamaSettings.llm = None  # LLM synthesis handled externally by pydantic-ai

    vector_store = _build_vector_store()
    index = VectorStoreIndex.from_vector_store(vector_store)

    query_engine = index.as_query_engine(
        similarity_top_k=similarity_top_k,
        response_mode="no_text",  # return raw source nodes — we format ourselves
    )
    logger.info(
        "RAG query engine initialised (table=%s, top_k=%d)",
        settings.pgvector_table,
        similarity_top_k,
    )
    return query_engine


def is_rag_query_engine_warm() -> bool:
    """Return whether the pgvector query engine has already been initialised."""

    return get_rag_query_engine.cache_info().currsize > 0


async def prewarm_rag_query_engine() -> bool:
    """Warm the RAG query engine outside latency-sensitive request paths."""

    try:
        if is_rag_query_engine_warm():
            logger.info("RAG query engine already warm")
            return True
        logger.info("Prewarming RAG query engine in background")
        await asyncio.to_thread(get_rag_query_engine)
        logger.info("RAG query engine prewarm complete")
        return True
    except Exception as exc:
        logger.warning("RAG query engine prewarm failed: %s", exc)
        return False


def start_rag_query_engine_prewarm() -> asyncio.Task[bool] | None:
    """Start one shared background prewarm task for the current event loop."""

    global _ENGINE_PREWARM_TASK
    if is_rag_query_engine_warm():
        logger.info("RAG query engine already warm; skipping prewarm task")
        return None
    if _ENGINE_PREWARM_TASK is not None and not _ENGINE_PREWARM_TASK.done():
        logger.info("RAG query engine prewarm already running")
        return _ENGINE_PREWARM_TASK
    _ENGINE_PREWARM_TASK = asyncio.create_task(prewarm_rag_query_engine())
    return _ENGINE_PREWARM_TASK


async def _get_rag_query_engine_with_timeout(timeout_seconds: float) -> BaseQueryEngine:
    if is_rag_query_engine_warm():
        return get_rag_query_engine()
    prewarm_task = start_rag_query_engine_prewarm()
    if prewarm_task is not None:
        await asyncio.wait_for(asyncio.shield(prewarm_task), timeout=timeout_seconds)
    if is_rag_query_engine_warm():
        return get_rag_query_engine()
    raise RuntimeError("RAG query engine unavailable after prewarm")


async def _query_index_with_timeout(query: str, timeout_seconds: float):
    timeout = max(0.05, float(timeout_seconds or 0.05))
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    engine = await _get_rag_query_engine_with_timeout(timeout)
    elapsed = loop.time() - started_at
    remaining = max(0.05, timeout - elapsed)
    return await asyncio.wait_for(engine.aquery(query), timeout=remaining)


async def search_triage_manual(query: str) -> str:
    """Search the MFU hospital official triage manual for relevant passages.

    This is the async wrapper registered as a pydantic-ai tool.

    Args:
        query: Patient symptoms or clinical question in Thai or English.

    Returns:
        Concatenated relevant passages, or a fallback message when unavailable.
    """
    try:
        engine = get_rag_query_engine()
        response = await engine.aquery(query)

        nodes = getattr(response, "source_nodes", [])
        if nodes:
            passages: list[str] = []
            for node in nodes:
                text = getattr(node.node, "text", "") or ""
                title = node.node.metadata.get("title", "")
                page = node.node.metadata.get("page", "")
                header = f"[Section: {title} | Page: {page}]" if title else ""
                passages.append(f"{header}\n{text}".strip())
            return "\n\n---\n\n".join(passages)

        return str(response)

    except Exception as exc:
        logger.warning("RAG query failed: %s", exc)
        return (
            "ไม่พบข้อมูลจากคู่มือการคัดกรอง กรุณาใช้วิจารณญาณทางคลินิกของท่านเอง "
            "(Triage manual unavailable — use clinical judgement.)"
        )


async def search_triage_manual_status(
    query: str,
    language: str = "en",
) -> dict[str, object]:
    """Search the indexed triage manual and return explicit fallback status.

    The ADK live/text triage agents use this shape so they can prefer the
    uploaded pgvector index when available, while transparently falling back to
    static JSON references when the index is missing, empty, or unavailable.
    """

    clean_query = str(query or "").strip()
    lang = language if language in {"en", "th"} else "en"
    logger.info(
        "Indexed triage manual search requested language=%s query_len=%d",
        lang,
        len(clean_query),
    )
    if not clean_query:
        logger.warning("Indexed triage manual search skipped: empty query")
        return {
            "available": False,
            "source": "static_fallback",
            "passages": "",
            "fallback_reason": "empty_query",
            "language": lang,
        }

    try:
        response = await _query_index_with_timeout(
            clean_query,
            settings.rag_query_timeout_seconds,
        )
        nodes = getattr(response, "source_nodes", [])
        if not nodes:
            logger.warning(
                "Indexed triage manual search returned no passages language=%s",
                lang,
            )
            return {
                "available": False,
                "source": "static_fallback",
                "passages": "",
                "fallback_reason": "empty_index_result",
                "language": lang,
            }

        passages: list[str] = []
        for node in nodes:
            text = getattr(node.node, "text", "") or ""
            title = node.node.metadata.get("title", "")
            page = node.node.metadata.get("page", "")
            header = f"[Section: {title} | Page: {page}]" if title else ""
            passage = f"{header}\n{text}".strip()
            if passage:
                passages.append(passage)

        if not passages:
            logger.warning(
                "Indexed triage manual search nodes had no text language=%s",
                lang,
            )
            return {
                "available": False,
                "source": "static_fallback",
                "passages": "",
                "fallback_reason": "empty_passages",
                "language": lang,
            }

        joined = "\n\n---\n\n".join(passages)
        logger.info(
            "Indexed triage manual search found %d passages language=%s",
            len(passages),
            lang,
        )
        return {
            "available": True,
            "source": "indexed_triage_manual",
            "passages": joined,
            "fallback_reason": None,
            "language": lang,
        }

    except TimeoutError as exc:
        logger.warning(
            "Indexed triage manual search timed out after %.2fs; using static fallback",
            settings.rag_query_timeout_seconds,
        )
        return {
            "available": False,
            "source": "static_fallback",
            "passages": "",
            "fallback_reason": "index_timeout",
            "language": lang,
        }
    except Exception as exc:
        logger.warning("Indexed triage manual search unavailable: %s", exc)
        return {
            "available": False,
            "source": "static_fallback",
            "passages": "",
            "fallback_reason": str(exc)[:300] or "index_unavailable",
            "language": lang,
        }
