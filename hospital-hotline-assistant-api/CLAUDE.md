# Backend (FastAPI, Python 3.11, uv)

- Run: `uv run uvicorn app.main:app --reload` (:8000). Tests: `uv run pytest -m "not integration"`. Types: Pyright standard.
- ALL routes in `app/main.py`. Raw asyncpg SQL via `app/database.py` — no ORM. Migrations = numbered raw SQL in `migrations/`, applied by `scripts/init_db.py` (idempotent, tracks `schema_migrations`).
- Settings: `app/config.py` (pydantic-settings, `extra="ignore"`). Never read env vars directly.
- `services/triage_service.py` is engine-authoritative: persists exactly what the screening engine decides. The AI engine itself lives in `services/screening/` (has its own CLAUDE.md).
- Patient-facing responses NEVER contain triage level/color/diagnosis — redaction in `triage_payloads.py`, reply validation in `screening/validator.py`. Nurse/admin surfaces show everything.
- Key seams: `screening/his/` (HIS adapters, picked by `HIS_MODE`), `blood_pressure.py` + `bp_rest.py` (Omron cuff + 15-min crisis rest window), `google_stt.py`/`google_tts.py`, `admin_auth.py` (in-memory tokens, lost on restart).
- Voice: `WS /ws/voice/{id}` → `screening/voice_bridge.py`; binary frames = 16 kHz PCM up / 24 kHz down, JSON frames = control.
- Tests are self-contained with in-file fakes (`tests/screening/fakes.py`); no real GCP/DB unless marked `integration`. Triage-quality claims come only from `evals/` harness reports.
