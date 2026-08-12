# Backend (FastAPI, Python 3.11, uv)

- Run: `uv run uvicorn app.main:app --reload` (:8000). Tests: `uv run pytest -m "not integration"`. Types: Pyright standard.
- Routes live in feature routers under `app/routers/` (shared auth deps in `routers/deps.py`); `app/main.py` only wires lifespan/services + `include_router`. Raw asyncpg SQL via `app/database.py` — no ORM. Migrations = numbered raw SQL in `migrations/`, applied by `scripts/init_db.py` (idempotent, tracks `schema_migrations`).
- Settings: `app/config.py` (pydantic-settings, `extra="ignore"`). Never read env vars directly.
- `services/triage_service.py` is engine-authoritative: persists exactly what the screening engine decides. The AI engine itself lives in `services/screening/` (has its own CLAUDE.md).
- The model is never sent a patient identifier (name/HN/VN/slip/session id/birthdate) — `docs/ai-model-io.md` is the generated contract, `tests/screening/test_no_pii_in_prompts.py` the guard. Production runs it on a hospital workstation via `SCREENING_MODEL_PROVIDER=openai_compatible`.
- Patient-facing responses NEVER contain triage level/color/diagnosis — redaction in `triage_payloads.py`, reply validation in `screening/validator.py`. Nurse/admin surfaces show everything.
- Key seams: `screening/his/` (HIS adapters, picked by `HIS_MODE`), `blood_pressure.py` + `bp_rest.py` (Omron cuff + 15-min crisis rest window), `speech_adapter.py` (STT/TTS provider switch — `STT_PROVIDER`/`TTS_PROVIDER`, `google` default, `openai_compatible` for on-prem whisper/TTS servers), `admin_auth.py` (in-memory tokens, lost on restart).
- Voice: `WS /ws/voice/{id}` → `screening/voice_bridge.py`; binary frames = 16 kHz PCM up / 24 kHz down, JSON frames = control.
- Tests are self-contained with in-file fakes (`tests/screening/fakes.py`); no real GCP/DB unless marked `integration`. Triage-quality claims come only from `evals/` harness reports.
