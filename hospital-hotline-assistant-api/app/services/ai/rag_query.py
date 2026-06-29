"""RAG query interface — loads the triage-manual vector index and exposes an
async search function used as a pydantic-ai tool in triage_rag_agent.py.

Usage::

    from app.services.ai.rag_query import search_triage_manual

    passages = await search_triage_manual("chest pain with shortness of breath")
"""

from __future__ import annotations

import logging
from functools import lru_cache

from llama_index.core import VectorStoreIndex
from llama_index.core.query_engine import BaseQueryEngine
from llama_index.core.settings import Settings as LlamaSettings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.postgres import PGVectorStore

from app.config import settings

logger = logging.getLogger(__name__)


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
