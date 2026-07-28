# Features

What the AI-OPD Pre-screening & Triage System offers, by surface. Last updated 2026-07-24.
(How it's built is in `CLAUDE.md` and `docs/`; this is the *what*.)

## Patient kiosk (`/kiosk`) — voice-first pre-screening booth

- **Bilingual voice conversation** — Thai (default) and English, selected on the
  welcome screen. The whole flow is spoken (Google STT/TTS over a live
  WebSocket); every question also shows tappable quick-reply chips, so patients
  can answer by voice or touch. A typed-form fallback exists for
  no-microphone kiosks.
- **Visit check-in** — patient enters or QR-scans their hospital Visit Number
  (VN); the system pulls their registration from the hospital HIS (name, age,
  HN, prior vitals) and greets them by name.
- **Spoken identity confirmation** — "you are {name}, right?" before anything
  else, including on resumed sessions. A stranger answering "no" can never
  modify the real patient's session.
- **Session resume** — re-entering a VN within 12 h offers continue /
  start-over (spoken + buttons) for unfinished sessions, or reprint for
  completed ones.
- **First-visit history intake** — for first-time patients the AI asks five
  health-history questions one at a time in the same call (smoking/alcohol,
  allergies, chronic conditions, past surgeries, family history), each with
  suggested-answer chips. Answers are written back to the patient's HN record
  in the HIS and feed the triage as risk factors.
- **AI symptom interview** — the patient describes symptoms in their own
  words; the AI asks deterministic follow-up questions (verbatim red-flag and
  pain-scale wording from the MFU manual) within a bounded question budget.
- **Vitals on demand** — the engine requests measurements mid-interview only
  when the complaint requires them (e.g. BP for chest pain or age ≥ 60,
  temperature for fever), plus weight/height at wrap-up if the HIS values are
  stale. Supports a paired Bluetooth BP cuff (scan/pair/fetch/watch) and
  manual entry.
- **BP crisis rest-first protocol** — a first reading > 180/110 triggers a
  15-minute rest window (kiosk shows a rest screen; re-measurement gates the
  session) before a confirmatory reading may dispose to emergency.
- **Safety-redacted replies** — patients never see the triage level, color,
  diagnosis, or prescriptions; every reply is validated against leaks in both
  languages. Emergency dispositions tell the patient to go to the ER
  immediately; everything else routes OPD-first.
- **Department recommendation + wayfinding** — the result screen names the
  department with floor/room and a spoken navigation line, plus an embedded
  hospital map.
- **Printable slip** (`/slip/{sessionId}`) — QR-coded queue slip with the slip
  code the nurse desk uses to look the patient up; opens in a new tab for
  printing.
- **Chief-complaint summary** — a clean template-formatted complaint line
  ("Fever for 1 day prior to hospital visit") stored for staff, no LLM
  paraphrasing.

## Triage engine (backend)

- **Deterministic 5-level triage** — a pure rules engine (red flags,
  disposition, department mapping, question policy) decides the MOPH ER
  five-level acuity from versioned, hand-encoded bilingual criteria. The LLM
  only extracts findings from utterances and phrases questions/explanations —
  it never decides the level.
- **Criteria lifecycle** — screening criteria live in the database with
  upload → draft → review → approve → activate versioning; staff can upload a
  document and have the LLM extract a draft criteria version for review.
  Sessions pin the criteria version they ran under.
- **Objective-input gating** — measured vitals and HIS age merge into state
  *before* the red-flag gate, so a cuff reading of 200/120 disposes emergency
  on turn 1 regardless of what the patient says.
- **RAG-grounded explanations** — non-emergency explanations retrieve passages
  from the uploaded MFU triage-manual PDF (pgvector) for grounding;
  explanation-only — decisions never depend on RAG.
- **Full AI audit trail** — every LLM call and rules decision is recorded
  (`ai_inference_audit`) with a per-session trace API and aggregate AI-metrics
  API; nurse-visible disposition reasons cite the manual.
- **Text chat + SSE streaming** — the same engine serves plain REST chat and a
  streaming variant used by staff-side tools.

## Hospital HIS integration

- **Mock HIS service** (`hospital-his-mock/`) — standalone SQLite service
  seeding synthetic patients (HN) and visits (VN); admin portal shows the
  "hospital side" live.
- **Adapter seam** — mock / HTTP adapters selected by config; the real
  hospital HIS can be swapped in without touching the flow. Admin endpoints
  view and edit the HIS connection at runtime.
- **Two-stage write-back** — Stage 1: screening result attaches to the visit;
  Stage 2: nurse approval publishes the final department + reason. First-visit
  history answers write to the patient's HN record.

## Nurse portal (`/nurse`)

- **Review queue** — completed screenings with severity, complaint, vitals,
  and the AI's disposition reasons (with manual citations); searchable by the
  slip code on the patient's receipt.
- **Tabbed review modal** — booth vitals, editable chief complaint, nurse
  note, and department; one smart confirm that approves or reroutes and
  publishes to the HIS (Stage 2).
- **Escalations** — sessions the AI escalated to a human are flagged for
  priority handling.
- **Doctor & schedule management** — CRUD for doctors and date-based
  schedules; availability feeds the routing context.

## Admin portal (`/admin`)

- **Session monitor** — filterable session list (severity, language, status)
  with full conversation transcripts and emergency-event timeline.
- **AI trace & metrics** — per-session inference trace (every extraction,
  rules decision, validation) and aggregate model metrics.
- **Hospital DB panel** — live view of the mock HIS: watch a visit go
  registered → screened → routed during a demo.
- **Disease surveillance dashboard** — symptom-category aggregation over time
  for outbreak monitoring, extracted per session.
- **Criteria manager** — upload, diff, edit, approve, and activate screening
  criteria versions.
- **Triage-manual upload** — replace the RAG-grounding manual PDF;
  re-ingestion runs in the background.
- **BP device manager** — scan and pair the kiosk's Bluetooth BP cuff.
- **User management** — create/edit/delete staff accounts with roles
  (super_admin / admin / viewer); bearer-token login.
- **Kiosk stats** — daily counts for the kiosk home screen.

## Platform

- **i18n throughout** — Thai and English as first-class languages in the UI,
  the spoken flow, the criteria, and the leak validator.
- **Idempotent setup** — one command applies all migrations, seeds criteria
  v1, and health-checks the HIS mock (`scripts/init_db.py`); `reset_demo.py`
  restores a clean demo state.
- **Model-agnostic LLM seam** — Vertex AI Gemini today; an OpenAI-compatible
  adapter for future local models (e.g. edge deployment).
- **Self-contained test suite** — 385+ unit tests with fakes (no live
  Google/DB), including table-driven rules tests from the seed criteria and
  golden bilingual transcripts validator-checked end to end.
