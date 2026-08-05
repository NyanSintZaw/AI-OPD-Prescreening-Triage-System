# AI OPD Prescreening & Triage System — API Reference

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

### `GET /`

Root.

**Auth:** none

**Response 200:** JSON (Successful Response)

---

### `GET /health`

Health.

**Auth:** none

**Response 200:** JSON (Successful Response)

---

### `POST /admin/login`

Admin Login.

**Auth:** none

**Request body** (`application/json`, `AdminLoginRequest`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `email` | string | Y | Email |
| `password` | string | Y | Password |

Example request:

```json
{
  "email": "string",
  "password": "string"
}
```

**Response 200:** `AdminLoginResponse`

Example response:

```json
{
  "access_token": "string",
  "token_type": "bearer",
  "expires_at": "2026-08-04T09:00:00Z",
  "user": {
    "id": "00000000-0000-0000-0000-000000000000",
    "email": "string",
    "full_name": "string",
    "role": "super_admin"
  }
}
```

---

### `POST /admin/logout`

Admin Logout.

Revoke the bearer token server-side. Idempotent: unknown or already
expired tokens are a no-op (still 204) so the client can always call it.

**Auth:** none

**Response 204:** Successful Response

---

### `GET /admin/users`

Admin List Users.

**Auth:** bearer token (roles: super_admin)

**Response 200:** `array of AdminUserManageOut`

Example response:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000000",
    "email": "string",
    "full_name": "string",
    "role": "super_admin",
    "is_active": false,
    "last_login_at": "2026-08-04T09:00:00Z",
    "created_at": "2026-08-04T09:00:00Z"
  }
]
```

---

### `POST /admin/users`

Admin Create User.

**Auth:** bearer token (roles: super_admin)

**Request body** (`application/json`, `AdminUserCreate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `email` | string | Y | Email |
| `full_name` | string | Y | Full Name |
| `password` | string | Y | Password |
| `role` | string | N | Role (default: `"nurse"`) |

Example request:

```json
{
  "email": "string",
  "full_name": "string",
  "password": "string",
  "role": "nurse"
}
```

**Response 201:** `AdminUserManageOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "email": "string",
  "full_name": "string",
  "role": "super_admin",
  "is_active": false,
  "last_login_at": "2026-08-04T09:00:00Z",
  "created_at": "2026-08-04T09:00:00Z"
}
```

---

### `PATCH /admin/users/{user_id}`

Admin Update User.

**Auth:** bearer token (roles: super_admin)

**Path params:** `user_id`

**Request body** (`application/json`, `AdminUserUpdate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `full_name` | string or null | N | Full Name |
| `password` | string or null | N | Password |
| `is_active` | boolean or null | N | Is Active |

Example request:

```json
{
  "full_name": "string",
  "password": "string",
  "is_active": false
}
```

**Response 200:** `AdminUserManageOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "email": "string",
  "full_name": "string",
  "role": "super_admin",
  "is_active": false,
  "last_login_at": "2026-08-04T09:00:00Z",
  "created_at": "2026-08-04T09:00:00Z"
}
```

---

### `DELETE /admin/users/{user_id}`

Admin Delete User.

Hard delete a nurse account. Review history survives — reviewer FKs
are ON DELETE SET NULL, so signed reviews just show a blank reviewer.

**Auth:** bearer token (roles: super_admin)

**Path params:** `user_id`

**Response 204:** Successful Response

---

### `POST /sessions`

Create Session.

**Auth:** none

**Request body** (`application/json`, `SessionCreate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `language` | string — one of `th` \| `en` | N | Language (default: `"th"`) |
| `user_agent` | string or null | N | User Agent |
| `ip_hash` | string or null | N | Ip Hash |
| `metadata` | object | N | Metadata |

Example request:

```json
{
  "language": "th",
  "user_agent": "string",
  "ip_hash": "string",
  "metadata": {}
}
```

**Response 201:** `SessionOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "language": "th",
  "status": "active",
  "started_at": "2026-08-04T09:00:00Z",
  "ended_at": "2026-08-04T09:00:00Z",
  "user_agent": "string",
  "ip_hash": "string",
  "metadata": {}
}
```

---

### `POST /sessions/{session_id}/link-visit`

Link Visit.

Link a hospital visit to this session.

The patient types (or scans) the visit ID issued at the registration
booth; we validate it against the HIS and pull demographics (birthdate →
age) and any HIS-recorded vitals into session metadata so the screening
engine can pre-fill them. Unknown visit → ``linked=false`` and the
patient continues anonymously.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `LinkVisitRequest`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `visit_id` | string | Y | Visit Id |
| `preconfirmed` | boolean | N | Preconfirmed (default: `false`) |

Example request:

```json
{
  "visit_id": "string",
  "preconfirmed": false
}
```

**Response 200:** `LinkVisitResponse`

Example response:

```json
{
  "linked": false,
  "visit_id": "string",
  "patient_name": "string",
  "age_years": 0,
  "appointment": false,
  "has_his_vitals": false,
  "is_first_time": false,
  "hn": "string"
}
```

---

### `DELETE /sessions/{session_id}/link-visit`

Unlink Visit.

Clear the linked hospital visit so the patient can re-enter a VN.

Used when name confirmation fails ("Is this you?" → No). Does not delete
the session or screening state — drops ``metadata.visit`` plus any
HIS-derived prefill (history, HIS-sourced vitals) of the wrong patient.

**Auth:** none

**Path params:** `session_id`

**Response 200:** `SessionOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "language": "th",
  "status": "active",
  "started_at": "2026-08-04T09:00:00Z",
  "ended_at": "2026-08-04T09:00:00Z",
  "user_agent": "string",
  "ip_hash": "string",
  "metadata": {}
}
```

---

### `GET /sessions/by-visit/{visit_id}`

Get Session By Visit.

Return the most recent active session linked to this hospital visit (VN).

Used by the kiosk before creating a new session: if the patient hung up
or walked away mid-interview and re-enters the same VN, resume the prior
session (screening engine state is already in Postgres).

**Auth:** none

**Path params:** `visit_id`

**Response 200:** `SessionByVisitOut`

Example response:

```json
{
  "found": false,
  "visit_id": "string",
  "session": {
    "id": "00000000-0000-0000-0000-000000000000",
    "language": "th",
    "status": "active",
    "started_at": "2026-08-04T09:00:00Z",
    "ended_at": "2026-08-04T09:00:00Z",
    "user_agent": "string",
    "ip_hash": "string",
    "metadata": {}
  },
  "status": "string",
  "patient_name": "string",
  "name_confirmed": false,
  "needs_history_intake": false
}
```

---

### `POST /sessions/{session_id}/patient-history`

Save Patient History.

Persist first-time-patient history to session metadata and the HIS HN.

Gated for booth intake after name confirmation. Writes through
``HisAdapter.push_patient_history`` so returning visits see the data.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `PatientHistoryIntakeRequest`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `smoking_alcohol` | string or null | N | Smoking Alcohol |
| `allergies` | string or null | N | Allergies |
| `chronic_conditions` | string or null | N | Chronic Conditions |
| `past_surgeries` | string or null | N | Past Surgeries |
| `family_history` | string or null | N | Family History |

Example request:

```json
{
  "smoking_alcohol": "string",
  "allergies": "string",
  "chronic_conditions": "string",
  "past_surgeries": "string",
  "family_history": "string"
}
```

**Response 200:** `PatientHistoryIntakeResponse`

Example response:

```json
{
  "saved": false,
  "pushed_to_his": false,
  "is_first_time": false,
  "hn": "string"
}
```

---

### `POST /sessions/{session_id}/confirm-visit-name`

Confirm Visit Name.

Confirm or reject the HIS patient name after link-visit.

Buttons send ``confirmed=true/false``; typed/spoken replies send ``text``
and are classified by the shared yes/no NLU. A ``no`` decision unlinks the
visit so the kiosk can re-prompt for VN. An unclear reply returns 422 and
is re-asked at most MAX_IDENTITY_RETRIES times, then treated as rejected —
fail closed like the voice identity gate (never interview an unverified
identity).

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `ConfirmVisitNameRequest`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `confirmed` | boolean or null | N | Confirmed |
| `text` | string or null | N | Text |

Example request:

```json
{
  "confirmed": false,
  "text": "string"
}
```

**Response 200:** `ConfirmVisitNameResponse`

Example response:

```json
{
  "decision": "yes",
  "name_confirmed": false,
  "unlinked": false,
  "patient_name": "string"
}
```

---

### `GET /sessions/{session_id}`

Get Session.

**Auth:** none

**Path params:** `session_id`

**Response 200:** `SessionOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "language": "th",
  "status": "active",
  "started_at": "2026-08-04T09:00:00Z",
  "ended_at": "2026-08-04T09:00:00Z",
  "user_agent": "string",
  "ip_hash": "string",
  "metadata": {}
}
```

---

### `PATCH /sessions/{session_id}`

Update Session.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `SessionUpdate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `status` | string — one of `active` \| `completed` \| `reset` \| `escalated` | Y | Status |

Example request:

```json
{
  "status": "active"
}
```

**Response 200:** `SessionOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "language": "th",
  "status": "active",
  "started_at": "2026-08-04T09:00:00Z",
  "ended_at": "2026-08-04T09:00:00Z",
  "user_agent": "string",
  "ip_hash": "string",
  "metadata": {}
}
```

---

### `PUT /sessions/{session_id}/location`

Update Session Location.

Save the patient-reported area for a session.
Called by the chat UI after the user answers the location prompt.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `SessionLocationUpdate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `location_area` | string | Y | Location Area |

Example request:

```json
{
  "location_area": "string"
}
```

**Response 200:** JSON (Successful Response)

---

### `PUT /sessions/{session_id}/vitals`

Update Session Vitals.

Store a blood-pressure reading on the session so the triage agent
(text chat and live voice) can factor it into the assessment.
Called by the vitals gate UI after a cuff fetch or manual entry.

Plausibility is enforced by ``SessionVitalsUpdate`` (bounds from the
criteria defaults, plus systolic > diastolic), so an impossible reading is
rejected with a 422 BEFORE the hypertensive-crisis check below can see it.
That ordering is load-bearing: 300/220 must not open a 15-minute rest
window. See docs/vital-bounds.md.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `SessionVitalsUpdate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `systolic` | integer | Y | Systolic |
| `diastolic` | integer | Y | Diastolic |
| `pulse_bpm` | integer or null | N | Pulse Bpm |
| `weight_kg` | number or null | N | Weight Kg |
| `height_cm` | number or null | N | Height Cm |
| `temperature_c` | number or null | N | Temperature C |
| `measured_at` | string (date-time) or null | N | Measured At |
| `source` | string — one of `device` \| `manual` | N | Source (default: `"device"`) |
| `reading_id` | string (uuid) or null | N | Reading Id |

Example request:

```json
{
  "systolic": 0,
  "diastolic": 0,
  "pulse_bpm": 0,
  "weight_kg": 0.0,
  "height_cm": 0.0,
  "temperature_c": 0.0,
  "measured_at": "2026-08-04T09:00:00Z",
  "source": "device",
  "reading_id": "00000000-0000-0000-0000-000000000000"
}
```

**Response 200:** JSON (Successful Response)

---

### `POST /sessions/{session_id}/measurement`

Update Session Measurement.

Record a single vital the screening engine asked for mid-interview
(temperature-on-demand). Merges into the session's stored vitals so the
next turn's ``turn_context`` carries it — without requiring the booth to
re-send the blood-pressure reading.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `SessionMeasurementUpdate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `vital` | string — one of `temp` \| `weight` \| `height` | Y | Vital |
| `value` | number | Y | Value |

Example request:

```json
{
  "vital": "temp",
  "value": 0.0
}
```

**Response 200:** JSON (Successful Response)

---

### `GET /screening/vital-bounds`

Get Vital Bounds.

Physiologically possible ranges from the active criteria version.

The kiosk reads these so the patient gets instant, correctly-worded
feedback instead of a bare 422 — and so the numbers live in exactly one
place (the criteria document) rather than being retyped in the client.

**Auth:** none

**Response 200:** JSON (Successful Response)

---

### `GET /vitals/blood-pressure/rest-status`

Get Bp Rest Status.

Whether this patient must wait before another BP measurement.

**Auth:** none

**Query params:**

| Param | Type | Required | Notes |
|---|---|---|---|
| `session_id` | string (uuid) or null | N |  |
| `hn` | string or null | N |  |
| `visit_id` | string or null | N |  |

**Response 200:** `BpRestStatusOut`

Example response:

```json
{
  "resting": false,
  "rest_until": "2026-08-04T09:00:00Z",
  "seconds_remaining": 0,
  "reason": "string",
  "hn": "string",
  "visit_id": "string"
}
```

---

### `POST /vitals/blood-pressure/fetch`

Fetch Blood Pressure.

Pull the latest reading from the Omron cuff over Bluetooth.

Runs omblepy on the API host. Always returns 200 with a ``status``
field so the kiosk UI can branch on failure modes (device not
advertising, busy, ...) without an error-handling side channel.

A fresh reading is persisted to ``bp_readings`` immediately — before
the patient decides to continue — so the measurement survives even if
they cancel the voice flow right after measuring.

**Auth:** none

**Request body** (`application/json`): see schema in /docs

Example request:

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000"
}
```

**Response 200:** `BloodPressureFetchResponse`

Example response:

```json
{
  "status": "ok",
  "systolic": 0,
  "diastolic": 0,
  "pulse_bpm": 0,
  "measured_at": "2026-08-04T09:00:00Z",
  "is_recent": false,
  "irregular_heartbeat": false,
  "body_movement": false,
  "message": "string",
  "reading_id": "00000000-0000-0000-0000-000000000000",
  "rest_until": "2026-08-04T09:00:00Z",
  "seconds_remaining": 0
}
```

---

### `POST /vitals/blood-pressure/watch`

Watch Blood Pressure.

Long-poll: wait for the cuff's finished-measurement broadcast, then
fetch and return the reading immediately.

The cuff is silent while measuring and starts advertising the moment
it finishes — that advertisement is the real "patient is done" signal,
so the fetch begins ~1s after the measurement ends. Returns status
``not_seen`` when nothing appeared within ``timeout_seconds`` so the
kiosk can re-arm without any dead time.

**Auth:** none

**Request body** (`application/json`): see schema in /docs

Example request:

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "timeout_seconds": 25
}
```

**Response 200:** `BloodPressureFetchResponse`

Example response:

```json
{
  "status": "ok",
  "systolic": 0,
  "diastolic": 0,
  "pulse_bpm": 0,
  "measured_at": "2026-08-04T09:00:00Z",
  "is_recent": false,
  "irregular_heartbeat": false,
  "body_movement": false,
  "message": "string",
  "reading_id": "00000000-0000-0000-0000-000000000000",
  "rest_until": "2026-08-04T09:00:00Z",
  "seconds_remaining": 0
}
```

---

### `GET /admin/bp-device`

Get Bp Device Status.

Current cuff configuration for the admin portal device manager.

**Auth:** bearer token (roles: super_admin, nurse, viewer)

**Response 200:** `BpDeviceStatusOut`

Example response:

```json
{
  "device_name": "string",
  "device_mac": "string",
  "configured": false,
  "busy": false,
  "supported_models": [
    "string"
  ]
}
```

---

### `POST /admin/bp-device/scan`

Scan Bp Devices.

Sweep for nearby BLE devices (~6s) so the admin can pick the cuff.

Mirrors omblepy's interactive selection table: likely Omron monitors
are flagged and sorted first.

**Auth:** bearer token (roles: super_admin, nurse)

**Response 200:** `BpScanResponse`

Example response:

```json
{
  "status": "ok",
  "devices": [
    {
      "mac": "string",
      "name": "string",
      "rssi": 0,
      "is_omron": false
    }
  ],
  "message": "string"
}
```

---

### `POST /admin/bp-device/pair`

Pair Bp Device.

Program the pairing key into the selected cuff and make it the
active kiosk device (persists to .env, effective immediately).

**Auth:** bearer token (roles: super_admin, nurse)

**Request body** (`application/json`, `BpPairRequest`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `mac` | string | Y | Mac |
| `device_name` | string | Y | Device Name |

Example request:

```json
{
  "mac": "string",
  "device_name": "string"
}
```

**Response 200:** `BpPairResponse`

Example response:

```json
{
  "status": "ok",
  "device_name": "string",
  "device_mac": "string",
  "message": "string"
}
```

---

### `POST /sessions/{session_id}/messages`

Create Message.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `MessageCreate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `role` | string — one of `user` \| `assistant` \| `system` | Y | Role |
| `input_mode` | string — one of `voice` \| `text` \| `button` or null | N | Input Mode |
| `content` | string | Y | Content |
| `audio_url` | string or null | N | Audio Url |
| `transcript_confidence` | number or null | N | Transcript Confidence |
| `model_name` | string or null | N | Model Name |
| `response_latency_ms` | integer or null | N | Response Latency Ms |
| `metadata` | object | N | Metadata |

Example request:

```json
{
  "role": "user",
  "input_mode": "voice",
  "content": "string",
  "audio_url": "string",
  "transcript_confidence": 0.0,
  "model_name": "string",
  "response_latency_ms": 0,
  "metadata": {}
}
```

**Response 201:** `MessageOut`

Example response:

```json
{
  "role": "user",
  "input_mode": "voice",
  "content": "string",
  "audio_url": "string",
  "transcript_confidence": 0.0,
  "model_name": "string",
  "response_latency_ms": 0,
  "metadata": {},
  "id": "00000000-0000-0000-0000-000000000000",
  "session_id": "00000000-0000-0000-0000-000000000000",
  "created_at": "2026-08-04T09:00:00Z"
}
```

---

### `GET /sessions/{session_id}/messages`

List Messages.

**Auth:** none

**Path params:** `session_id`

**Response 200:** `array of MessageOut`

Example response:

```json
[
  {
    "role": "user",
    "input_mode": "voice",
    "content": "string",
    "audio_url": "string",
    "transcript_confidence": 0.0,
    "model_name": "string",
    "response_latency_ms": 0,
    "metadata": {},
    "id": "00000000-0000-0000-0000-000000000000",
    "session_id": "00000000-0000-0000-0000-000000000000",
    "created_at": "2026-08-04T09:00:00Z"
  }
]
```

---

### `POST /sessions/{session_id}/symptoms`

Create Symptom Entry.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `SymptomEntryCreate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `message_id` | string (uuid) or null | N | Message Id |
| `raw_text` | string | Y | Raw Text |
| `normalized_symptoms` | array of any | N | Normalized Symptoms |
| `body_location` | string or null | N | Body Location |
| `duration_text` | string or null | N | Duration Text |
| `pain_score` | integer or null | N | Pain Score |
| `pain_location` | string or null | N | Pain Location |
| `distress_score` | integer or null | N | Distress Score |
| `distress_type` | string or null | N | Distress Type |
| `red_flags` | array of string | N | Red Flags |

Example request:

```json
{
  "message_id": "00000000-0000-0000-0000-000000000000",
  "raw_text": "string",
  "normalized_symptoms": [],
  "body_location": "string",
  "duration_text": "string",
  "pain_score": 0,
  "pain_location": "string",
  "distress_score": 0,
  "distress_type": "string",
  "red_flags": [
    "string"
  ]
}
```

**Response 201:** JSON (Successful Response)

---

### `POST /sessions/{session_id}/severity-assessments`

Create Severity Assessment.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `SeverityAssessmentCreate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `source_message_id` | string (uuid) or null | N | Source Message Id |
| `severity` | string — one of `emergency` \| `urgent` \| `general` \| `unknown` | N | Severity (default: `"unknown"`) |
| `confidence` | number or null | N | Confidence |
| `explanation` | string or null | N | Explanation |
| `detected_triggers` | array of any | N | Detected Triggers |

Example request:

```json
{
  "source_message_id": "00000000-0000-0000-0000-000000000000",
  "severity": "unknown",
  "confidence": 0.0,
  "explanation": "string",
  "detected_triggers": []
}
```

**Response 201:** JSON (Successful Response)

---

### `POST /sessions/{session_id}/follow-up-questions`

Create Follow Up Question.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `FollowUpQuestionCreate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `question_text` | string | Y | Question Text |
| `reason` | string or null | N | Reason |

Example request:

```json
{
  "question_text": "string",
  "reason": "string"
}
```

**Response 201:** `FollowUpQuestionOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "session_id": "00000000-0000-0000-0000-000000000000",
  "question_text": "string",
  "reason": "string",
  "asked_at": "2026-08-04T09:00:00Z",
  "answer_message_id": "00000000-0000-0000-0000-000000000000",
  "answered_at": "2026-08-04T09:00:00Z"
}
```

---

### `GET /sessions/{session_id}/follow-up-questions`

List Follow Up Questions.

**Auth:** none

**Path params:** `session_id`

**Response 200:** `array of FollowUpQuestionOut`

Example response:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000000",
    "session_id": "00000000-0000-0000-0000-000000000000",
    "question_text": "string",
    "reason": "string",
    "asked_at": "2026-08-04T09:00:00Z",
    "answer_message_id": "00000000-0000-0000-0000-000000000000",
    "answered_at": "2026-08-04T09:00:00Z"
  }
]
```

---

### `PATCH /sessions/{session_id}/follow-up-questions/{question_id}/answer`

Answer Follow Up Question.

**Auth:** none

**Path params:** `session_id`, `question_id`

**Request body** (`application/json`, `FollowUpQuestionAnswerUpdate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `answer_message_id` | string (uuid) | Y | Answer Message Id |

Example request:

```json
{
  "answer_message_id": "00000000-0000-0000-0000-000000000000"
}
```

**Response 200:** `FollowUpQuestionOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "session_id": "00000000-0000-0000-0000-000000000000",
  "question_text": "string",
  "reason": "string",
  "asked_at": "2026-08-04T09:00:00Z",
  "answer_message_id": "00000000-0000-0000-0000-000000000000",
  "answered_at": "2026-08-04T09:00:00Z"
}
```

---

### `POST /sessions/{session_id}/department-recommendations`

Create Department Recommendation.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `DepartmentRecommendationCreate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `assessment_id` | string (uuid) or null | N | Assessment Id |
| `department_id` | string (uuid) | Y | Department Id |
| `confidence` | number or null | N | Confidence |
| `reason` | string or null | N | Reason |

Example request:

```json
{
  "assessment_id": "00000000-0000-0000-0000-000000000000",
  "department_id": "00000000-0000-0000-0000-000000000000",
  "confidence": 0.0,
  "reason": "string"
}
```

**Response 201:** JSON (Successful Response)

---

### `POST /sessions/{session_id}/emergency-events`

Create Emergency Event.

**Auth:** none

**Path params:** `session_id`

**Request body** (`application/json`, `EmergencyEventCreate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `trigger_id` | string (uuid) or null | N | Trigger Id |
| `source_message_id` | string (uuid) or null | N | Source Message Id |
| `detected_symptoms` | array of any | N | Detected Symptoms |
| `alert_message` | string | Y | Alert Message |

Example request:

```json
{
  "trigger_id": "00000000-0000-0000-0000-000000000000",
  "source_message_id": "00000000-0000-0000-0000-000000000000",
  "detected_symptoms": [],
  "alert_message": "string"
}
```

**Response 201:** JSON (Successful Response)

---

### `GET /sessions/{session_id}/emergency-events`

List Emergency Events.

**Auth:** none

**Path params:** `session_id`

**Response 200:** `array of EmergencyEventOut`

Example response:

```json
[
  {
    "trigger_id": "00000000-0000-0000-0000-000000000000",
    "source_message_id": "00000000-0000-0000-0000-000000000000",
    "detected_symptoms": [],
    "alert_message": "string",
    "id": "00000000-0000-0000-0000-000000000000",
    "session_id": "00000000-0000-0000-0000-000000000000",
    "created_at": "2026-08-04T09:00:00Z"
  }
]
```

---

### `GET /departments`

List Departments.

**Auth:** none

**Response 200:** `array of DepartmentOut`

Example response:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000000",
    "code": "string",
    "kind": "emergency",
    "name_en": "string",
    "name_th": "string",
    "description_en": "string",
    "description_th": "string",
    "is_active": false,
    "floor": "string",
    "room": "string",
    "nav_hint_en": "string",
    "nav_hint_th": "string",
    "nav_line_en": "string",
    "nav_line_th": "string"
  }
]
```

---

### `GET /routing-rules`

List Routing Rules.

**Auth:** none

**Response 200:** `array of RoutingRuleOut`

Example response:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000000",
    "department_id": "00000000-0000-0000-0000-000000000000",
    "rule_name": "string",
    "description": "string",
    "symptom_keywords": [
      "string"
    ],
    "condition_json": {},
    "severity_override": "emergency",
    "priority": 0,
    "is_active": false
  }
]
```

---

### `GET /emergency-triggers`

List Emergency Triggers.

**Auth:** none

**Response 200:** `array of EmergencyTriggerOut`

Example response:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000000",
    "trigger_name": "string",
    "description": "string",
    "trigger_keywords": [
      "string"
    ],
    "condition_json": {},
    "alert_message_en": "string",
    "alert_message_th": "string",
    "priority": 0,
    "is_active": false
  }
]
```

---

### `GET /kiosk/stats`

Kiosk Stats.

Public counters for the kiosk home / attract screen (no auth).

Three "today" numbers the booth shows patients:
  - ``visitors_today``  : hospital visits registered in the HIS today
                          (falls back to the full visit list when the mock
                          seed carries no ``modify_time``).
  - ``navigated_today`` : nurse-approved/corrected assessments today.
  - ``sessions_today``  : triage sessions started at the booth today.
Every source degrades to 0 rather than erroring so the screen never breaks.

**Auth:** none

**Response 200:** JSON (Successful Response)

---

### `GET /doctors`

List Doctors.

List all doctors, optionally filtering by active status.

**Auth:** none

**Query params:**

| Param | Type | Required | Notes |
|---|---|---|---|
| `active_only` | boolean | N | default: `true` |

**Response 200:** `array of DoctorOut`

Example response:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000000",
    "full_name": "string",
    "title": "string",
    "specialization": "string",
    "department_id": "00000000-0000-0000-0000-000000000000",
    "department_name_en": "string",
    "department_name_th": "string",
    "phone_ext": "string",
    "notes": "string",
    "is_active": false,
    "created_at": "2026-08-04T09:00:00Z",
    "updated_at": "2026-08-04T09:00:00Z"
  }
]
```

---

### `POST /doctors`

Create Doctor.

Create a new doctor profile. Requires admin or nurse role.

**Auth:** bearer token (roles: super_admin, nurse)

**Request body** (`application/json`, `DoctorCreate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `full_name` | string | Y | Full Name |
| `title` | string | N | Title (default: `"Dr."`) |
| `specialization` | string or null | N | Specialization |
| `department_id` | string (uuid) or null | N | Department Id |
| `phone_ext` | string or null | N | Phone Ext |
| `notes` | string or null | N | Notes |
| `is_active` | boolean | N | Is Active (default: `true`) |

Example request:

```json
{
  "full_name": "string",
  "title": "Dr.",
  "specialization": "string",
  "department_id": "00000000-0000-0000-0000-000000000000",
  "phone_ext": "string",
  "notes": "string",
  "is_active": true
}
```

**Response 201:** `DoctorOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "full_name": "string",
  "title": "string",
  "specialization": "string",
  "department_id": "00000000-0000-0000-0000-000000000000",
  "department_name_en": "string",
  "department_name_th": "string",
  "phone_ext": "string",
  "notes": "string",
  "is_active": false,
  "created_at": "2026-08-04T09:00:00Z",
  "updated_at": "2026-08-04T09:00:00Z"
}
```

---

### `GET /doctors/{doctor_id}`

Get Doctor.

Get a doctor with their full weekly schedule.

**Auth:** none

**Path params:** `doctor_id`

**Response 200:** `DoctorWithSchedulesOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "full_name": "string",
  "title": "string",
  "specialization": "string",
  "department_id": "00000000-0000-0000-0000-000000000000",
  "department_name_en": "string",
  "department_name_th": "string",
  "phone_ext": "string",
  "notes": "string",
  "is_active": false,
  "created_at": "2026-08-04T09:00:00Z",
  "updated_at": "2026-08-04T09:00:00Z",
  "schedules": [
    {
      "schedule_date": "string",
      "start_time": "string",
      "end_time": "string",
      "break_start": "string",
      "break_end": "string",
      "room": "string",
      "slot_label": "string",
      "is_available": true,
      "notes": "string",
      "id": "00000000-0000-0000-0000-000000000000",
      "doctor_id": "00000000-0000-0000-0000-000000000000",
      "created_at": "2026-08-04T09:00:00Z",
      "updated_at": "2026-08-04T09:00:00Z"
    }
  ]
}
```

---

### `PATCH /doctors/{doctor_id}`

Update Doctor.

Update a doctor profile. Requires admin or nurse role.

**Auth:** bearer token (roles: super_admin, nurse)

**Path params:** `doctor_id`

**Request body** (`application/json`, `DoctorUpdate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `full_name` | string or null | N | Full Name |
| `title` | string or null | N | Title |
| `specialization` | string or null | N | Specialization |
| `department_id` | string (uuid) or null | N | Department Id |
| `phone_ext` | string or null | N | Phone Ext |
| `notes` | string or null | N | Notes |
| `is_active` | boolean or null | N | Is Active |

Example request:

```json
{
  "full_name": "string",
  "title": "string",
  "specialization": "string",
  "department_id": "00000000-0000-0000-0000-000000000000",
  "phone_ext": "string",
  "notes": "string",
  "is_active": false
}
```

**Response 200:** `DoctorOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "full_name": "string",
  "title": "string",
  "specialization": "string",
  "department_id": "00000000-0000-0000-0000-000000000000",
  "department_name_en": "string",
  "department_name_th": "string",
  "phone_ext": "string",
  "notes": "string",
  "is_active": false,
  "created_at": "2026-08-04T09:00:00Z",
  "updated_at": "2026-08-04T09:00:00Z"
}
```

---

### `GET /doctors/{doctor_id}/schedules`

List Doctor Schedules.

List schedule entries for a doctor, optionally from a start date.

**Auth:** none

**Path params:** `doctor_id`

**Query params:**

| Param | Type | Required | Notes |
|---|---|---|---|
| `from_date` | string or null | N |  |

**Response 200:** `array of DoctorScheduleOut`

Example response:

```json
[
  {
    "schedule_date": "string",
    "start_time": "string",
    "end_time": "string",
    "break_start": "string",
    "break_end": "string",
    "room": "string",
    "slot_label": "string",
    "is_available": true,
    "notes": "string",
    "id": "00000000-0000-0000-0000-000000000000",
    "doctor_id": "00000000-0000-0000-0000-000000000000",
    "created_at": "2026-08-04T09:00:00Z",
    "updated_at": "2026-08-04T09:00:00Z"
  }
]
```

---

### `POST /doctors/{doctor_id}/schedules`

Add Doctor Schedule.

Add a date-specific schedule entry for a doctor.

**Auth:** bearer token (roles: super_admin, nurse)

**Path params:** `doctor_id`

**Request body** (`application/json`, `DoctorScheduleCreate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `schedule_date` | string (date) | Y | Schedule Date |
| `start_time` | string (time) | Y | Start Time |
| `end_time` | string (time) | Y | End Time |
| `break_start` | string (time) or null | N | Break Start |
| `break_end` | string (time) or null | N | Break End |
| `room` | string or null | N | Room |
| `slot_label` | string or null | N | Slot Label |
| `is_available` | boolean | N | Is Available (default: `true`) |
| `notes` | string or null | N | Notes |

Example request:

```json
{
  "schedule_date": "string",
  "start_time": "string",
  "end_time": "string",
  "break_start": "string",
  "break_end": "string",
  "room": "string",
  "slot_label": "string",
  "is_available": true,
  "notes": "string"
}
```

**Response 201:** `DoctorScheduleOut`

Example response:

```json
{
  "schedule_date": "string",
  "start_time": "string",
  "end_time": "string",
  "break_start": "string",
  "break_end": "string",
  "room": "string",
  "slot_label": "string",
  "is_available": true,
  "notes": "string",
  "id": "00000000-0000-0000-0000-000000000000",
  "doctor_id": "00000000-0000-0000-0000-000000000000",
  "created_at": "2026-08-04T09:00:00Z",
  "updated_at": "2026-08-04T09:00:00Z"
}
```

---

### `PATCH /doctors/{doctor_id}/schedules/{schedule_id}`

Update Doctor Schedule.

Update an existing schedule entry.

**Auth:** bearer token (roles: super_admin, nurse)

**Path params:** `doctor_id`, `schedule_id`

**Request body** (`application/json`, `DoctorScheduleCreate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `schedule_date` | string (date) | Y | Schedule Date |
| `start_time` | string (time) | Y | Start Time |
| `end_time` | string (time) | Y | End Time |
| `break_start` | string (time) or null | N | Break Start |
| `break_end` | string (time) or null | N | Break End |
| `room` | string or null | N | Room |
| `slot_label` | string or null | N | Slot Label |
| `is_available` | boolean | N | Is Available (default: `true`) |
| `notes` | string or null | N | Notes |

Example request:

```json
{
  "schedule_date": "string",
  "start_time": "string",
  "end_time": "string",
  "break_start": "string",
  "break_end": "string",
  "room": "string",
  "slot_label": "string",
  "is_available": true,
  "notes": "string"
}
```

**Response 200:** `DoctorScheduleOut`

Example response:

```json
{
  "schedule_date": "string",
  "start_time": "string",
  "end_time": "string",
  "break_start": "string",
  "break_end": "string",
  "room": "string",
  "slot_label": "string",
  "is_available": true,
  "notes": "string",
  "id": "00000000-0000-0000-0000-000000000000",
  "doctor_id": "00000000-0000-0000-0000-000000000000",
  "created_at": "2026-08-04T09:00:00Z",
  "updated_at": "2026-08-04T09:00:00Z"
}
```

---

### `DELETE /doctors/{doctor_id}/schedules/{schedule_id}`

Delete Doctor Schedule.

Delete a schedule entry.

**Auth:** bearer token (roles: super_admin, nurse)

**Path params:** `doctor_id`, `schedule_id`

**Response 204:** Successful Response

---

### `GET /schedules/available`

Get Available Doctors.

Return doctors with their available schedule entries for a given date
(defaults to today). Old entries are never deleted — only today's are surfaced.
Used by the AI to answer patient availability queries.

**Auth:** none

**Query params:**

| Param | Type | Required | Notes |
|---|---|---|---|
| `schedule_date` | string or null | N |  |
| `department_id` | string (uuid) or null | N |  |

**Response 200:** `array of DoctorWithSchedulesOut`

Example response:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000000",
    "full_name": "string",
    "title": "string",
    "specialization": "string",
    "department_id": "00000000-0000-0000-0000-000000000000",
    "department_name_en": "string",
    "department_name_th": "string",
    "phone_ext": "string",
    "notes": "string",
    "is_active": false,
    "created_at": "2026-08-04T09:00:00Z",
    "updated_at": "2026-08-04T09:00:00Z",
    "schedules": [
      {
        "schedule_date": "string",
        "start_time": "string",
        "end_time": "string",
        "break_start": "string",
        "break_end": "string",
        "room": "string",
        "slot_label": "string",
        "is_available": true,
        "notes": "string",
        "id": "00000000-0000-0000-0000-000000000000",
        "doctor_id": "00000000-0000-0000-0000-000000000000",
        "created_at": "2026-08-04T09:00:00Z",
        "updated_at": "2026-08-04T09:00:00Z"
      }
    ]
  }
]
```

---

### `POST /tts`

Text To Speech.

Synthesize speech for the given text. Returns audio/mpeg (MP3) bytes.

**Auth:** none

**Request body** (`application/json`, `TtsRequest`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `text` | string | Y | Text |
| `language` | string — one of `th` \| `en` | N | Language (default: `"en"`) |

Example request:

```json
{
  "text": "string",
  "language": "en"
}
```

**Response 200:** JSON (Successful Response)

---

### `POST /stt`

Speech To Text.

Transcribe a short audio clip. Returns the recognized text.

**Auth:** none

**Request body** (`multipart/form-data`, `Body_speech_to_text_stt_post`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `audio` | string | Y | Short audio clip from MediaRecorder |
| `language` | string | N | Language (default: `"en"`) |

**Response 200:** `SttResponse`

Example response:

```json
{
  "transcript": "string",
  "confidence": 0.0,
  "language_code": "string"
}
```

---

### `GET /conversation-summary`

Conversation Summary.

**Auth:** bearer token (roles: super_admin, viewer, nurse)

**Response 200:** `array of ConversationSummaryOut`

Example response:

```json
[
  {
    "session_id": "00000000-0000-0000-0000-000000000000",
    "language": "th",
    "status": "active",
    "started_at": "2026-08-04T09:00:00Z",
    "ended_at": "2026-08-04T09:00:00Z",
    "severity": "emergency",
    "department_name_en": "string",
    "department_name_th": "string",
    "message_count": 0,
    "has_alert": false,
    "escalation_reason": "string"
  }
]
```

---

### `GET /admin/surveillance`

Get Surveillance Summary.

Aggregate disease-surveillance data for the admin outbreak dashboard.

**Auth:** bearer token (roles: super_admin, nurse, viewer)

**Query params:**

| Param | Type | Required | Notes |
|---|---|---|---|
| `days` | integer | N | default: `7` |

**Response 200:** `SurveillanceSummaryOut`

Example response:

```json
{
  "days": 0,
  "total_reports": 0,
  "top_symptoms": [
    {
      "keyword": "string",
      "count": 0
    }
  ],
  "by_area": [
    {
      "area": "string",
      "keyword": "string",
      "count": 0
    }
  ],
  "daily_trend": [
    {
      "date": "string",
      "count": 0
    }
  ],
  "severity_distribution": [
    {
      "severity_level": "string",
      "count": 0
    }
  ],
  "outbreak_alerts": [
    {
      "keyword": "string",
      "area": "string",
      "recent_count": 0,
      "previous_count": 0,
      "increase_pct": 0.0
    }
  ]
}
```

---

### `POST /admin/triage-manual/upload`

Upload Triage Manual.

Upload a new triage manual PDF and trigger background RAG ingestion.

Replaces any previously uploaded manual.  The old pgvector embeddings are
deleted automatically before the new ones are stored.

Returns a JSON object with the upload ``id`` and initial ``status``.

**Auth:** bearer token (roles: super_admin, nurse)

**Request body** (`multipart/form-data`, `Body_upload_triage_manual_admin_triage_manual_upload_post`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | string | Y | Hospital triage manual PDF |

**Response 200:** JSON (Successful Response)

---

### `GET /admin/triage-manual/status`

Get Triage Manual Status.

Return the latest triage manual upload record.

The frontend polls this endpoint after uploading to track ingest progress.
Returns ``null`` when no manual has been uploaded yet.

**Auth:** bearer token (roles: super_admin, nurse)

**Response 200:** JSON (Successful Response)

---

### `GET /admin/ai-metrics`

Get Ai Metrics.

Aggregate AI transparency metrics over ai_inference_audit (SRS F40).

Feeds the head-nurse governance panel: call volumes/ok-rates/latency per
LLM call site, dispositions by level and department, validator violation
counts, and escalation totals.

**Auth:** bearer token (roles: super_admin, nurse, viewer)

**Query params:**

| Param | Type | Required | Notes |
|---|---|---|---|
| `from` | string or null | N |  |
| `to` | string or null | N |  |

**Response 200:** JSON (Successful Response)

---

### `GET /admin/sessions/{session_id}/trace`

Get Session Trace.

Full AI decision trace for one session (SRS Explainability / F40).

Returns the screening engine state (findings, slots, disposition with
fired rules + manual citations) and the per-call ai_inference_audit
timeline. Only available for sessions run by the screening engine v2.

**Auth:** bearer token (roles: nurse, super_admin, viewer)

**Path params:** `session_id`

**Response 200:** JSON (Successful Response)

---

### `GET /admin/reviews`

List Assessment Reviews.

**Auth:** bearer token (roles: nurse, super_admin, viewer)

**Query params:**

| Param | Type | Required | Notes |
|---|---|---|---|
| `status` | string | N | default: `"pending"` |

**Response 200:** `array of AssessmentReviewOut`

Example response:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000000",
    "session_id": "00000000-0000-0000-0000-000000000000",
    "assessment_id": "00000000-0000-0000-0000-000000000000",
    "status": "pending",
    "reviewer_id": "00000000-0000-0000-0000-000000000000",
    "reviewer_name": "string",
    "proposed_department_id": "00000000-0000-0000-0000-000000000000",
    "proposed_department_name_en": "string",
    "proposed_department_name_th": "string",
    "confirmed_department_id": "00000000-0000-0000-0000-000000000000",
    "confirmed_department_name_en": "string",
    "confirmed_department_name_th": "string",
    "ai_assessment_score": 0,
    "ai_assessment_scale": 10,
    "patient_contact_requested": false,
    "patient_contact_phone": "string",
    "patient_contact_preferred_time": "string",
    "patient_contact_relation": "string",
    "disposition_reasons": [
      {}
    ],
    "notes": "string",
    "visit_id": "string",
    "patient_name": "string",
    "vitals": {},
    "missing_vitals": [
      "string"
    ],
    "rejected_vitals": {},
    "ai_chief_complaint": "string",
    "ai_illness_note": "string",
    "patient_follow_up": "string",
    "chief_complaint": "string",
    "illness_note": "string",
    "his_routing_status": "string",
    "reviewed_at": "2026-08-04T09:00:00Z",
    "created_at": "2026-08-04T09:00:00Z",
    "updated_at": "2026-08-04T09:00:00Z"
  }
]
```

---

### `POST /admin/reviews/{assessment_id}/approve`

Approve Assessment Review.

**Auth:** bearer token (roles: nurse, super_admin)

**Path params:** `assessment_id`

**Request body** (`application/json`, `AssessmentReviewApproveRequest`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `notes` | string or null | N | Notes |
| `ai_assessment_score` | integer or null | N | Ai Assessment Score |
| `chief_complaint` | string or null | N | Chief Complaint |
| `illness_note` | string or null | N | Illness Note |

Example request:

```json
{
  "notes": "string",
  "ai_assessment_score": 0,
  "chief_complaint": "string",
  "illness_note": "string"
}
```

**Response 200:** `AssessmentReviewOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "session_id": "00000000-0000-0000-0000-000000000000",
  "assessment_id": "00000000-0000-0000-0000-000000000000",
  "status": "pending",
  "reviewer_id": "00000000-0000-0000-0000-000000000000",
  "reviewer_name": "string",
  "proposed_department_id": "00000000-0000-0000-0000-000000000000",
  "proposed_department_name_en": "string",
  "proposed_department_name_th": "string",
  "confirmed_department_id": "00000000-0000-0000-0000-000000000000",
  "confirmed_department_name_en": "string",
  "confirmed_department_name_th": "string",
  "ai_assessment_score": 0,
  "ai_assessment_scale": 10,
  "patient_contact_requested": false,
  "patient_contact_phone": "string",
  "patient_contact_preferred_time": "string",
  "patient_contact_relation": "string",
  "disposition_reasons": [
    {}
  ],
  "notes": "string",
  "visit_id": "string",
  "patient_name": "string",
  "vitals": {},
  "missing_vitals": [
    "string"
  ],
  "rejected_vitals": {},
  "ai_chief_complaint": "string",
  "ai_illness_note": "string",
  "patient_follow_up": "string",
  "chief_complaint": "string",
  "illness_note": "string",
  "his_routing_status": "string",
  "reviewed_at": "2026-08-04T09:00:00Z",
  "created_at": "2026-08-04T09:00:00Z",
  "updated_at": "2026-08-04T09:00:00Z"
}
```

---

### `POST /admin/reviews/{assessment_id}/correct`

Correct Assessment Review.

**Auth:** bearer token (roles: nurse, super_admin)

**Path params:** `assessment_id`

**Request body** (`application/json`, `AssessmentReviewCorrectRequest`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `confirmed_department_id` | string (uuid) | Y | Confirmed Department Id |
| `reason` | string or null | N | Reason |
| `ai_assessment_score` | integer or null | N | Ai Assessment Score |
| `chief_complaint` | string or null | N | Chief Complaint |
| `illness_note` | string or null | N | Illness Note |

Example request:

```json
{
  "confirmed_department_id": "00000000-0000-0000-0000-000000000000",
  "reason": "string",
  "ai_assessment_score": 0,
  "chief_complaint": "string",
  "illness_note": "string"
}
```

**Response 200:** `AssessmentReviewOut`

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "session_id": "00000000-0000-0000-0000-000000000000",
  "assessment_id": "00000000-0000-0000-0000-000000000000",
  "status": "pending",
  "reviewer_id": "00000000-0000-0000-0000-000000000000",
  "reviewer_name": "string",
  "proposed_department_id": "00000000-0000-0000-0000-000000000000",
  "proposed_department_name_en": "string",
  "proposed_department_name_th": "string",
  "confirmed_department_id": "00000000-0000-0000-0000-000000000000",
  "confirmed_department_name_en": "string",
  "confirmed_department_name_th": "string",
  "ai_assessment_score": 0,
  "ai_assessment_scale": 10,
  "patient_contact_requested": false,
  "patient_contact_phone": "string",
  "patient_contact_preferred_time": "string",
  "patient_contact_relation": "string",
  "disposition_reasons": [
    {}
  ],
  "notes": "string",
  "visit_id": "string",
  "patient_name": "string",
  "vitals": {},
  "missing_vitals": [
    "string"
  ],
  "rejected_vitals": {},
  "ai_chief_complaint": "string",
  "ai_illness_note": "string",
  "patient_follow_up": "string",
  "chief_complaint": "string",
  "illness_note": "string",
  "his_routing_status": "string",
  "reviewed_at": "2026-08-04T09:00:00Z",
  "created_at": "2026-08-04T09:00:00Z",
  "updated_at": "2026-08-04T09:00:00Z"
}
```

---

### `GET /admin/feedback`

List Routing Feedback.

**Auth:** bearer token (roles: nurse, super_admin, viewer)

**Response 200:** `array of RoutingFeedbackOut`

Example response:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000000",
    "session_id": "00000000-0000-0000-0000-000000000000",
    "assessment_id": "00000000-0000-0000-0000-000000000000",
    "original_department_id": "00000000-0000-0000-0000-000000000000",
    "corrected_department_id": "00000000-0000-0000-0000-000000000000",
    "corrected_department_name_en": "string",
    "corrected_department_name_th": "string",
    "reported_by": "00000000-0000-0000-0000-000000000000",
    "reporter_name": "string",
    "reason": "string",
    "created_at": "2026-08-04T09:00:00Z"
  }
]
```

---

### `GET /admin/his/connection`

Admin His Connection.

Current hospital-DB connection state for the Database Settings tab.

**Auth:** bearer token (roles: super_admin, nurse, viewer)

**Response 200:** `HisConnectionOut`

Example response:

```json
{
  "mode": "mock",
  "endpoint": "string",
  "name": "string",
  "connected": false,
  "visit_count": 0,
  "message": "string",
  "has_api_key": false
}
```

---

### `PUT /admin/his/connection`

Admin His Connect.

Establish (or change) the hospital-DB connection from the admin page.

Probes the endpoint first — an unreachable endpoint is rejected without
saving, so the demo can never end up pointed at a dead database. On
success the adapter is swapped live (no restart) and the config is
persisted to .env.

**Auth:** bearer token (roles: super_admin)

**Request body** (`application/json`, `HisConnectionUpdate`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `endpoint` | string | Y | Endpoint |
| `name` | string | Y | Name |
| `api_key` | string or null | N | Api Key |

Example request:

```json
{
  "endpoint": "string",
  "name": "string",
  "api_key": "string"
}
```

**Response 200:** `HisConnectionOut`

Example response:

```json
{
  "mode": "mock",
  "endpoint": "string",
  "name": "string",
  "connected": false,
  "visit_count": 0,
  "message": "string",
  "has_api_key": false
}
```

---

### `DELETE /admin/his/connection`

Admin His Disconnect.

Disconnect the hospital DB: back to the mock adapter, persisted.

HIS_BASE_URL is kept in .env so reconnecting pre-fills the last endpoint;
the access token is cleared (re-typed on reconnect — it's a secret, and
this is the UI's only way to drop a stale one). Booth flows keep working
(mock accepts every visit, write-backs are logged instead of sent).

**Auth:** bearer token (roles: super_admin)

**Response 200:** `HisConnectionOut`

Example response:

```json
{
  "mode": "mock",
  "endpoint": "string",
  "name": "string",
  "connected": false,
  "visit_count": 0,
  "message": "string",
  "has_api_key": false
}
```

---

### `GET /admin/his/visits`

Admin His Visits.

**Auth:** bearer token (roles: super_admin, nurse, viewer)

**Response 200:** JSON (Successful Response)

---

### `GET /admin/his/visits/{visit_id}`

Admin His Visit Detail.

**Auth:** bearer token (roles: super_admin, nurse, viewer)

**Path params:** `visit_id`

**Response 200:** JSON (Successful Response)

---

### `GET /admin/his/patients`

Admin His Patients.

HN master records from the connected hospital DB — the admin
Database tab's patient (HN) view. Each row already carries the full
history + last-vitals payload, so no per-patient detail proxy is needed.

**Auth:** bearer token (roles: super_admin, nurse, viewer)

**Response 200:** JSON (Successful Response)

---

### `GET /admin/criteria/versions`

List Criteria Versions.

**Auth:** bearer token (roles: super_admin, nurse, viewer)

**Response 200:** JSON (Successful Response)

---

### `GET /admin/criteria/versions/{version_id}`

Get Criteria Version Detail.

**Auth:** bearer token (roles: super_admin, nurse, viewer)

**Path params:** `version_id`

**Response 200:** JSON (Successful Response)

---

### `PUT /admin/criteria/versions/{version_id}`

Edit Criteria Version.

Replace a draft's criteria JSON (the pressure valve for imperfect extraction).

Saves even when the document has validation errors — they are returned so
the editor can fix them iteratively — but submit/activate require a clean
document.

**Auth:** bearer token (roles: super_admin, nurse)

**Path params:** `version_id`

**Request body** (`application/json`): see schema in /docs

Example request:

```json
{}
```

**Response 200:** JSON (Successful Response)

---

### `GET /admin/criteria/versions/{version_id}/diff`

Diff Criteria Version.

Section-level diff (added/removed/changed rule ids) vs another version.

**Auth:** bearer token (roles: super_admin, nurse, viewer)

**Path params:** `version_id`

**Query params:**

| Param | Type | Required | Notes |
|---|---|---|---|
| `against` | string (uuid) or null | N |  |

**Response 200:** JSON (Successful Response)

---

### `POST /admin/criteria/versions/{version_id}/submit`

Submit Criteria Version.

**Auth:** bearer token (roles: super_admin, nurse)

**Path params:** `version_id`

**Response 200:** JSON (Successful Response)

---

### `POST /admin/criteria/versions/{version_id}/approve`

Approve Criteria Version.

**Auth:** bearer token (roles: super_admin, nurse)

**Path params:** `version_id`

**Response 200:** JSON (Successful Response)

---

### `POST /admin/criteria/versions/{version_id}/activate`

Activate Criteria Version.

Activate an approved version. Activating a retired version = rollback.

**Auth:** bearer token (roles: super_admin, nurse)

**Path params:** `version_id`

**Response 200:** JSON (Successful Response)

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


---

## Schemas appendix

Request/response models referenced above.

### `AdminLoginRequest`

| Field | Type | Required | Notes |
|---|---|---|---|
| `email` | string | Y | Email |
| `password` | string | Y | Password |

### `AdminLoginResponse`

| Field | Type | Required | Notes |
|---|---|---|---|
| `access_token` | string | Y | Access Token |
| `token_type` | string | N | Token Type (default: `"bearer"`) |
| `expires_at` | string (date-time) | Y | Expires At |
| `user` | AdminUserOut | Y |  |

### `AdminUserCreate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `email` | string | Y | Email |
| `full_name` | string | Y | Full Name |
| `password` | string | Y | Password |
| `role` | string | N | Role (default: `"nurse"`) |

### `AdminUserManageOut`

Row in the admin User Settings table (nurse accounts).

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (uuid) | Y | Id |
| `email` | string | Y | Email |
| `full_name` | string or null | N | Full Name |
| `role` | string — one of `super_admin` \| `nurse` \| `viewer` | Y | Role |
| `is_active` | boolean | Y | Is Active |
| `last_login_at` | string (date-time) or null | N | Last Login At |
| `created_at` | string (date-time) | Y | Created At |

### `AdminUserOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (uuid) | Y | Id |
| `email` | string | Y | Email |
| `full_name` | string or null | N | Full Name |
| `role` | string — one of `super_admin` \| `nurse` \| `viewer` | Y | Role |

### `AdminUserUpdate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `full_name` | string or null | N | Full Name |
| `password` | string or null | N | Password |
| `is_active` | boolean or null | N | Is Active |

### `AreaSymptomCount`

| Field | Type | Required | Notes |
|---|---|---|---|
| `area` | string | Y | Area |
| `keyword` | string | Y | Keyword |
| `count` | integer | Y | Count |

### `AssessmentReviewApproveRequest`

| Field | Type | Required | Notes |
|---|---|---|---|
| `notes` | string or null | N | Notes |
| `ai_assessment_score` | integer or null | N | Ai Assessment Score |
| `chief_complaint` | string or null | N | Chief Complaint |
| `illness_note` | string or null | N | Illness Note |

### `AssessmentReviewCorrectRequest`

| Field | Type | Required | Notes |
|---|---|---|---|
| `confirmed_department_id` | string (uuid) | Y | Confirmed Department Id |
| `reason` | string or null | N | Reason |
| `ai_assessment_score` | integer or null | N | Ai Assessment Score |
| `chief_complaint` | string or null | N | Chief Complaint |
| `illness_note` | string or null | N | Illness Note |

### `AssessmentReviewOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (uuid) | Y | Id |
| `session_id` | string (uuid) | Y | Session Id |
| `assessment_id` | string (uuid) | Y | Assessment Id |
| `status` | string — one of `pending` \| `approved` \| `corrected` | Y | Status |
| `reviewer_id` | string (uuid) or null | N | Reviewer Id |
| `reviewer_name` | string or null | N | Reviewer Name |
| `proposed_department_id` | string (uuid) or null | N | Proposed Department Id |
| `proposed_department_name_en` | string or null | N | Proposed Department Name En |
| `proposed_department_name_th` | string or null | N | Proposed Department Name Th |
| `confirmed_department_id` | string (uuid) or null | N | Confirmed Department Id |
| `confirmed_department_name_en` | string or null | N | Confirmed Department Name En |
| `confirmed_department_name_th` | string or null | N | Confirmed Department Name Th |
| `ai_assessment_score` | integer or null | N | Ai Assessment Score |
| `ai_assessment_scale` | integer | N | Ai Assessment Scale (default: `10`) |
| `patient_contact_requested` | boolean or null | N | Patient Contact Requested |
| `patient_contact_phone` | string or null | N | Patient Contact Phone |
| `patient_contact_preferred_time` | string or null | N | Patient Contact Preferred Time |
| `patient_contact_relation` | string or null | N | Patient Contact Relation |
| `disposition_reasons` | array of object or null | N | Disposition Reasons |
| `notes` | string or null | N | Notes |
| `visit_id` | string or null | N | Visit Id |
| `patient_name` | string or null | N | Patient Name |
| `vitals` | object or null | N | Vitals |
| `missing_vitals` | array of string or null | N | Missing Vitals |
| `rejected_vitals` | object or null | N | Rejected Vitals |
| `ai_chief_complaint` | string or null | N | Ai Chief Complaint |
| `ai_illness_note` | string or null | N | Ai Illness Note |
| `patient_follow_up` | string or null | N | Patient Follow Up |
| `chief_complaint` | string or null | N | Chief Complaint |
| `illness_note` | string or null | N | Illness Note |
| `his_routing_status` | string or null | N | His Routing Status |
| `reviewed_at` | string (date-time) or null | N | Reviewed At |
| `created_at` | string (date-time) | Y | Created At |
| `updated_at` | string (date-time) | Y | Updated At |

### `BloodPressureFetchResponse`

Result of a kiosk-side omblepy fetch. ``status`` is always set; the reading fields are only present when ``status == "ok"``.

| Field | Type | Required | Notes |
|---|---|---|---|
| `status` | string — one of `ok` \| `busy` \| `not_configured` \| `device_not_found` \| `pairing_error` \| `wrong_device` \| `timeout` \| `no_records` \| `implausible` \| `not_seen` \| `resting` \| `error` | Y | Status |
| `systolic` | integer or null | N | Systolic |
| `diastolic` | integer or null | N | Diastolic |
| `pulse_bpm` | integer or null | N | Pulse Bpm |
| `measured_at` | string (date-time) or null | N | Measured At |
| `is_recent` | boolean or null | N | Is Recent |
| `irregular_heartbeat` | boolean or null | N | Irregular Heartbeat |
| `body_movement` | boolean or null | N | Body Movement |
| `message` | string or null | N | Message |
| `reading_id` | string (uuid) or null | N | Reading Id |
| `rest_until` | string (date-time) or null | N | Rest Until |
| `seconds_remaining` | integer or null | N | Seconds Remaining |

### `BpDeviceStatusOut`

Current cuff configuration shown in the admin portal.

| Field | Type | Required | Notes |
|---|---|---|---|
| `device_name` | string | Y | Device Name |
| `device_mac` | string or null | Y | Device Mac |
| `configured` | boolean | Y | Configured |
| `busy` | boolean | Y | Busy |
| `supported_models` | array of string | Y | Supported Models |

### `BpFetchRequest`

Optional body for the cuff fetch: links the stored reading to the kiosk session as soon as it is captured.

| Field | Type | Required | Notes |
|---|---|---|---|
| `session_id` | string (uuid) or null | N | Session Id |

### `BpPairRequest`

| Field | Type | Required | Notes |
|---|---|---|---|
| `mac` | string | Y | Mac |
| `device_name` | string | Y | Device Name |

### `BpPairResponse`

| Field | Type | Required | Notes |
|---|---|---|---|
| `status` | string — one of `ok` \| `busy` \| `invalid` \| `device_not_found` \| `pairing_error` \| `wrong_device` \| `timeout` \| `not_configured` \| `error` | Y | Status |
| `device_name` | string or null | N | Device Name |
| `device_mac` | string or null | N | Device Mac |
| `message` | string or null | N | Message |

### `BpRestStatusOut`

Whether this patient/visit must wait before another BP reading.

| Field | Type | Required | Notes |
|---|---|---|---|
| `resting` | boolean | Y | Resting |
| `rest_until` | string (date-time) or null | N | Rest Until |
| `seconds_remaining` | integer | N | Seconds Remaining (default: `0`) |
| `reason` | string or null | N | Reason |
| `hn` | string or null | N | Hn |
| `visit_id` | string or null | N | Visit Id |

### `BpScanDeviceOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `mac` | string | Y | Mac |
| `name` | string or null | N | Name |
| `rssi` | integer or null | N | Rssi |
| `is_omron` | boolean | N | Is Omron (default: `false`) |

### `BpScanResponse`

| Field | Type | Required | Notes |
|---|---|---|---|
| `status` | string — one of `ok` \| `busy` \| `error` | Y | Status |
| `devices` | array of BpScanDeviceOut | N | Devices |
| `message` | string or null | N | Message |

### `BpWatchRequest`

Body for the long-poll watch: wait up to ``timeout_seconds`` for the cuff's finished-measurement broadcast, then fetch immediately.

| Field | Type | Required | Notes |
|---|---|---|---|
| `session_id` | string (uuid) or null | N | Session Id |
| `timeout_seconds` | number | N | Timeout Seconds (default: `25`) |

### `ConfirmVisitNameRequest`

Patient response to "Is this you, {name}?" after link-visit.  Provide either ``confirmed`` (button) or ``text`` (typed/spoken natural language). When ``text`` is set, the shared yes/no classifier decides.

| Field | Type | Required | Notes |
|---|---|---|---|
| `confirmed` | boolean or null | N | Confirmed |
| `text` | string or null | N | Text |

### `ConfirmVisitNameResponse`

Outcome of the VN name-confirm step.

| Field | Type | Required | Notes |
|---|---|---|---|
| `decision` | string — one of `yes` \| `no` \| `uncertain` \| `other` | Y | Decision |
| `name_confirmed` | boolean | Y | Name Confirmed |
| `unlinked` | boolean | N | Unlinked (default: `false`) |
| `patient_name` | string or null | N | Patient Name |

### `ConversationSummaryOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `session_id` | string (uuid) | Y | Session Id |
| `language` | string — one of `th` \| `en` | Y | Language |
| `status` | string — one of `active` \| `completed` \| `reset` \| `escalated` | Y | Status |
| `started_at` | string (date-time) | Y | Started At |
| `ended_at` | string (date-time) or null | N | Ended At |
| `severity` | string — one of `emergency` \| `urgent` \| `general` \| `unknown` or null | N | Severity |
| `department_name_en` | string or null | N | Department Name En |
| `department_name_th` | string or null | N | Department Name Th |
| `message_count` | integer | Y | Message Count |
| `has_alert` | boolean | N | Has Alert (default: `false`) |
| `escalation_reason` | string or null | N | Escalation Reason |

### `DailyCount`

| Field | Type | Required | Notes |
|---|---|---|---|
| `date` | string | Y | Date |
| `count` | integer | Y | Count |

### `DepartmentOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (uuid) | Y | Id |
| `code` | string | Y | Code |
| `kind` | string — one of `emergency` \| `opd` | Y | Kind |
| `name_en` | string | Y | Name En |
| `name_th` | string or null | N | Name Th |
| `description_en` | string or null | N | Description En |
| `description_th` | string or null | N | Description Th |
| `is_active` | boolean | Y | Is Active |
| `floor` | string or null | N | Floor |
| `room` | string or null | N | Room |
| `nav_hint_en` | string or null | N | Nav Hint En |
| `nav_hint_th` | string or null | N | Nav Hint Th |
| `nav_line_en` | string or null | N | Nav Line En |
| `nav_line_th` | string or null | N | Nav Line Th |

### `DepartmentRecommendationCreate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `assessment_id` | string (uuid) or null | N | Assessment Id |
| `department_id` | string (uuid) | Y | Department Id |
| `confidence` | number or null | N | Confidence |
| `reason` | string or null | N | Reason |

### `DoctorCreate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `full_name` | string | Y | Full Name |
| `title` | string | N | Title (default: `"Dr."`) |
| `specialization` | string or null | N | Specialization |
| `department_id` | string (uuid) or null | N | Department Id |
| `phone_ext` | string or null | N | Phone Ext |
| `notes` | string or null | N | Notes |
| `is_active` | boolean | N | Is Active (default: `true`) |

### `DoctorOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (uuid) | Y | Id |
| `full_name` | string | Y | Full Name |
| `title` | string | Y | Title |
| `specialization` | string or null | N | Specialization |
| `department_id` | string (uuid) or null | N | Department Id |
| `department_name_en` | string or null | N | Department Name En |
| `department_name_th` | string or null | N | Department Name Th |
| `phone_ext` | string or null | N | Phone Ext |
| `notes` | string or null | N | Notes |
| `is_active` | boolean | Y | Is Active |
| `created_at` | string (date-time) | Y | Created At |
| `updated_at` | string (date-time) | Y | Updated At |

### `DoctorScheduleCreate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `schedule_date` | string (date) | Y | Schedule Date |
| `start_time` | string (time) | Y | Start Time |
| `end_time` | string (time) | Y | End Time |
| `break_start` | string (time) or null | N | Break Start |
| `break_end` | string (time) or null | N | Break End |
| `room` | string or null | N | Room |
| `slot_label` | string or null | N | Slot Label |
| `is_available` | boolean | N | Is Available (default: `true`) |
| `notes` | string or null | N | Notes |

### `DoctorScheduleOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `schedule_date` | string (date) | Y | Schedule Date |
| `start_time` | string (time) | Y | Start Time |
| `end_time` | string (time) | Y | End Time |
| `break_start` | string (time) or null | N | Break Start |
| `break_end` | string (time) or null | N | Break End |
| `room` | string or null | N | Room |
| `slot_label` | string or null | N | Slot Label |
| `is_available` | boolean | N | Is Available (default: `true`) |
| `notes` | string or null | N | Notes |
| `id` | string (uuid) | Y | Id |
| `doctor_id` | string (uuid) | Y | Doctor Id |
| `created_at` | string (date-time) | Y | Created At |
| `updated_at` | string (date-time) | Y | Updated At |

### `DoctorUpdate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `full_name` | string or null | N | Full Name |
| `title` | string or null | N | Title |
| `specialization` | string or null | N | Specialization |
| `department_id` | string (uuid) or null | N | Department Id |
| `phone_ext` | string or null | N | Phone Ext |
| `notes` | string or null | N | Notes |
| `is_active` | boolean or null | N | Is Active |

### `DoctorWithSchedulesOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (uuid) | Y | Id |
| `full_name` | string | Y | Full Name |
| `title` | string | Y | Title |
| `specialization` | string or null | N | Specialization |
| `department_id` | string (uuid) or null | N | Department Id |
| `department_name_en` | string or null | N | Department Name En |
| `department_name_th` | string or null | N | Department Name Th |
| `phone_ext` | string or null | N | Phone Ext |
| `notes` | string or null | N | Notes |
| `is_active` | boolean | Y | Is Active |
| `created_at` | string (date-time) | Y | Created At |
| `updated_at` | string (date-time) | Y | Updated At |
| `schedules` | array of DoctorScheduleOut | N | Schedules |

### `EmergencyEventCreate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `trigger_id` | string (uuid) or null | N | Trigger Id |
| `source_message_id` | string (uuid) or null | N | Source Message Id |
| `detected_symptoms` | array of any | N | Detected Symptoms |
| `alert_message` | string | Y | Alert Message |

### `EmergencyEventOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `trigger_id` | string (uuid) or null | N | Trigger Id |
| `source_message_id` | string (uuid) or null | N | Source Message Id |
| `detected_symptoms` | array of any | N | Detected Symptoms |
| `alert_message` | string | Y | Alert Message |
| `id` | string (uuid) | Y | Id |
| `session_id` | string (uuid) | Y | Session Id |
| `created_at` | string (date-time) | Y | Created At |

### `EmergencyTriggerOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (uuid) | Y | Id |
| `trigger_name` | string | Y | Trigger Name |
| `description` | string or null | N | Description |
| `trigger_keywords` | array of string | Y | Trigger Keywords |
| `condition_json` | object | Y | Condition Json |
| `alert_message_en` | string | Y | Alert Message En |
| `alert_message_th` | string or null | N | Alert Message Th |
| `priority` | integer | Y | Priority |
| `is_active` | boolean | Y | Is Active |

### `FollowUpQuestionAnswerUpdate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `answer_message_id` | string (uuid) | Y | Answer Message Id |

### `FollowUpQuestionCreate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `question_text` | string | Y | Question Text |
| `reason` | string or null | N | Reason |

### `FollowUpQuestionOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (uuid) | Y | Id |
| `session_id` | string (uuid) | Y | Session Id |
| `question_text` | string | Y | Question Text |
| `reason` | string or null | N | Reason |
| `asked_at` | string (date-time) | Y | Asked At |
| `answer_message_id` | string (uuid) or null | N | Answer Message Id |
| `answered_at` | string (date-time) or null | N | Answered At |

### `HisConnectionOut`

Hospital-DB connection state shown in admin Database Settings.

| Field | Type | Required | Notes |
|---|---|---|---|
| `mode` | string — one of `mock` \| `http` | Y | Mode |
| `endpoint` | string or null | N | Endpoint |
| `name` | string | Y | Name |
| `connected` | boolean | Y | Connected |
| `visit_count` | integer or null | N | Visit Count |
| `message` | string or null | N | Message |
| `has_api_key` | boolean | N | Has Api Key (default: `false`) |

### `HisConnectionUpdate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `endpoint` | string | Y | Endpoint |
| `name` | string | Y | Name |
| `api_key` | string or null | N | Api Key |

### `LinkVisitRequest`

| Field | Type | Required | Notes |
|---|---|---|---|
| `visit_id` | string | Y | Visit Id |
| `preconfirmed` | boolean | N | Preconfirmed (default: `false`) |

### `LinkVisitResponse`

| Field | Type | Required | Notes |
|---|---|---|---|
| `linked` | boolean | Y | Linked |
| `visit_id` | string | Y | Visit Id |
| `patient_name` | string or null | N | Patient Name |
| `age_years` | integer or null | N | Age Years |
| `appointment` | boolean | N | Appointment (default: `false`) |
| `has_his_vitals` | boolean | N | Has His Vitals (default: `false`) |
| `is_first_time` | boolean | N | Is First Time (default: `false`) |
| `hn` | string or null | N | Hn |

### `MessageCreate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `role` | string — one of `user` \| `assistant` \| `system` | Y | Role |
| `input_mode` | string — one of `voice` \| `text` \| `button` or null | N | Input Mode |
| `content` | string | Y | Content |
| `audio_url` | string or null | N | Audio Url |
| `transcript_confidence` | number or null | N | Transcript Confidence |
| `model_name` | string or null | N | Model Name |
| `response_latency_ms` | integer or null | N | Response Latency Ms |
| `metadata` | object | N | Metadata |

### `MessageOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `role` | string — one of `user` \| `assistant` \| `system` | Y | Role |
| `input_mode` | string — one of `voice` \| `text` \| `button` or null | N | Input Mode |
| `content` | string | Y | Content |
| `audio_url` | string or null | N | Audio Url |
| `transcript_confidence` | number or null | N | Transcript Confidence |
| `model_name` | string or null | N | Model Name |
| `response_latency_ms` | integer or null | N | Response Latency Ms |
| `metadata` | object | N | Metadata |
| `id` | string (uuid) | Y | Id |
| `session_id` | string (uuid) | Y | Session Id |
| `created_at` | string (date-time) | Y | Created At |

### `OutbreakAlert`

| Field | Type | Required | Notes |
|---|---|---|---|
| `keyword` | string | Y | Keyword |
| `area` | string or null | Y | Area |
| `recent_count` | integer | Y | Recent Count |
| `previous_count` | integer | Y | Previous Count |
| `increase_pct` | number | Y | Increase Pct |

### `PatientHistoryIntakeRequest`

First-time-patient structured history collected at the booth.

| Field | Type | Required | Notes |
|---|---|---|---|
| `smoking_alcohol` | string or null | N | Smoking Alcohol |
| `allergies` | string or null | N | Allergies |
| `chronic_conditions` | string or null | N | Chronic Conditions |
| `past_surgeries` | string or null | N | Past Surgeries |
| `family_history` | string or null | N | Family History |

### `PatientHistoryIntakeResponse`

| Field | Type | Required | Notes |
|---|---|---|---|
| `saved` | boolean | Y | Saved |
| `pushed_to_his` | boolean | Y | Pushed To His |
| `is_first_time` | boolean | N | Is First Time (default: `false`) |
| `hn` | string or null | N | Hn |

### `RoutingFeedbackOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (uuid) | Y | Id |
| `session_id` | string (uuid) | Y | Session Id |
| `assessment_id` | string (uuid) | Y | Assessment Id |
| `original_department_id` | string (uuid) or null | N | Original Department Id |
| `corrected_department_id` | string (uuid) | Y | Corrected Department Id |
| `corrected_department_name_en` | string or null | N | Corrected Department Name En |
| `corrected_department_name_th` | string or null | N | Corrected Department Name Th |
| `reported_by` | string (uuid) or null | N | Reported By |
| `reporter_name` | string or null | N | Reporter Name |
| `reason` | string or null | N | Reason |
| `created_at` | string (date-time) | Y | Created At |

### `RoutingRuleOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (uuid) | Y | Id |
| `department_id` | string (uuid) | Y | Department Id |
| `rule_name` | string | Y | Rule Name |
| `description` | string or null | N | Description |
| `symptom_keywords` | array of string | Y | Symptom Keywords |
| `condition_json` | object | Y | Condition Json |
| `severity_override` | string — one of `emergency` \| `urgent` \| `general` \| `unknown` or null | N | Severity Override |
| `priority` | integer | Y | Priority |
| `is_active` | boolean | Y | Is Active |

### `SessionByVisitOut`

Result of looking up a recent session by hospital visit ID (VN).  ``found=False`` when no same-day session is linked to this VN — the client should create a new session and call ``link-visit``. When ``found=True``, ``status`` says what the kiosk should offer: ``active`` → continue or start over; ``completed`` → start over / reprint slip.

| Field | Type | Required | Notes |
|---|---|---|---|
| `found` | boolean | Y | Found |
| `visit_id` | string | Y | Visit Id |
| `session` | SessionOut or null | N |  |
| `status` | string or null | N | Status |
| `patient_name` | string or null | N | Patient Name |
| `name_confirmed` | boolean | N | Name Confirmed (default: `false`) |
| `needs_history_intake` | boolean | N | Needs History Intake (default: `false`) |

### `SessionCreate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `language` | string — one of `th` \| `en` | N | Language (default: `"th"`) |
| `user_agent` | string or null | N | User Agent |
| `ip_hash` | string or null | N | Ip Hash |
| `metadata` | object | N | Metadata |

### `SessionLocationUpdate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `location_area` | string | Y | Location Area |

### `SessionMeasurementUpdate`

A single vital captured mid-interview when the engine requests it (temperature once a fever is reported; weight/height near the end of the interview). Merges into the session's stored vitals without disturbing the blood-pressure reading (BP has its own PUT with provenance).

| Field | Type | Required | Notes |
|---|---|---|---|
| `vital` | string — one of `temp` \| `weight` \| `height` | Y | Vital |
| `value` | number | Y | Value |

### `SessionOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (uuid) | Y | Id |
| `language` | string — one of `th` \| `en` | Y | Language |
| `status` | string — one of `active` \| `completed` \| `reset` \| `escalated` | Y | Status |
| `started_at` | string (date-time) | Y | Started At |
| `ended_at` | string (date-time) or null | N | Ended At |
| `user_agent` | string or null | N | User Agent |
| `ip_hash` | string or null | N | Ip Hash |
| `metadata` | object | Y | Metadata |

### `SessionUpdate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `status` | string — one of `active` \| `completed` \| `reset` \| `escalated` | Y | Status |

### `SessionVitalsUpdate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `systolic` | integer | Y | Systolic |
| `diastolic` | integer | Y | Diastolic |
| `pulse_bpm` | integer or null | N | Pulse Bpm |
| `weight_kg` | number or null | N | Weight Kg |
| `height_cm` | number or null | N | Height Cm |
| `temperature_c` | number or null | N | Temperature C |
| `measured_at` | string (date-time) or null | N | Measured At |
| `source` | string — one of `device` \| `manual` | N | Source (default: `"device"`) |
| `reading_id` | string (uuid) or null | N | Reading Id |

### `SeverityAssessmentCreate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `source_message_id` | string (uuid) or null | N | Source Message Id |
| `severity` | string — one of `emergency` \| `urgent` \| `general` \| `unknown` | N | Severity (default: `"unknown"`) |
| `confidence` | number or null | N | Confidence |
| `explanation` | string or null | N | Explanation |
| `detected_triggers` | array of any | N | Detected Triggers |

### `SeverityCount`

| Field | Type | Required | Notes |
|---|---|---|---|
| `severity_level` | string or null | Y | Severity Level |
| `count` | integer | Y | Count |

### `SttResponse`

| Field | Type | Required | Notes |
|---|---|---|---|
| `transcript` | string | Y | Transcript |
| `confidence` | number or null | N | Confidence |
| `language_code` | string | Y | Language Code |

### `SurveillanceSummaryOut`

| Field | Type | Required | Notes |
|---|---|---|---|
| `days` | integer | Y | Days |
| `total_reports` | integer | Y | Total Reports |
| `top_symptoms` | array of SymptomCount | Y | Top Symptoms |
| `by_area` | array of AreaSymptomCount | Y | By Area |
| `daily_trend` | array of DailyCount | Y | Daily Trend |
| `severity_distribution` | array of SeverityCount | Y | Severity Distribution |
| `outbreak_alerts` | array of OutbreakAlert | Y | Outbreak Alerts |

### `SymptomCount`

| Field | Type | Required | Notes |
|---|---|---|---|
| `keyword` | string | Y | Keyword |
| `count` | integer | Y | Count |

### `SymptomEntryCreate`

| Field | Type | Required | Notes |
|---|---|---|---|
| `message_id` | string (uuid) or null | N | Message Id |
| `raw_text` | string | Y | Raw Text |
| `normalized_symptoms` | array of any | N | Normalized Symptoms |
| `body_location` | string or null | N | Body Location |
| `duration_text` | string or null | N | Duration Text |
| `pain_score` | integer or null | N | Pain Score |
| `pain_location` | string or null | N | Pain Location |
| `distress_score` | integer or null | N | Distress Score |
| `distress_type` | string or null | N | Distress Type |
| `red_flags` | array of string | N | Red Flags |

### `TtsRequest`

| Field | Type | Required | Notes |
|---|---|---|---|
| `text` | string | Y | Text |
| `language` | string — one of `th` \| `en` | N | Language (default: `"en"`) |
