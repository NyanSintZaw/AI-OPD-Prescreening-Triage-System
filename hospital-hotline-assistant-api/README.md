# Hospital Hotline FastAPI Backend

Python FastAPI backend for the AI voice-based hospital hotline MVP. It uses the supplied PostgreSQL schema for anonymous sessions, voice/text messages, symptom intake, severity assessments, department recommendations, routing rules, emergency triggers, emergency events, and admin dashboard summaries.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and update `DATABASE_URL`.
4. Export your database URL: `export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/hospital_hotline"`.
5. Create the database: `createdb -h localhost -U postgres hospital_hotline`.
6. Run the migration: `psql "$DATABASE_URL" -f migrations/001_hospital_hotline_schema.sql`.
7. Start the API: `uvicorn app.main:app --reload`.

If Postgres.app shows a trust authentication permission error, approve the permission dialog in Postgres.app settings or use the localhost command above instead of the default socket connection.

Set `CORS_ORIGINS` in `.env` to allow your frontend origin. The default allows local React/Vite ports `3000` and `5173`.

## AI + Alert Configuration

Set these variables in `.env` for production-like frontdesk triage:

- `GOOGLE_AI_ENABLED=true`
- `GOOGLE_CLOUD_PROJECT=<your-project>`
- `GOOGLE_CLOUD_LOCATION=us-central1`
- `GOOGLE_MODEL_NAME=gemini-2.0-flash`
- `GOOGLE_APPLICATION_CREDENTIALS=<path-to-service-account-json>`
- `SLACK_WEBHOOK_URL=<incoming-webhook-url>`
- `ALERT_SEVERITY_THRESHOLD=emergency`
- `ALERT_COOLDOWN_SECONDS=300`

## Useful Endpoints

- `GET /health`
- `POST /sessions`
- `GET /sessions/{session_id}`
- `PATCH /sessions/{session_id}`
- `POST /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/messages`
- `POST /sessions/{session_id}/chat`
- `POST /sessions/{session_id}/symptoms`
- `POST /sessions/{session_id}/severity-assessments`
- `POST /sessions/{session_id}/follow-up-questions`
- `GET /sessions/{session_id}/follow-up-questions`
- `PATCH /sessions/{session_id}/follow-up-questions/{question_id}/answer`
- `GET /departments`
- `GET /routing-rules`
- `GET /emergency-triggers`
- `POST /sessions/{session_id}/department-recommendations`
- `POST /sessions/{session_id}/emergency-events`
- `GET /sessions/{session_id}/emergency-events`
- `GET /conversation-summary`

Interactive docs are available at `http://localhost:8000/docs` when the server is running.