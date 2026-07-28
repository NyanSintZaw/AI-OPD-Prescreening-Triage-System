# Hospital Hotline AI

An AI-assisted hospital hotline for the **frontdesk of an emergency ward**. Patients—including non-Thai speakers—interact through a web hotline UI; the system classifies the situation, recommends a department, detects emergencies via a rule engine + LLM, and alerts human staff in real time.

This repository is a monorepo containing two projects:

| Folder | Stack | Purpose |
| --- | --- | --- |
| [`hospital-hotline-assistant-api/`](./hospital-hotline-assistant-api) | FastAPI + PostgreSQL + Google Generative AI + Slack webhooks | Backend triage orchestration, session/message persistence, rule engine, admin endpoints |
| [`hospital-hotline-assistant-web/`](./hospital-hotline-assistant-web) | React + Vite + TypeScript + i18n | Patient hotline UI (frontdesk-friendly), admin dashboard, multilingual speech support |

## Architecture at a glance

```
Patient browser  ──►  React/Vite UI  ──►  POST /sessions/{id}/chat (FastAPI)
                                              │
                                              ├─► Rule engine (emergency triggers + routing)
                                              ├─► Google Generative AI (Gemini) for triage
                                              ├─► PostgreSQL (sessions, messages, severity, departments, emergency events, follow-ups, audit logs)
                                              └─► Slack webhook (emergency / escalation alerts)
```

The backend `chat` endpoint is the single orchestration entry point: it logs the user message, runs rule checks, calls the LLM, persists structured outputs (symptoms, severity, department, follow-ups, emergency events), and triggers alerts. Frontend consumes the response in one round trip.

## Quick start (dev)

### 1. Databases (Docker) — run these in Docker; run the app on your device

Both databases come up with one command from the repo root:

```bash
docker compose up -d      # Postgres (:5432) + mock hospital DB (:8001)
docker compose down       # stop
docker compose down -v    # stop + wipe Postgres data
```

- **postgres** — our database (sessions, criteria, audit …). Once the
  containers are up, one command applies all migrations, seeds criteria, and
  confirms both databases are ready:

  ```bash
  cd hospital-hotline-assistant-api && uv run python scripts/init_db.py
  ```

- **his-mock** — the mock hospital HIS database (separate, SQLite). Auto-seeds
  the synthetic pre-registration sample; reachable at `http://localhost:8001`
  (`/docs` is the "hospital side" window). `init_db.py` health-checks it. See
  [`hospital-his-mock`](./hospital-his-mock).

The backend and frontend run on your device (below), connecting to these on
`localhost`.

### 2. Backend (Python 3.11, managed with [uv](https://docs.astral.sh/uv/))

```bash
cd hospital-hotline-assistant-api
uv sync                                   # install deps (no requirements.txt — uv-managed)
cp .env.example .env                      # then set GOOGLE_CLOUD_PROJECT + GOOGLE_APPLICATION_CREDENTIALS
uv run python scripts/init_db.py          # migrations + criteria + HIS health-check (see step 1)
uv run uvicorn app.main:app --reload      # http://localhost:8000  (docs at /docs; ~15s to warm up)
```

`.env.example` already sets the flags for the new system —
`TRIAGE_ENGINE=langgraph`, `VOICE_ENGINE=turn`, and `HIS_MODE=http` /
`HIS_BASE_URL=http://localhost:8001`. Leave them as-is; just fill in your
Google Vertex project + service-account key. `DATABASE_URL` must match the
Postgres password (`postgres`, per the compose file).

### 3. Frontend (React + Vite)

```bash
cd hospital-hotline-assistant-web
cp .env.example .env                       # VITE_API_BASE_URL defaults to http://localhost:8000
npm install
npm run dev                                # http://localhost:5173
```

### 4. Walk the demo

Open **http://localhost:5173**:

- **Patient booth** (`/patient`) — type a hospital **visit ID** (the mock seeds
  `990000000000000001`–`…008`; `…003` is a child → pediatrics), take/enter
  vitals, then chat in Thai or English.
- **Admin** (`/admin`) — the **🏥 Hospital DB** tab shows the visit go
  `registered → screened → routed` live.
- **Nurse** (`/nurse`) — search by the slip code on the patient's receipt,
  then Confirm / Reroute (this publishes the department + reason back to the
  hospital DB).

## Features

Full list in [`docs/features.md`](./docs/features.md). Highlights:

- **Voice-first bilingual kiosk** (Thai/English) — spoken conversation with tappable quick-reply chips; VN check-in against the hospital HIS, spoken identity confirm, session resume, first-visit history intake.
- **Deterministic 5-level triage** — a pure rules engine decides MOPH acuity from versioned bilingual criteria; the LLM only extracts findings and phrases replies. Patients never see the level (leak validator, th + en).
- **Vitals on demand** — BP cuff / temperature / weight-height requested mid-interview only when the complaint requires them; BP-crisis rest-first protocol.
- **HIS integration** — mock hospital HIS + adapter seam for the real one; two-stage write-back (screening attach → nurse-approved publish).
- **Nurse review portal** — slip-code lookup, editable review, approve/reroute publishing to the HIS.
- **Admin portal** — session monitor with AI trace, criteria lifecycle (upload → approve → activate), RAG manual upload, disease-surveillance dashboard, BP-device and user management.

## Repository layout

```
hospital-hotline-assistant-api/    # FastAPI service + SQL schema + AI / Slack integrations
hospital-hotline-assistant-web/    # React/Vite SPA (patient + admin UIs)
```

Each subproject has its own `README.md` with deeper setup and API documentation.

## Credits

The original FastAPI scaffold and database schema for `hospital-hotline-assistant-api/` were authored by [@Khant-SoDOpe](https://github.com/Khant-SoDOpe) in [`Khant-SoDOpe/hospital-hotline-assistant-api`](https://github.com/Khant-SoDOpe/hospital-hotline-assistant-api). This repository extends it with the triage orchestration layer (rule engine, Google AI client, Slack notifier, follow-up question APIs, emergency event handling) and adds the entire web frontend.
