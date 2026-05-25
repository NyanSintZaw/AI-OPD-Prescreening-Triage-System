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

### 1. Database (PostgreSQL 16)

The simplest path is Docker:

```powershell
docker run -d --name hospital-hotline-pg `
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres -e POSTGRES_DB=hospital_hotline `
  -p 5433:5432 postgres:16-alpine

docker cp hospital-hotline-assistant-api/migrations/001_hospital_hotline_schema.sql hospital-hotline-pg:/tmp/schema.sql
docker exec hospital-hotline-pg psql -U postgres -d hospital_hotline -f /tmp/schema.sql
```

### 2. Backend

```powershell
cd hospital-hotline-assistant-api
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then edit DATABASE_URL, Slack webhook, Google AI keys
uvicorn app.main:app --reload
```

Backend serves at `http://127.0.0.1:8000` (docs at `/docs`).

### 3. Frontend

```powershell
cd hospital-hotline-assistant-web
copy .env.example .env
npm install
npm run dev
```

Frontend serves at `http://localhost:5173`.

## Features

- **Multilingual triage** (English, Thai, others via the LLM) — frontdesk mode auto-enables text-to-speech for hands-free patient communication.
- **Rule engine + LLM hybrid** — deterministic emergency triggers always win over LLM classification, so safety-critical keywords (chest pain, can't breathe, etc.) escalate immediately.
- **Department routing** — recommended specialty (ER, cardiology, ENT, …) returned with each turn.
- **Follow-up questions** — backend can request structured clarification before final triage.
- **Slack alerts** — emergency / high-severity events fire a webhook with cooldown + threshold controls (no spam).
- **Admin dashboard** — filterable session list (severity, language, alert status), per-session conversation transcript, and emergency event timeline.

## Repository layout

```
hospital-hotline-assistant-api/    # FastAPI service + SQL schema + AI / Slack integrations
hospital-hotline-assistant-web/    # React/Vite SPA (patient + admin UIs)
```

Each subproject has its own `README.md` with deeper setup and API documentation.

## Credits

The original FastAPI scaffold and database schema for `hospital-hotline-assistant-api/` were authored by [@Khant-SoDOpe](https://github.com/Khant-SoDOpe) in [`Khant-SoDOpe/hospital-hotline-assistant-api`](https://github.com/Khant-SoDOpe/hospital-hotline-assistant-api). This repository extends it with the triage orchestration layer (rule engine, Google AI client, Slack notifier, follow-up question APIs, emergency event handling) and adds the entire web frontend.
