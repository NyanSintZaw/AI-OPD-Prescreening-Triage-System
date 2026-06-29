"""Unit tests for app.services.ai.rag_ingest — chunking / parsing logic.

All tests run fully offline: no PDF file, no Postgres, no Gemini needed.
"""

from __future__ import annotations

import pytest

from app.services.ai.rag_ingest import (
    _SECTION_KEYWORDS,
    _build_documents,
    _chunk_by_sections,
    _parse_pg_password,
    _parse_pg_user,
)


def _make_pages(*texts: str) -> list[tuple[int, str]]:
    return [(i + 1, t) for i, t in enumerate(texts)]


class TestChunkBySections:
    def test_single_page_no_section_headers_produces_one_chunk(self):
        pages = _make_pages("This text has no triage keywords at all.")
        chunks = _chunk_by_sections(pages)
        assert len(chunks) == 1
        assert chunks[0]["title"] == "introduction"
        assert "no triage keywords" in chunks[0]["text"]

    def test_english_section_keyword_triggers_split(self):
        pages = _make_pages(
            "Preamble text\ntriage level 1\nImmediate life threat\ntriage level 2\nHigh risk"
        )
        chunks = _chunk_by_sections(pages)
        assert len(chunks) == 3
        assert chunks[1]["title"].lower().startswith("triage level")

    def test_thai_section_keyword_triggers_split(self):
        # Avoid using ระดับ as a substring of body text (pattern matches anywhere on line)
        pages = _make_pages(
            "บทนำ\nระดับ 1 ฉุกเฉินวิกฤต\nข้อมูลการดูแล\nระดับ 2 ฉุกเฉิน\nข้อมูลการรักษา"
        )
        chunks = _chunk_by_sections(pages)
        assert len(chunks) == 3  # intro + ระดับ1 + ระดับ2

    def test_multiple_pages_preserves_page_number(self):
        pages = _make_pages(
            "Page one text",
            "fast track criteria\nPatient details",
        )
        chunks = _chunk_by_sections(pages)
        ft = next(c for c in chunks if "fast track" in c["title"].lower())
        assert ft["page"] == 2

    def test_empty_pages_produces_no_chunks(self):
        assert _chunk_by_sections([]) == []

    def test_all_section_keywords_are_detected(self):
        lines = [f"{kw} section content" for kw in _SECTION_KEYWORDS]
        pages = _make_pages("\n".join(lines))
        chunks = _chunk_by_sections(pages)
        assert len(chunks) >= len(_SECTION_KEYWORDS)

    def test_chunk_index_is_sequential(self):
        pages = _make_pages("intro\nระดับ 1 text\nสัญญาณชีพ data\nfast track info")
        chunks = _chunk_by_sections(pages)
        assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))

    def test_very_long_section_title_is_capped_at_120_chars(self):
        long_header = "ระดับ " + "x" * 200
        pages = _make_pages(f"{long_header}\nbody text")
        chunks = _chunk_by_sections(pages)
        section_chunk = next(c for c in chunks if c["title"] != "introduction")
        assert len(section_chunk["title"]) <= 120


class TestBuildDocuments:
    def _sample_chunks(self) -> list[dict]:
        return [
            {"title": "triage level 1", "text": "Cardiac arrest procedures", "page": 1, "chunk_index": 0},
            {"title": "ระดับ 2", "text": "High risk situations", "page": 3, "chunk_index": 1},
        ]

    def test_document_count_matches_chunk_count(self):
        assert len(_build_documents(self._sample_chunks(), "t.pdf")) == 2

    def test_document_metadata_fields(self):
        meta = _build_documents(self._sample_chunks(), "test.pdf")[0].metadata
        assert meta["source"] == "test.pdf"
        assert meta["language"] == "th"
        assert meta["doc_type"] == "triage_manual"
        assert meta["page"] == 1

    def test_document_id_unique_and_contains_source(self):
        docs = _build_documents(self._sample_chunks(), "my.pdf")
        ids = {d.doc_id for d in docs}
        assert len(ids) == 2
        assert all("my.pdf" in i for i in ids)

    def test_document_text_matches_chunk(self):
        docs = _build_documents(self._sample_chunks(), "t.pdf")
        assert docs[0].text == "Cardiac arrest procedures"

    def test_empty_chunks_returns_empty_list(self):
        assert _build_documents([], "t.pdf") == []


class TestDsnParsing:
    DSN = "postgresql://myuser:mypassword@localhost:5432/hospital_hotline"

    def test_parse_user(self):
        assert _parse_pg_user(self.DSN) == "myuser"

    def test_parse_password(self):
        assert _parse_pg_password(self.DSN) == "mypassword"

    def test_user_fallback_on_malformed_dsn(self):
        assert _parse_pg_user("bad") == "postgres"

    def test_password_fallback_on_malformed_dsn(self):
        assert _parse_pg_password("bad") == "postgres"

    def test_default_config_credentials(self):
        from app.config import settings
        assert _parse_pg_user(settings.database_url) == "postgres"
        assert _parse_pg_password(settings.database_url) == "postgres"


def test_ingest_raises_when_pdf_missing():
    from app.services.ai.rag_ingest import ingest
    with pytest.raises(FileNotFoundError, match="PDF not found"):
        ingest(pdf_path="/nonexistent/path/triage.pdf")
