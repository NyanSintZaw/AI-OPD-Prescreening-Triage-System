# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AI-assisted hospital hotline triage system for Mae Fah Luang University (MFU) Medical Center. Anonymous patients describe symptoms via text chat or live voice call; an AI agent performs ER Five-Level triage, recommends a department (OPD-first policy), and stores results in Postgres for a nurse-review admin portal and disease-surveillance dashboard.

Monorepo with two subprojects:
- `hospital-hotline-assistant-api/` — FastAPI backend (Python 3.11, managed with **uv**)
- `hospital-hotline-assistant-web/` — React 19 + Vite + TypeScript SPA

UI languages: Thai (default) and English.

## Commands

### Backend (`hospital-hotline-assistant-api/`)

The READMEs mention `pip install -r requirements.txt`, but no requirements.txt exists — the project is uv-managed (`pyproject.toml` + `uv.lock`):

```bash
uv sync                                        # install deps (incl. dev group: pytest, pytest-asyncio)
uv run uvicorn app.main:app --reload           # run server → http://localhost:8000 (docs at /docs)
uv run pytest                                  # run all tests
uv run pytest -m "not integration"             # skip tests needing a live backend + DB
uv run pytest tests/test_rag_query.py          # run one test file
uv run pytest tests/test_rag_query.py::test_name   # run one test
```

pytest is configured with `asyncio_mode = "auto"` — async tests need no decorator. Type checking is Pyright (`pyrightconfig.json`, standard mode). No linter/formatter is configured.

Database (PostgreSQL 16 + pgvector):

```bash
docker compose up -d                           # root compose: postgres :5432 + mock hospital DB (HIS) :8001
uv run python scripts/init_db.py               # one command: applies ALL migrations (idempotent, tracks in schema_migrations), seeds criteria v1, health-checks the mock HIS
# manual alternative: psql "$DATABASE_URL" -f migrations/00X_*.sql (raw SQL, in order, no Alembic)
uv run python scripts/seed_screening_criteria.py   # criteria-only reseed/refresh (init_db.py already runs this)
```

The mock hospital HIS (`hospital-his-mock/`) is a separate SQLite service that auto-seeds itself on startup; `init_db.py` only health-checks it. Both DBs run via Docker; the app runs on the host.

Config comes from `.env` (copy `.env.example`). `scripts/` has connectivity checkers (`check_db.py`, `check_vertex.py`, etc.).

### Frontend (`hospital-hotline-assistant-web/`)

```bash
npm install
npm run dev        # Vite dev server → http://localhost:5173
npm run build      # tsc && vite build
npm run preview
```

No lint or test setup exists. Env via `.env` (copy `.env.example`): `VITE_API_BASE_URL`, `VITE_ENABLE_VOICE`, `VITE_FRONTDESK_MODE`, `VITE_VOICE_DEBUG`.

## Architecture

### Backend

All routes live in `app/main.py`; persistence is raw SQL via asyncpg (no ORM) through `app/database.py`. Request/response models in `app/schemas.py`; settings in `app/config.py` (pydantic-settings, env vars like `SCREENING_MODEL_NAME`, `HIS_MODE`, `PGVECTOR_TABLE`, `EMBED_MODEL`). `Settings` uses `extra="ignore"` so retired env vars in older `.env` files don't break startup.

**One AI engine — the deterministic screening engine (LangGraph)** (`app/services/screening/`). The older ADK (Stack A) and pydantic-ai RAG (Stack B) stacks and the legacy keyword `rule_engine` have been removed; there are no `TRIAGE_ENGINE`/`VOICE_ENGINE` flags. `TriageService` (`app/services/triage_service.py`) is engine-authoritative: it persists exactly the engine's decision — no override chain, no keyword rules.

- **Decision separation is the core rule**: the LLM only extracts structured findings from utterances, paraphrases questions, and phrases explanations. A pure rules engine (`rules/`: `red_flags.py`, `disposition.py`, `department_map.py`, `question_policy.py`) decides the MOPH 5-level triage and department routing from versioned criteria. Patients NEVER see the level — replies are validated (`validator.py`) against level/color/diagnosis/prescription leaks in both th and en; nurse/admin surfaces still show everything.
- Criteria live in `app/data/screening_criteria_v1.json` (hand-encoded bilingual from the MFU Thai manual; schema in `rules/criteria_models.py` with a condition AST) and in the `screening_criteria_versions` table (upload → draft → review → approve → activate lifecycle via `/admin/criteria/*`; `criteria_upload.py` does LLM extraction of uploaded documents into drafts; `scripts/seed_screening_criteria.py` seeds v1, which `init_db.py` runs). Sessions pin their criteria version.
- Each chat turn is one bounded LangGraph invocation (`graph.py`, nodes in `nodes/`): ingest (LLM extraction) → red-flag gate + completeness gate (pure) → question (deterministic pick, verbatim red-flag/scale wording) or dispose → explain (validated, RAG-grounded). Escalation to a nurse is a phase value, not an interrupt. State persists as JSONB in `screening_sessions` via asyncpg (`persistence.py`) — deliberately no LangGraph checkpointer (would require psycopg3).
- `engine.py` (`ScreeningTriageEngine`, built by `make_triage_engine`) implements the `TriageEngine` protocol (`app/services/ai/triage_models.py`) so `TriageService`, SSE events, and the frontend contract are unchanged. `run_turn` accepts a `turn_context` of objective inputs (age from a linked HIS visit, measured vitals) that the engine merges into state **before** the red-flag gate — so a cuff reading of 200/120 disposes emergency on turn 1 (see `_turn_context` in `triage_service.py`, `vitals.py`). Model access goes through `model_adapter.py` (LangChain `BaseChatModel`: `vertexai` Gemini now, `openai_compatible` for future local LLMs).
- Every LLM call and rules decision writes to `ai_inference_audit` (migration 014): trace API `GET /admin/sessions/{id}/trace`, aggregates `GET /admin/ai-metrics`, nurse-visible `disposition_reasons` with manual citations in reviews.
- `voice_bridge.py` (`TurnVoiceService`, the only voice service) runs voice calls turn-by-turn through the same pipeline (buffer 16 kHz PCM → end-of-turn or silence fallback → STT → `process_chat_stream` → TTS LINEAR16 24 kHz). STT/TTS are the Google Cloud one-shot clients (`google_stt.py`/`google_tts.py`), language-selected (`th-TH`/`en-US`).
- `his/` holds the HIS integration seam: `HisAdapter` protocol, `MockHisAdapter` (logs), `HttpHisAdapter` (real HIS or the `hospital-his-mock` service), `department_map.py` (our codes → verbatim HIS names), `build_his_adapter(settings)` (picks by `HIS_MODE`). Two-stage write-back and the before/after demo model are documented in `docs/his-integration.md`.

**RAG grounding** (`app/services/ai/rag_query.py` + `rag_ingest.py`): LlamaIndex over `PGVectorStore` (table `triage_knowledge`, 384-dim multilingual embeddings, **pgvector required** — use the `pgvector/pgvector:pg16` image). `POST /admin/triage-manual/upload` saves the manual PDF and re-ingests as a background task. The screening `explain` node retrieves top passages (`response_mode="no_text"`, so LlamaIndex's `MockLLM` is never used) to ground non-emergency explanations; decisions work without it.

**Text triage flow** (`POST /sessions/{id}/chat` → `TriageService.process_chat`): prepare turn (persist message, load departments) → one screening-engine turn → finalize: persist the engine's severity + department OPD-first (levels 1–2 forced to `emergency`; interview turns stay `unknown`/no-department), rows written to `symptom_entries`, `severity_assessments`, `department_recommendations`, `assessment_reviews`, `disease_surveillance`. The `/chat/stream` variant emits SSE events and drives a `contact_flow` state machine in session metadata. `assessment_status` is `complete` iff `severity_level != "unknown"` — patient severity is redacted to `"unknown"` (`triage_payloads.py`).

**Voice flow** (`WS /ws/voice/{session_id}`): browser streams 16 kHz PCM up / receives 24 kHz PCM down; every turn persists as it happens through `process_chat_stream`. Binary WS frames are mic PCM; JSON control frames are `mute`/`unmute`/`end_of_turn`/`end_call`.

Admin auth is in-memory bearer tokens (`admin_auth.py`, roles `super_admin`/`admin`/`viewer`) — tokens vanish on restart.

**Tests** (`tests/`): self-contained unit tests with in-file fakes; no real Google/DB calls except tests marked `integration`. `tests/screening/` covers the engine: table-driven rules tests from the seed criteria, graph/engine tests with a `FakeChatModel` (`fakes.py`), golden end-to-end transcripts (`test_golden_transcripts.py`) validator-checking every reply in both languages, HIS adapter/write-back tests, voice-bridge tests (incl. a Thai turn), and `test_engine_authority.py` (interview turns stay in_progress; disposed turns persist the engine's department). Run `uv run pytest -m "not integration"`.

### Frontend

React 19 SPA, react-router v7 (`src/App.tsx`): patient routes `/patient`, `/call`, `/chat` (no auth); staff routes `/nurse`, `/admin` gated by `ProtectedRoute` with roles from localStorage. State is hand-rolled hooks + localStorage (react-query is installed but unused).

Backend communication (`src/api/client.ts`, base URL from `VITE_API_BASE_URL`):
- REST via a single `api` fetch wrapper (`src/api/index.ts`), bearer token auto-injected
- SSE: `api.chatStream()` parses `POST /sessions/{id}/chat/stream` events
- WebSocket: `src/hooks/useVoiceCall.ts` (~1000 lines) is the live-call engine — an inline AudioWorklet downsamples mic audio to 16 kHz Int16 PCM sent as binary frames to `WS /ws/voice/{session_id}`; 24 kHz PCM replies play through a gap-free scheduler; JSON control frames carry transcripts, emergency banners, `assessment_complete`, mute/end-call.

i18n: i18next with inline resources in `src/i18n/resources.ts` — exactly two languages (`th` default, `en`); update both blocks when adding strings. Styling is plain global CSS with design tokens in `src/styles/tokens.css` (MFU brand vars like `--mch-cyan`) — no Tailwind/CSS Modules. `RecommendationCard.tsx` renders triage results and embeds the static wayfinding map from `public/hospital-map/` via iframe.
