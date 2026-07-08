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

All routes live in `app/main.py`; persistence is raw SQL via asyncpg (no ORM) through `app/database.py`. Request/response models in `app/schemas.py`; settings in `app/config.py` (pydantic-settings, env vars like `GOOGLE_MODEL_NAME`, `GOOGLE_LIVE_MODEL_NAME`, `PGVECTOR_TABLE`, `EMBED_MODEL`).

**Facade pattern:** the AI code was refactored out of monolithic modules into `app/services/ai/`. `app/services/adk_agent.py`, `app/services/live_voice_service.py`, and `app/services/triage_engine.py` are compatibility facades that re-export from `app/services/ai/*` — the `app/services/ai/` versions are authoritative; edit there.

Three AI stacks coexist, selected by config flags (`TRIAGE_ENGINE=adk|langgraph`, `VOICE_ENGINE=live|turn`, both default to the legacy values):

**Stack C — Deterministic screening engine v2** (`app/services/screening/`, `TRIAGE_ENGINE=langgraph`) — the SRS-mandated rebuild; prefer this for new AI work:
- **Decision separation is the core rule**: the LLM only extracts structured findings from utterances, paraphrases questions, and phrases explanations. A pure rules engine (`rules/`: `red_flags.py`, `disposition.py`, `department_map.py`, `question_policy.py`) decides the MOPH 5-level triage and department routing from versioned criteria. Patients NEVER see the level — replies are validated (`validator.py`) against level/color/diagnosis/prescription leaks in both th and en; nurse/admin surfaces still show everything.
- Criteria live in `app/data/screening_criteria_v1.json` (hand-encoded bilingual from the MFU Thai manual; schema in `rules/criteria_models.py` with a condition AST) and in the `screening_criteria_versions` table (upload → draft → review → approve → activate lifecycle via `/admin/criteria/*`; `criteria_upload.py` does LLM extraction of uploaded documents into drafts; `scripts/seed_screening_criteria.py` seeds v1). Sessions pin their criteria version.
- Each chat turn is one bounded LangGraph invocation (`graph.py`, nodes in `nodes/`): ingest (LLM extraction) → red-flag gate + completeness gate (pure) → question (deterministic pick, verbatim red-flag/scale wording) or dispose → explain (validated, RAG-grounded). Escalation to a nurse is a phase value, not an interrupt. State persists as JSONB in `screening_sessions` via asyncpg (`persistence.py`) — deliberately no LangGraph checkpointer (would require psycopg3).
- `engine.py` (`ScreeningTriageEngine`) implements the same `TriageEngine` protocol as Stack A, so `TriageService`, SSE events, and the frontend contract are unchanged. Model access goes through `model_adapter.py` (LangChain `BaseChatModel`: `vertexai` now, `openai_compatible` for future local LLMs).
- Every LLM call and rules decision writes to `ai_inference_audit` (migration 014): trace API `GET /admin/sessions/{id}/trace`, aggregates `GET /admin/ai-metrics`, nurse-visible `disposition_reasons` with manual citations in reviews.
- `voice_bridge.py` (`TurnVoiceService`, `VOICE_ENGINE=turn`) runs voice calls turn-by-turn through the same pipeline (buffer 16 kHz PCM → end-of-turn or silence fallback → STT → `process_chat_stream` → TTS LINEAR16 24 kHz), duck-typing `LiveVoiceService` so the WS route/frontend are untouched.
- `his/` holds the HIS integration seam (`HisAdapter` protocol + `MockHisAdapter`).

**Stack A — Google ADK + Gemini on Vertex AI** (legacy chat/voice engine, `app/services/ai/`, `TRIAGE_ENGINE=adk`):
- `agent_factory.py` builds an `LlmAgent` tree: `HotlineOrchestrator` → `TriageAgent` + `ContactPreferenceAgent`, with `FunctionTool`s defined in `tools.py` (`classify_triage_level`, `search_indexed_triage_manual`, `get_triage_reference`, `get_department_list`, `record_contact_preference`). Prompts in `prompts.py`.
- Chat history lives in a module-level ADK `InMemorySessionService` keyed by session_id — not in the DB.
- Text path: `text_runner.py` (`HotlineADKRunner`) wrapped by `triage_engine.py` (`LlmTriageEngine`).
- Voice path: `live_runner.py` / `live_service.py` (`LiveVoiceService`) use ADK `run_live` with the Gemini Live native-audio model — Gemini Live handles STT/TTS itself; the REST `/tts` and `/stt` endpoints (`google_tts.py` / `google_stt.py`) are a separate one-shot speech path.
- `reference_data.py` loads static JSON from `app/data/` (`departments.json`, `er_triage_five_level_system.json`) with in-code fallbacks.

**Stack B — pydantic-ai + LlamaIndex RAG** (`POST /triage/rag`, deprecated — kept for comparison only):
- `triage_rag_agent.py`: layer 1 hard rules (`rule_engine.py`: emergency triggers, routing rules) return immediately if matched; layer 2 a pydantic-ai agent with a pgvector search tool.
- `rag_query.py` — shared LlamaIndex query engine over `PGVectorStore` (table `triage_knowledge`, 384-dim multilingual embeddings); also serves the ADK `search_indexed_triage_manual` tool.
- `rag_ingest.py` — `POST /admin/triage-manual/upload` saves the triage-manual PDF to `app/data/triage_manual.pdf` and re-ingests into pgvector as a background task.

**Text triage flow** (`POST /sessions/{id}/chat` → `TriageService.process_chat` in `app/services/triage_service.py`): prepare turn (persist message, load reference data, run rule engine) → ADK agent run → finalize: severity decided by an override chain (ADK classification → emergency keyword trigger → routing-rule override → pain/distress scale override; nothing downgrades an emergency), department resolved OPD-first (levels 1–2 forced to `emergency`), rows written to `symptom_entries`, `severity_assessments`, `department_recommendations`, `assessment_reviews`, `disease_surveillance`, and staff notified (`notification_service.py`). The `/chat/stream` variant emits SSE events and drives a `contact_flow` state machine in session metadata.

**Live voice flow** (`WS /ws/voice/{session_id}`): browser streams 16 kHz PCM up / receives 24 kHz PCM down. With `VOICE_ENGINE=live`, on call end the accumulated transcript + captured classification replay into `TriageService.finalize_live_assessment`, persisting the same rows as a text turn without re-invoking the LLM. With `VOICE_ENGINE=turn`, every turn persists as it happens through `process_chat_stream` — no replay.

Admin auth is in-memory bearer tokens (`admin_auth.py`, roles `super_admin`/`admin`/`viewer`) — tokens vanish on restart.

**Tests** (`tests/`): self-contained unit tests with in-file fakes and monkeypatching against `app/services/ai/*`; no real Google/DB calls except tests marked `integration`. `tests/screening/` covers the v2 engine: table-driven rules tests from the seed criteria, graph/engine tests with a `FakeChatModel` (`fakes.py`), golden end-to-end transcripts (`test_golden_transcripts.py`) that validator-check every reply in both languages, and voice-bridge tests. When touching triage behavior, run the suite under both `TRIAGE_ENGINE` values.

### Frontend

React 19 SPA, react-router v7 (`src/App.tsx`): patient routes `/patient`, `/call`, `/chat` (no auth); staff routes `/nurse`, `/admin` gated by `ProtectedRoute` with roles from localStorage. State is hand-rolled hooks + localStorage (react-query is installed but unused).

Backend communication (`src/api/client.ts`, base URL from `VITE_API_BASE_URL`):
- REST via a single `api` fetch wrapper (`src/api/index.ts`), bearer token auto-injected
- SSE: `api.chatStream()` parses `POST /sessions/{id}/chat/stream` events
- WebSocket: `src/hooks/useVoiceCall.ts` (~1000 lines) is the live-call engine — an inline AudioWorklet downsamples mic audio to 16 kHz Int16 PCM sent as binary frames to `WS /ws/voice/{session_id}`; 24 kHz PCM replies play through a gap-free scheduler; JSON control frames carry transcripts, emergency banners, `assessment_complete`, mute/end-call.

i18n: i18next with inline resources in `src/i18n/resources.ts` — exactly two languages (`th` default, `en`); update both blocks when adding strings. Styling is plain global CSS with design tokens in `src/styles/tokens.css` (MFU brand vars like `--mch-cyan`) — no Tailwind/CSS Modules. `RecommendationCard.tsx` renders triage results and embeds the static wayfinding map from `public/hospital-map/` via iframe.
