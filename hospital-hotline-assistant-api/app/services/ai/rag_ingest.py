"""Ingest the hospital triage manual PDF into a pgvector store.

Run once (or after the PDF is updated) to populate the triage_knowledge table:

    uv run python -m app.services.ai.rag_ingest

The script is idempotent when called with ``clear_first=False`` (new chunks are
upserted by doc_id).  Pass ``clear_first=True`` (or use ``ingest_replace()``)
to wipe old embeddings before loading the new PDF.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.settings import Settings as LlamaSettings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.postgres import PGVectorStore

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section-boundary keywords (Thai + English as specified)
# ---------------------------------------------------------------------------
_SECTION_KEYWORDS: list[str] = [
    "triage level",
    "ระดับ",
    "ส่งห้องฉุกเฉิน",
    "แนวทางการรับผู้ป่วย",
    "ลักษณะจำเพาะ",
    "แนวทางการดูแล",
    "ข้อบ่งชี้",
    "fast track",
    "สัญญาณชีพ",
    "chief complain",
    "แนวทางการบริหาร",
]

# Matches any line that contains a section keyword (case-insensitive).
_SECTION_PATTERN = re.compile(
    r"(" + "|".join(re.escape(k) for k in _SECTION_KEYWORDS) + r")",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# PDF parsing helpers
# ---------------------------------------------------------------------------

def _extract_pages(pdf_path: str) -> list[tuple[int, str]]:
    """Return a list of (page_number, text) tuples from *pdf_path*.

    Page numbers are 1-based to match PDF viewer conventions.
    """
    doc = fitz.open(pdf_path)
    pages: list[tuple[int, str]] = []
    for page_idx in range(len(doc)):
        page = doc.load_page(page_idx)
        text = page.get_text("text") or ""
        pages.append((page_idx + 1, text.strip()))
    doc.close()
    return pages


def _chunk_by_sections(pages: list[tuple[int, str]]) -> list[dict[str, Any]]:
    """Split extracted page text into logical sections using *_SECTION_KEYWORDS*.

    Returns a list of dicts:
        {
            "title": str,       # first line of the section
            "text": str,        # full section body
            "page": int,        # starting page number (1-based)
            "chunk_index": int, # position among all chunks
        }
    """
    chunks: list[dict[str, Any]] = []
    current_lines: list[str] = []
    current_title = "introduction"
    current_page = 1
    chunk_index = 0

    def _flush() -> None:
        nonlocal chunk_index
        body = "\n".join(current_lines).strip()
        if body:
            chunks.append(
                {
                    "title": current_title,
                    "text": body,
                    "page": current_page,
                    "chunk_index": chunk_index,
                }
            )
            chunk_index += 1

    for page_num, page_text in pages:
        for line in page_text.splitlines():
            stripped = line.strip()
            if not stripped:
                current_lines.append("")
                continue

            if _SECTION_PATTERN.search(stripped):
                _flush()
                current_lines = [stripped]
                current_title = stripped[:120]  # cap title length
                current_page = page_num
            else:
                current_lines.append(stripped)

    _flush()  # persist the last open section
    return chunks


# ---------------------------------------------------------------------------
# LlamaIndex document builder
# ---------------------------------------------------------------------------

def _build_documents(chunks: list[dict[str, Any]], source: str) -> list[Document]:
    """Convert section chunks into LlamaIndex *Document* objects."""
    docs: list[Document] = []
    for chunk in chunks:
        doc_id = f"{source}::chunk_{chunk['chunk_index']}"
        docs.append(
            Document(
                text=chunk["text"],
                doc_id=doc_id,
                metadata={
                    "title": chunk["title"],
                    "page": chunk["page"],
                    "source": source,
                    "language": "th",
                    "doc_type": "triage_manual",
                },
            )
        )
    return docs


# ---------------------------------------------------------------------------
# pgvector store factory
# ---------------------------------------------------------------------------

def _build_vector_store() -> PGVectorStore:
    """Construct a LlamaIndex PGVectorStore using the application's DATABASE_URL."""
    return PGVectorStore.from_params(
        database="hospital_hotline",
        host="localhost",
        port=5432,
        user=_parse_pg_user(settings.database_url),
        password=_parse_pg_password(settings.database_url),
        table_name=settings.pgvector_table,
        embed_dim=settings.pgvector_embed_dim,
    )


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


# ---------------------------------------------------------------------------
# Clear existing embeddings
# ---------------------------------------------------------------------------

def clear_existing() -> None:
    """Delete all embedded chunks from the pgvector store.

    LlamaIndex PGVectorStore stores rows in a table named
    ``data_{table_name}`` (e.g. ``data_triage_knowledge``).
    This function truncates that table using a synchronous psycopg2 connection
    so it can be called both from the CLI script and from a FastAPI background
    task without async complexity.
    """
    import psycopg2  # psycopg2-binary is a project dependency

    table = f"data_{settings.pgvector_table}"
    dsn = settings.database_url
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {table} CASCADE")  # noqa: S608
        conn.commit()
        logger.info("Cleared all rows from '%s'.", table)
    except Exception:
        conn.rollback()
        # Table may not exist yet (first run) — that's fine
        logger.debug("Truncate of '%s' skipped (table may not exist yet).", table)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main ingest entry-point
# ---------------------------------------------------------------------------

def ingest(pdf_path: str | None = None, clear_first: bool = False) -> int:
    """Parse, embed, and store the triage manual PDF.

    Args:
        pdf_path:    Override the path from *settings.triage_manual_path*.
        clear_first: When True, existing embeddings are deleted before
                     ingesting so the knowledge base is fully replaced.

    Returns:
        Number of document chunks ingested.
    """
    resolved_path = pdf_path or settings.triage_manual_path

    if not Path(resolved_path).is_file():
        logger.error("Triage manual PDF not found at: %s", resolved_path)
        raise FileNotFoundError(f"PDF not found: {resolved_path}")

    if clear_first:
        logger.info("Clearing existing embeddings before re-ingest…")
        clear_existing()

    logger.info("Loading PDF: %s", resolved_path)
    pages = _extract_pages(resolved_path)
    logger.info("  → %d pages extracted", len(pages))

    chunks = _chunk_by_sections(pages)
    logger.info("  → %d sections after chunking", len(chunks))

    documents = _build_documents(chunks, source=resolved_path)

    # Configure the global LlamaIndex embedding model (no OpenAI dependency)
    embed_model = HuggingFaceEmbedding(
        model_name=settings.embed_model,
        query_instruction="query: ",
        text_instruction="passage: ",
    )
    LlamaSettings.embed_model = embed_model
    LlamaSettings.llm = None  # LLM calls are handled externally by pydantic-ai

    vector_store = _build_vector_store()
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    logger.info("Embedding and storing %d document chunks …", len(documents))
    VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
        show_progress=True,
    )

    logger.info(
        "Ingest complete — %d chunks stored in '%s'.", len(documents), settings.pgvector_table
    )

    # Invalidate the cached query engine so the next query uses fresh data
    try:
        from app.services.ai.rag_query import get_rag_query_engine
        get_rag_query_engine.cache_clear()
    except Exception:
        pass

    return len(documents)


def ingest_replace(pdf_path: str | None = None) -> int:
    """Convenience wrapper: clear existing embeddings then ingest.

    Equivalent to ``ingest(pdf_path, clear_first=True)``.
    """
    return ingest(pdf_path=pdf_path, clear_first=True)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        count = ingest(clear_first=True)
        print(f"✓ Ingested {count} chunks successfully.")
    except FileNotFoundError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(1)
