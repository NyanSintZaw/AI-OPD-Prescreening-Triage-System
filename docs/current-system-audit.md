# Current System Audit

**Repository:** `NyanSintZaw/AI-OPD-Prescreening-Triage-System`  
**Audited branch:** local `main`, aligned with `origin/main` at the time of review  
**Audit date:** 2026-06-29  
**Scope:** source-code audit of the FastAPI backend, React frontend, SQL migrations, tests, and bundled reference data. This is an implementation audit, not a clinical validation or a live-environment/database audit.

## Executive summary

The repository implements a bilingual patient chat and Gemini Live voice screening experience, nurse review and schedule-management screens, an admin monitoring/surveillance screen, database-backed rules, and a separate RAG/manual pipeline. The most important architectural fact is that there are currently **two separate triage pipelines**:

1. Normal patient chat and live calls use the Google ADK triage agent, the bundled static `er_triage_five_level_system.json`, the bundled department JSON, database emergency/routing rules, pain/distress overrides, and today's doctor schedule context.
2. `POST /triage/rag` uses database rules first and the uploaded-manual vector index only when no rule matches. No frontend code calls this endpoint, and it does not persist the normal session assessment/review records.

> **Are current screening steps grounded in the uploaded manual?**  
> **No—not in the patient-facing chat or live-call workflows.** Uploading a manual replaces the PDF and its pgvector embeddings, but normal `/sessions/{id}/chat`, `/chat/stream`, and `/ws/voice/{id}` screening never query those embeddings. They are grounded in the bundled static ESI-style JSON plus the ADK prompt and then overridden/supplemented by DB rules. Only the standalone, backend-only `/triage/rag` endpoint queries the uploaded manual, and even there a matching DB rule returns before RAG is used.

There are also material authorization inconsistencies: the frontend treats the `admin` role as a nurse and bars it from `/admin`, while the backend grants `admin` most administrative operations; `super_admin` is barred from the nurse UI despite being accepted by the backend; and `viewer` can open admin tabs whose APIs reject it. Most patient/session and read-only clinical endpoints are entirely unauthenticated, including transcripts and doctor records.

## Architecture

```text
Patient browser
  ├─ /chat ── SSE or JSON ──> /sessions/{id}/chat[/stream]
  │                              │
  │                              v
  │                    TriageService + ADK text runner
  │                              │
  └─ /call ── PCM WebSocket ─> /ws/voice/{id} ─> Gemini Live/ADK
                                 │                    │
                                 └──── finalizes via TriageService
                                                      │
        static ESI JSON + department JSON ────────────┤
        PostgreSQL emergency/routing rules ───────────┤
        today's doctor schedules ─────────────────────┤
                                                      v
                              PostgreSQL session/messages/assessment/review/
                              recommendation/surveillance records

Nurse UI (/nurse) ──> review/correct assessments + manage doctors/schedules
Admin UI (/admin)  ──> session monitoring + surveillance + manual upload

Manual PDF upload ──> background ingest ──> pgvector
                                             │
backend-only POST /triage/rag ── DB rules ───┴─> RAG LLM (only if no rule match)
```

## Feature inventory by audience

### 1. Patient

Implemented and exposed in the UI:

- `/patient` landing page with Thai/English language selection and entry points for call, chat, and an interactive hospital map.
- Anonymous session creation; the session UUID is stored in browser storage.
- `/chat` supports persisted conversation history, streaming assistant text over SSE, typed input, microphone clips through Google STT, optional TTS playback, reset/new-session behavior, and assessment completion.
- Chat presents severity, recommended department, emergency information, contact-preference follow-up, a patient ID/pass, and hospital map routing after completion.
- `/call` captures 16 kHz PCM microphone audio and receives 24 kHz model audio over WebSocket. It supports mute, speaker toggle, end-of-turn/end-call controls, live transcripts, emergency/assessment events, auto-end after assessment, and the same recommendation/pass UI.
- Patients can submit an area/location after assessment for surveillance aggregation.
- Post-triage hospital contact preference and phone-number collection exist in text and live flows.
- The landing page hospital map is a frontend-only pathfinding feature backed by static map assets.

Limitations:

- There is no patient authentication or ownership check. Anyone who knows a session UUID can read or mutate that session and its messages.
- A refreshed backend loses ADK in-memory conversation state even though messages remain in PostgreSQL; the normal text runner does not rebuild model history from DB messages.
- The patient UI never invokes `/triage/rag`, so manual upload has no effect on its screening.
- The `ChatRequest.history` field exists but is ignored by the backend.

### 2. Nurse

Implemented and exposed at `/nurse` for frontend role `admin`:

- Pending assessment queue, optional contact-request filter, transcript modal, proposed-department display, AI score (1–10), approve action, and correction to another department with a reason.
- Approval creates a confirmed recommendation; correction creates both a confirmed recommendation and routing-feedback record.
- Routing-feedback history is displayed.
- Doctor profile management: create, edit, activate/deactivate, assign department, specialization, extension, and notes.
- Date-specific doctor schedule management: add/upsert, edit, delete, time range, breaks, room, label, availability, notes, and filter from a date.

Limitations:

- The database has no `nurse` role; “nurse” is represented by the generic `admin` enum value.
- The review screen hard-codes the filter to `pending`; approved/corrected history is not selectable even though the API supports it.
- There is no nurse-specific backend namespace or audit-log write for review/schedule actions.
- Backend docstrings say schedule writes require “admin or nurse,” but the actual accepted roles are `admin` and `super_admin`.

### 3. Admin

Implemented and exposed at `/admin` for frontend roles `super_admin` and `viewer`:

- Session dashboard with 30-second optional refresh, status/severity/language/search filtering, conversation transcript detail, and emergency-event detail.
- Disease/outbreak surveillance dashboard.
- Triage-manual PDF upload/status interface.
- Login with an in-memory bearer token and role stored in local storage.

Limitations:

- The frontend excludes role `admin` from this portal even though backend endpoints such as conversation summary, surveillance, and manual management accept it.
- A `viewer` can see the manual-upload tab, but backend upload and status endpoints reject `viewer`; the component therefore cannot work correctly for that role.
- There is no user-management UI/API, logout/revocation endpoint, refresh token, durable token store, or audit-log API.

## Backend/API implementation

`app/main.py` is a single FastAPI application containing all routes. Startup creates the asyncpg pool, an in-memory admin token dictionary, Google STT/TTS clients, `TriageService`, and the live voice service. CORS is configurable. PostgreSQL foreign-key and unique violations have global JSON handlers.

Administrative authentication is custom: login verifies a SHA-256-style stored password through `admin_auth.py`, issues an opaque token held only in `app.state.admin_tokens`, and re-reads the active user from the DB per request. Tokens disappear on process restart and are not shared between multiple API processes.

### Endpoint inventory grouped by effective access

“Public” below means no `require_roles` dependency is present. It does not imply that the endpoint is safe to expose publicly.

#### Public/system and patient/session endpoints

| Method | Endpoint | Purpose / UI usage |
|---|---|---|
| GET | `/` | Service metadata; backend-only |
| GET | `/health` | DB-backed health check; API client exposes it |
| POST | `/admin/login` | Staff login |
| POST | `/sessions` | Create anonymous patient session; patient UI |
| GET | `/sessions/{session_id}` | Read session; API client only |
| PATCH | `/sessions/{session_id}` | Complete/reset/escalate session; patient UI |
| PUT | `/sessions/{session_id}/location` | Store reported area; chat UI |
| POST | `/sessions/{session_id}/messages` | Raw message creation; API client only |
| GET | `/sessions/{session_id}/messages` | Transcript; chat, nurse, and admin UIs |
| POST | `/sessions/{session_id}/chat` | Non-streaming normal ADK triage; supported by hook/API |
| POST | `/sessions/{session_id}/chat/stream` | Streaming normal ADK triage; main chat UI path |
| POST | `/sessions/{session_id}/symptoms` | Raw symptom-row creation; API client only |
| POST | `/sessions/{session_id}/severity-assessments` | Raw assessment creation; API client only |
| POST/GET | `/sessions/{session_id}/follow-up-questions` | Legacy structured follow-ups; API client only; normal ADK flow no longer writes them |
| PATCH | `/sessions/{session_id}/follow-up-questions/{question_id}/answer` | Link an answer; API client only |
| GET | `/departments` | Active departments; patient/nurse/call UI |
| GET | `/routing-rules` | Active DB rules; API client only |
| GET | `/emergency-triggers` | Active DB triggers; API client only |
| POST | `/sessions/{session_id}/department-recommendations` | Raw recommendation creation; API client only |
| POST | `/sessions/{session_id}/emergency-events` | Raw emergency-event creation; API client only |
| GET | `/sessions/{session_id}/emergency-events` | Event detail; admin UI |
| POST | `/tts` | Google TTS; chat UI |
| POST | `/stt` | Google STT for short recordings; chat UI |
| WS | `/ws/voice/{session_id}` | Gemini Live bidirectional voice call; call UI |
| GET | `/doctors` | List doctors; nurse UI, but unauthenticated |
| GET | `/doctors/{doctor_id}` | Doctor and schedules; nurse UI, but unauthenticated |
| GET | `/doctors/{doctor_id}/schedules` | Schedule list; nurse UI, but unauthenticated |
| GET | `/schedules/available` | Available doctors by date/optional department; API client and AI-facing intent, but not directly used by a page |
| POST | `/triage/rag` | Standalone DB-rule + uploaded-manual RAG decision; backend-only and unauthenticated |

#### `admin` and `super_admin`

| Method | Endpoint | Purpose / UI usage |
|---|---|---|
| GET | `/admin/reviews` | List review queue; nurse UI |
| POST | `/admin/reviews/{assessment_id}/approve` | Approve assessment; nurse UI |
| POST | `/admin/reviews/{assessment_id}/correct` | Correct routing and write feedback; nurse UI |
| GET | `/admin/feedback` | Feedback history; nurse UI |
| POST | `/doctors` | Create doctor; nurse UI |
| PATCH | `/doctors/{doctor_id}` | Edit/activate doctor; nurse UI |
| POST | `/doctors/{doctor_id}/schedules` | Add/upsert dated slot; nurse UI |
| PATCH | `/doctors/{doctor_id}/schedules/{schedule_id}` | Replace slot values; nurse UI |
| DELETE | `/doctors/{doctor_id}/schedules/{schedule_id}` | Delete slot; nurse UI |
| POST | `/admin/triage-manual/upload` | Save PDF and start background replace-ingest; admin UI |
| GET | `/admin/triage-manual/status` | Latest upload status; admin UI |

#### `admin`, `super_admin`, and `viewer`

| Method | Endpoint | Purpose / UI usage |
|---|---|---|
| GET | `/conversation-summary` | Latest 100 sessions; admin UI |
| GET | `/admin/surveillance` | Aggregated surveillance; admin UI |

There are no super-admin-only endpoints. The distinction between `super_admin` and `admin` is almost entirely a frontend portal distinction.

## Screening and triage logic

### Normal text screening

The normal `/chat` and `/chat/stream` flow is:

1. Validate the session and persist the user message.
2. Load active departments, emergency triggers, and routing rules from PostgreSQL.
3. Evaluate simple lowercase substring/`all`/`any` matching against the **current user turn only**.
4. Build a text block with today's available doctor schedules.
5. Run the Google ADK triage agent. Its tools expose:
   - the complete bundled `app/data/er_triage_five_level_system.json`;
   - the bundled `app/data/departments.json`;
   - `classify_triage_level`; and
   - the contact-preference tool (in the applicable runner/phase).
6. Convert ADK levels 1–2 to `emergency`, level 3 to `urgent`, levels 4–5 to `general`, and an absent classification to `unknown`.
7. Apply overrides in this order: ADK decision, DB emergency keyword trigger, DB routing-rule severity, then pain/distress escalation. Later stages can escalate but should not downgrade an emergency.
8. Resolve the department by ADK department **code**, otherwise a matched DB rule's department **UUID**, otherwise emergency or `opd_general` fallback.
9. Persist symptom, severity assessment, recommendation, pending nurse review, assistant message, session metadata, and surveillance data.

Follow-up questions are conversational text generated by the agent. The older `follow_up_questions` table/endpoints are not used by the normal pipeline.

### Live voice screening

The WebSocket bridge sends raw browser PCM to the Gemini Live/ADK pipeline and streams model audio/transcripts back. Live classification uses the same static ADK tools/reference and ultimately calls `TriageService.finalize_live_assessment`, so it shares DB rule checks, persistence, recommendation, review, and surveillance behavior with normal text. It does **not** use uploaded-manual RAG.

The live implementation includes mute/unmute, manual end-of-turn, contact-preference handling, assessment callback, and auto-completion. Notifications use `MockNotificationService`; there is no real dispatch integration.

### What sources affect normal screening?

| Source | Normal chat | Live call | Standalone `/triage/rag` |
|---|---:|---:|---:|
| Static ESI JSON | Yes | Yes | Not directly |
| DB emergency/routing rules | Yes | Yes, at finalization/current aggregated transcript | Yes; first layer |
| Uploaded triage-manual RAG | **No** | **No** | Yes, only when no DB rule matches |
| Today's doctor schedule context | Yes, injected into agent turn | Available to the live service/agent flow | No |

Schedule context is informational: it lets the agent answer availability questions. It does not itself select triage severity or constrain the recommended department to a doctor who is available.

## RAG and manual upload

Implemented:

- Admin PDF-only upload with empty-file and 50 MB checks.
- The file overwrites a configured fixed path (`app/data/triage_manual.pdf` by default).
- An upload metadata row is inserted with `processing`; a background thread clears the existing vector table, extracts/chunks the PDF, embeds chunks with a Hugging Face model, stores them in PostgreSQL/pgvector, clears the cached query engine, and marks the upload `ready` or `failed`.
- The admin component polls latest upload status and displays filename, size, chunk count, and errors.
- `/triage/rag` runs DB emergency and routing rules before a pydantic-ai agent whose tool retrieves the top three manual passages.

Gaps and risks:

- No frontend calls `/triage/rag`, and it is not integrated into `TriageService` or live voice.
- Rule matches bypass manual retrieval completely.
- `/triage/rag` is unauthenticated, stateless, does not validate that an upload is `ready`, and does not persist assessment/review/audit records.
- The RAG routing-rule branch puts a department UUID into a field named `department_code`; the LLM branch expects a code. This is a concrete `department_code` versus `department_id` mismatch.
- The safe fallback returns `department_code: "general_opd"`, but the seeded/current code is `opd_general`.
- Retrieval failure returns “use clinical judgement” text to the model rather than failing closed or forcing nurse-only handling.
- Vector storage is created by LlamaIndex (`data_{pgvector_table}`), not declared in the numbered SQL migrations. Configuration hard-codes database name/host/port in the RAG vector-store constructors and only parses user/password from `DATABASE_URL`, which can diverge from deployment configuration.
- “Replace” truncates old embeddings before the new ingest succeeds. A failed ingest can leave no usable manual while the old upload record may still say `ready`.
- The fixed PDF path and process-local background task are unsafe for concurrent uploads and multi-instance deployments.

## Doctor schedule management

Migration 006 introduced weekly schedules; migration 007 intentionally drops that table and recreates date-specific schedules. Current schemas and APIs correctly use `schedule_date`, start/end, optional break, room, label, availability, and notes. Nurse UI supports doctor and slot CRUD. Public read endpoints expose doctors and schedules.

Normal text triage queries the DB directly for **today** and injects available doctors into the agent context. Historical slots remain for audit. The API `/schedules/available` supports another date and optional department, but its frontend wrapper exposes only the date argument and no current page calls it.

Known schedule issues:

- Invalid `from_date` and `schedule_date` strings silently degrade to no filter/today rather than return 400.
- Schedule update does not translate DB check/unique violations as carefully as schedule creation.
- Break ordering/containment is not constrained by DB or Pydantic.
- Read endpoints are public; write endpoints accept `admin`/`super_admin`.

## Disease/outbreak surveillance

Implemented capture paths:

- During triage finalization, one row per session is upserted from AI red flags/symptom summary or matched rule/trigger keywords.
- When a session is marked `completed`, an asynchronous Gemini surveillance extractor reprocesses eligible conversation text and saves richer disease keywords.
- Patient area is stored on the session and copied into surveillance data.
- Admin aggregation reports total rows, top symptoms, symptom/area combinations, daily trend, severity distribution, and alerts where a keyword/area has at least three recent cases and either no previous cases or at least a 2× increase.
- Admin UI offers time-window selection and visual summary tables/cards.

Limitations:

- “Keywords” can contain a full free-text symptoms summary, so aggregation may fragment into near-unique strings rather than normalized disease/symptom concepts.
- The dashboard counts surveillance rows/classification events, not verified diagnoses or epidemiologically deduplicated patients.
- `days` has no bounds validation; zero/negative or very large values are accepted.
- Daily grouping is UTC, not the configured Asia/Bangkok/local hospital day.
- Background extraction is fire-and-forget with no durable job queue or retry status.
- There is no alert acknowledgement, investigation workflow, export, notification, or public-health integration.

## Database schema and persistence

The migrations define:

- Core enums: language, session status, message role/input mode, severity, admin role, department kind, and review status.
- Core clinical data: sessions, messages, symptom entries, follow-up questions, severity assessments, departments, routing rules, emergency triggers/events, and department recommendations.
- Operations: admin users, audit logs, assessment reviews, routing feedback, doctors, dated schedules, surveillance, and manual-upload metadata.
- `conversation_summary` view for latest severity/recommendation/message counts.

Important observations:

- Migration 009 adds the unique `disease_surveillance(session_id)` constraint required by the application's `ON CONFLICT (session_id)` upsert.
- There is no migration 010; numbering jumps from 009 to 011. This is not intrinsically fatal but should be documented by the migration runner.
- SQL migrations are plain files; there is no schema-version table or migration framework shown, so ordering/idempotency depends on operational scripts.
- Migration 007 destroys weekly schedule data by dropping the table, as its comment acknowledges.
- `audit_logs` exists but application routes do not write to it.
- Contact preference is stored as loosely typed keys in `sessions.metadata`, not a dedicated table.
- The application creates a new severity assessment and pending review on every finalized turn, potentially producing multiple review items per patient session.

## UI versus backend-only features

| Capability | UI status | Backend status |
|---|---|---|
| Normal chat/streaming triage | Patient UI | Implemented and persisted |
| Live Gemini voice call | Patient UI | Implemented via WebSocket |
| Static hospital map | Patient/nurse recommendation UI | Frontend-only assets/pathfinding |
| Nurse review/correction | Nurse UI | Implemented |
| Doctor/schedule CRUD | Nurse UI | Implemented |
| Session monitoring | Admin UI | Implemented |
| Surveillance | Admin UI | Capture + aggregate API implemented |
| Manual upload/status | Admin UI | Implemented, role mismatch for viewer |
| Hybrid manual RAG triage | **No UI** | Standalone `/triage/rag` only |
| Raw symptom/assessment/recommendation/event CRUD | No direct UI | Public low-level endpoints |
| Structured follow-up-question CRUD | No current UI flow | Legacy endpoints remain |
| Available-doctors query | No direct page usage | Public endpoint + API wrapper |
| Audit logs/user administration | No UI | Table only; no routes |

## Permission and role mismatches

| Area | Frontend | Backend | Effect |
|---|---|---|---|
| Nurse portal | Only `admin` | Reviews/schedule writes allow `admin`, `super_admin` | Super admin cannot reach UI capabilities it is authorized to use |
| Admin portal | Only `super_admin`, `viewer` | Summary/surveillance allow all three roles | `admin` is unnecessarily barred from monitoring UI |
| Manual tab | Visible to `super_admin`, `viewer` | Status/upload allow `super_admin`, `admin` | Viewer sees a broken/forbidden tab; authorized `admin` cannot reach it through admin UI |
| Review APIs | Nurse UI maps nurse to `admin` | `admin`, `super_admin` | Naming obscures intended least privilege |
| Doctor reads | Nurse UI | Public | Sensitive operational data is more broadly accessible than UI implies |
| Session/transcript/event reads and writes | Patient/staff UIs | Public by UUID | No patient ownership, staff auth, or role separation |
| `/triage/rag` | No UI | Public | Potentially costly clinical-model endpoint has no access control/rate limit |

The frontend `ProtectedRoute` is only a navigation guard based on editable local-storage values; security must come from backend checks. Several relevant backend endpoints have none.

## Known bugs and inconsistencies

### High priority

- **Uploaded manual is disconnected from real patient screening.** Manual changes do not change chat/call decisions.
- **Role matrix is internally inconsistent** as detailed above.
- **Unauthenticated clinical/session access.** Session UUID knowledge is sufficient to read transcripts, inject messages/assessments/recommendations/events, alter session status/location, or initiate voice/chat processing.
- **No real emergency notification.** `MockNotificationService` only logs/stores in process; normal text finalization sets `alert_sent = false`. The service does not persist an `emergency_events` row in its normal finalization path, so the admin emergency-event detail can remain empty despite emergency severity.
- **In-memory state is not horizontally safe.** Admin tokens, ADK sessions, and live-call sessions are process-local and lost on restart; multiple workers will not share them.

### Data/model mismatches

- `/triage/rag` uses `department_code` for either a code or a UUID, depending on branch.
- RAG fallback uses `general_opd`; the active seeded department code is `opd_general`.
- Normal chat returns `department_id` (UUID), while agent/tool inputs use `department_code`; this is handled in `TriageService` but makes the separate RAG contract inconsistent.
- Normal non-streaming contact metadata reads `contact.get("phone")`, while the tool emits `phone_number`; streaming has separate conversion logic. This can lose the phone value in some paths.
- Session `has_alert` is read from `metadata.alert_sent`, but normal finalization does not set that key and returns `alert_sent = false`.
- Backend comments/docstrings still describe notification and emergency behavior that the current mock/no-op paths do not provide.

### Quality and operational findings

- Frontend production build currently fails TypeScript checks: unused `addAnother` state in `DoctorScheduleManager`, unused `useEffect` in `HospitalMapViewer`, and an incompatible `SymptomCount[]` prop type in `OutbreakSurveillance`.
- Backend compile check passes. Test run result was **71 passed, 4 failed, 1 error** in this workspace. One unit failure assumes the default DB password is `postgres` while the active `.env` supplies another value; four integration failures/errors require a running HTTP API and were blocked by the restricted/no-server test environment. These results do not establish end-to-end runtime health.
- `GET /admin/triage-manual/status` declares an unused `admin_user` parameter (authorization still executes).
- Manual upload performs blocking local file I/O in an async route and uses an untracked fire-and-forget task.
- Simple substring rules can produce false positives (for example negated symptoms) and do not normalize Thai/English clinical synonyms beyond seeded strings.
- Rule matching examines only the latest text turn in normal chat; accumulated context is primarily left to the in-memory LLM session.
- Severity vocabulary differs between five-level ESI and the four stored buckets, losing distinctions between levels 1/2 and 4/5 outside metadata/tool output.
- The system can create many per-turn assessment/review records; there is no explicit “final assessment” relation or supersession rule.
- There is no rate limiting, CSRF strategy, request-size limit for audio, or WebSocket authentication.

## Recommended next steps

1. **Unify the production triage path.** Make chat, stream, and live finalization call one versioned decision service that explicitly combines hard DB rules, retrieved active-manual passages, static fallback policy, and schedule context. Persist manual version/chunk citations and decision source with every assessment.
2. **Fail safely around manual state.** Require a successfully ingested active manual, ingest into a new version before atomically switching it active, retain rollback versions, and make retrieval failure explicit rather than silently advising model judgement.
3. **Define one department contract.** Use `department_code` for stable codes and `department_id` for UUIDs everywhere; resolve at a single boundary. Fix `general_opd` to `opd_general` and add contract tests for every branch.
4. **Create an explicit authorization matrix.** Prefer distinct roles such as `nurse`, `admin`, `super_admin`, and `viewer`; align login, `ProtectedRoute`, tabs, and `require_roles`. Hide/disable unauthorized tabs and add backend authorization tests.
5. **Protect patient data and mutation endpoints.** Issue a scoped patient session token, require it for that session's HTTP/WebSocket operations, restrict low-level clinical writes to trusted internal code, authenticate staff transcript/doctor reads, and add rate limits.
6. **Make state durable and multi-worker safe.** Replace process-local admin tokens with signed/durable sessions and shared revocation; persist/reconstruct conversational state; move ingest and surveillance extraction to a durable job queue.
7. **Complete emergency operations.** Implement a real notifier/acknowledgement channel, persist emergency events consistently, mark escalation/alert metadata transactionally, and show delivery status to staff.
8. **Normalize surveillance.** Store controlled symptom/disease codes separately from free text, use hospital-local time, validate the date window, distinguish suspected from confirmed cases, and add acknowledgement/export workflows.
9. **Repair the build and strengthen verification.** Fix the current TypeScript errors, separate unit from live integration tests, configure integration fixtures to start the API/database, and add end-to-end tests proving which manual version influenced chat and voice decisions.
10. **Introduce managed migrations and audit writes.** Track applied versions, document the missing 010 number, avoid destructive migrations where possible, and write immutable audit rows for login, review, schedule, manual, and role-sensitive operations.

## Verification performed during this audit

- Inspected all routes in `hospital-hotline-assistant-api/app/main.py`.
- Inspected `triage_service.py`, both triage-engine modules, `rule_engine.py`, and all files under `app/services/ai/`, including RAG ingest/query and live/text runners.
- Inspected frontend routing plus all pages, components, hooks, and API/type modules.
- Inspected migrations 001–009 and 011 and the Pydantic schemas.
- Searched the full repository for `/triage/rag`, department identifiers, role checks, schedule context, notification/event writes, and frontend API usage.
- Ran backend bytecode compilation successfully.
- Ran backend tests: 71 passed, 4 failed, 1 error, with the qualifications recorded above.
- Ran the frontend build; it failed on the four TypeScript diagnostics recorded above.

