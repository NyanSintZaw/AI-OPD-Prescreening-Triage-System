"""Assemble the two API docs from the generated fragments:
- docs/api-reference.md          internal, everything incl. mock HIS
- docs/api-reference-hospital.md hospital-IT-facing, our system only
"""
from pathlib import Path

S = Path(__file__).parent
DOCS = Path(__file__).resolve().parents[3] / "docs"

WS_SECTION = """

---

## WebSocket — `WS /ws/voice/{session_id}`

Live voice call — the kiosk booth's turn transport. Connect with
`ws://<host>/ws/voice/{session_id}?language=th|en`
(default `en`; invalid values fall back to `en`). Optional query param
`resume_prompt=active|completed` opens the call with the spoken continue-vs-start-over gate.

**Binary frames (client → server):** raw 16 kHz mono Int16 PCM mic audio.
**Binary frames (server → client):** 24 kHz mono Int16 PCM reply audio.

**JSON control frames, client → server** (`{"type": ...}`):

| type | Extra fields | Effect |
|---|---|---|
| `mute` | — | pause mic processing; server replies `{"type":"status","muted":true}` |
| `unmute` | — | resume; server replies `{"type":"status","muted":false}` |
| `end_of_turn` | `caption` (string, optional) | commit the user's turn; caption = client-side speech captions fallback |
| `submit_measurement` | `content` (string) | measurement popup result — injects a text turn so the engine continues without speech |
| `tap_reply` | `content` (string) | quick-reply chip tap — injected as a text turn tagged `input_mode="button"` |
| `end_call` | — | end the call |

**JSON control frames, server → client:**

| type | Payload |
|---|---|
| `transcript` | `role`, `text` — per-turn transcripts |
| `emergency` | emergency banner payload |
| `assessment_complete` | final-assessment payload |
| `measurement_request` | ask the client to open the measurement popup |
| `question_options` | quick-reply options for the current question |
| `identity` | patient identity (linked-visit greeting) |
| `resume_choice` | continue-vs-start-over resolution |
| `viseme_track` | viseme timing data for the avatar |
| `status` | `muted`: bool |
| `error` | `message` (e.g. `connect_failed`) |
| `call_ended` | sent before the server closes the socket |
"""

main_md = (S / "generated_main.md").read_text()
his_md = (S / "generated_his.md").read_text()
schemas_md = (S / "generated_schemas.md").read_text()
his_schemas_md = (S / "generated_his_schemas.md").read_text()

# ── internal doc ──────────────────────────────────────────────────────────────
internal_header = """# API Reference — AI OPD Prescreening & Triage System

**Generated from code** (FastAPI OpenAPI dump of `app/main.py` + `hospital-his-mock`),
updated 2026-08-04. Nothing here is hand-invented; every path, field, type, and JSON
example comes from the running route definitions. Interactive testing: run the backend
and open `http://localhost:8000/docs`, or import `http://localhost:8000/openapi.json`
into Postman.

> Hospital-IT-facing version (our system's API only, no mock HIS):
> [api-reference-hospital.md](api-reference-hospital.md)

Two services:

| Service | Base URL (dev) | What |
|---|---|---|
| Main API (`hospital-hotline-assistant-api`) | `http://localhost:8000` | everything below |
| Mock HIS (`hospital-his-mock`) | `http://localhost:8001` | fake hospital DB, §Mock HIS |

**Auth model:** patient-facing routes (`/sessions/*`, `/departments`, `/tts`, `/stt`,
`/doctors`*, `/kiosk/stats`, `/screening/*`, `/vitals/*`) need no auth. Staff routes marked
with **roles** below need `Authorization: Bearer <token>` from `POST /admin/login`
(tokens are in-memory — they vanish on backend restart). Response models are in the
[Schemas appendix](#schemas-appendix).

**JSON examples:** every `Example request` / `Example response` block is derived
mechanically from the schema — enums and defaults are real, other values are typed
placeholders (`"string"`, `0`, `false`).

---

## Main API endpoints

"""
internal = (
    internal_header + main_md + WS_SECTION
    + "\n\n---\n\n## Mock HIS service endpoints (`http://localhost:8001`)\n\n"
    + "Standalone fake hospital DB (SQLite, auto-seeds on startup). No auth (ignores any\n"
    + "`X-API-Key` / `Authorization` headers sent by the main API).\n\n"
    + his_md
    + "\n\n---\n\n## Schemas appendix\n\nRequest/response models referenced above (main API).\n\n"
    + schemas_md
    + "\n\n### Mock HIS schemas\n\n" + his_schemas_md + "\n"
)
(DOCS / "api-reference.md").write_text(internal)

# ── hospital-facing doc ───────────────────────────────────────────────────────
hospital_header = """# AI OPD Prescreening & Triage System — API Reference

Prepared for the MFU Medical Center hospital IT team · updated 2026-08-04

This document describes the complete HTTP + WebSocket API surface of the AI OPD
prescreening booth system (FastAPI backend). It is generated directly from the
application's OpenAPI definition, so paths, fields, and types match the running
system exactly. A live, interactive copy is always available at `/docs`
(Swagger UI) and `/openapi.json` on the deployed backend.

**Base URL:** `http://<backend-host>:8000` (deployment host to be agreed).

**Authentication:** patient-facing kiosk routes (`/sessions/*`, `/departments`,
`/tts`, `/stt`, `/doctors`*, `/kiosk/stats`, `/screening/*`, `/vitals/*`) are
unauthenticated — the kiosk runs unattended. Staff/administrative routes marked
with **roles** require `Authorization: Bearer <token>` obtained from
`POST /admin/login`.

**HIS integration:** this system consumes the hospital's iMed API as a *client*
(visit lookup, patient assignment) — that integration is specified separately in
`imed-patient-assignment-api.md` and is not part of this document. The endpoints
under `/admin/his/*` below are our admin console's view of that connection.

**JSON examples:** every `Example request` / `Example response` block is derived
from the schema — enum values and defaults are real, remaining values are typed
placeholders (`"string"`, `0`, `false`).

---

## REST endpoints

"""
hospital = (
    hospital_header + main_md + WS_SECTION
    + "\n\n---\n\n## Schemas appendix\n\nRequest/response models referenced above.\n\n"
    + schemas_md + "\n"
)
(DOCS / "api-reference-hospital.md").write_text(hospital)

print("internal:", len(internal.splitlines()), "lines | hospital:", len(hospital.splitlines()), "lines")
