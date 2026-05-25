# Hospital Hotline Assistant — Frontend

React + Vite web app for the AI voice-based hospital hotline MVP. Includes a patient-facing hotline UI and a basic admin dashboard.

## Prerequisites

- Node.js 18+
- Running [FastAPI backend](../hospital-hotline-assistant-api/README.md) on port 8000
- PostgreSQL with schema migrated

## Setup

```bash
cd hospital-hotline-assistant-web
npm install
cp .env.example .env
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_BASE_URL` | `http://localhost:8000` | FastAPI backend URL |
| `VITE_ENABLE_VOICE` | `false` | Enable browser speech recognition mic button |
| `VITE_FRONTDESK_MODE` | `true` | Auto-enable frontdesk-oriented UX (auto TTS) |

AI configuration (Vertex AI, Slack alerts, etc.) lives in the **backend** `.env`. The frontend has no AI provider knobs.

## Routes

| Path | Description |
|------|-------------|
| `/` | Landing page — language selection and start hotline |
| `/chat` | Patient conversation UI |
| `/admin` | Read-only session overview (no auth in MVP) |

## Run with backend

Terminal 1 — backend:

```bash
cd hospital-hotline-assistant-api
uvicorn app.main:app --reload
```

Terminal 2 — frontend:

```bash
cd hospital-hotline-assistant-web
npm run dev
```

## Build

```bash
npm run build
npm run preview
```

## AI engineer handoff

AI orchestration runs entirely in the backend (Vertex AI / Gemini + rule engine). See [AI_INTEGRATION.md](./AI_INTEGRATION.md) for:

- The `POST /sessions/{id}/chat` request / response shape
- Where to wire new triage fields (`useChat.ts` mapping)
- Speech hook integration points

Type "chest pain" / "เจ็บหน้าอก" — the backend's rule engine guarantees an emergency classification even when the LLM is unavailable.

## Security note

The admin dashboard has **no authentication** in this MVP. Add auth before production deployment.

## Design

UI follows the [MFU Medical Center Hospital](https://website01.mch.mfu.ac.th/en/mch-index.html) brand. See [DESIGN.md](./DESIGN.md) for colors, fonts, and tokens.

## Project structure

```
src/
├── api/          # Typed FastAPI client
├── hooks/        # useChat (calls /sessions/{id}/chat), useSession, useSpeech
├── i18n/         # Thai + English strings
├── pages/        # Landing, Chat, Admin
└── components/   # Chat UI, emergency banner, voice controls
```
