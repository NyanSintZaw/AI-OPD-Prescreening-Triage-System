# Meeting 2026-07-17 — Backend/AI Implementation Plan

> Source: stakeholder meeting notes on kiosk VN/HN flow, vitals, patient slip
> navigation text, session continuity, first-time-patient history, and
> natural-language chief complaints. Originally research + a plan; **all
> seven phases are now implemented** (see the per-phase status notes, dated
> 2026-07-21) and live-verified end to end. Kept as the design record for
> each phase.
>
> Companion reading: root `CLAUDE.md`, [`docs/his-integration.md`](his-integration.md),
> [`docs/triage-manual-vs-screening-criteria.md`](triage-manual-vs-screening-criteria.md),
> [`docs/current-system-audit.md`](current-system-audit.md) (stale — predates
> the ADK/pydantic-ai removal, but still accurate on frontend/role findings).

---

## 1. Meeting summary

### In scope (backend/AI work covered by this doc)

1. **VN confirmation** — after the visit number (VN) is entered, confirm the
   patient's full name back to them; if they say no / it's incorrect / any
   natural-language negation, reprompt for VN again (don't just accept a
   possibly-mistyped VN).
2. **Vital signs** — always recorded, never skippable; weight/height may be
   *omitted* if a recent measurement already exists for that patient (HN).
3. **Navigation instruction on the printed patient slip** — short, clear
   wayfinding text, e.g. *"Please proceed to the ENT Clinic, 3rd Floor."*
4. **First-time patient + session continuity**:
   - If a patient hangs up / walks away mid-session and re-enters the same
     VN, the system should **resume** the same session rather than start a
     fresh one.
   - **BP re-measure after a 15-minute rest timer** — a repeat BP reading
     (e.g. after a hypertensive-crisis flag) should only be allowed once 15
     minutes have elapsed since the flagged reading, and that "rest until"
     state must **persist across intervening patients** (i.e. it's tied to
     the patient/visit, not to browser/kiosk session memory).
5. **Patient additional information (first-time / new patients only)**:
   alcohol & smoking (with frequency), allergies (meds/food/other), chronic
   conditions, surgical history, family history of chronic/significant
   conditions. Also: **research whether the screening criteria need updates**
   so these factor into the assessment (not just get stored as inert data).
6. **Chief complaint in natural language** — the nurse-facing CC summary
   should read like a sentence a human would write, e.g. *"Fever for one day
   prior to hospital visit,"* not a machine-concatenated fragment list.

### Out of scope (explicitly excluded — do not implement)

- AI avatars.
- Map localization (Thai department names on the web map).
- Nurse floating icon button / iMed confirmation UI (the "last nurse
  interface line" mentioned in the meeting).

### Intended approach (as stated by the user, captured for the implementer)

- Evolve the mock HIS from VN-only toward a more realistic demo: add a real
  **HN table** for patient demographics/history, keep **VN** for visits, and
  **link HN↔VN** (this table already exists in code but is unused — see
  §2.1).
- Sessions must be consistent and linked to VN/HN; **resume** on re-entry of
  the same VN.
- The BP 15-minute timer must be **persisted** (Postgres, not in-memory) —
  the user's hypothesis is that `sessions`/a Postgres-backed table can carry
  this; confirmed feasible (§4.3).
- Additional history: research first whether/how the screening criteria
  schema needs new fields, then wire the collected history into the
  assessment (risk factors), not just into HIS/patient records.

---

## 2. Current state findings (with file paths)

### 2.1 Mock HIS (`hospital-his-mock/`)

- **`hospital-his-mock/his_mock/database.py`** defines the SQLite schema.
  There are **already three tables**:
  - `visits` (lines 32-59) — one row per visit, column-for-column mirror of
    the hospital's real `Prescreen` export. Pre-registration columns
    (`visit_id`, `hnx`, `patient_name`, `birthdate`, `appointment`) are
    hospital-owned; everything else (`weight`, `pressure`, `nurse_chief_complaint`,
    `first_location_*`, `second_location_*`, ...) starts NULL and is filled
    by our system's two-stage write-back (see `docs/his-integration.md` §0).
  - **`patients` (lines 61-77) — the HN "master record" table.** It already
    has exactly the columns the meeting asked for:
    `hn`, `patient_name`, `birthdate`, `smoking_alcohol`, `allergies`,
    `chronic_conditions`, `past_surgeries`, `family_history`,
    `history_recorded_at`, `last_weight`, `last_height`, `vitals_measured_at`.
    **This table is defined but has zero readers/writers anywhere in the
    codebase.** No endpoint in `his_mock/main.py` selects, inserts, or
    updates it; `seed_from_csv` never populates it. It is scaffolding that
    was added ahead of this work and is the natural foundation for §5.5/§5.6.
  - `prescreen_results` (lines 79-94) — the two-stage write-back holding
    table (Stage 1 pending → Stage 2 confirmed/rerouted), already fully wired
    (see `his_mock/main.py` `push_prescreen` / `confirm_routing`).
  - The module docstring (lines 1-21) explicitly already describes the
    intended design: *"a visit's `hnx` column links it to its patient... A
    patient with `history_recorded_at` NULL is a first-time patient: the
    booth collects their history and writes it back through the API."* The
    schema was clearly drafted for this exact meeting's requirements but
    the API layer was never finished.
- **`hospital-his-mock/his_mock/main.py`** (`build_app`) exposes only
  visit-centric endpoints today:
  - `GET /api/visits`, `GET /api/visits/{visit_id}` — read a visit
    (`visit_payload`, lines 158-199) — includes `hnx` but never joins to
    `patients`.
  - `POST /api/visits/{visit_id}/prescreen` — Stage 1 write-back (booth
    vitals + booth identity).
  - `PUT /api/visits/{visit_id}/routing` — Stage 2 write-back (nurse-signed
    chief complaint/illness note + destination department).
  - `PUT /api/visits/{visit_id}/follow-up` — patient's own follow-up note.
  - `GET /api/visits/{visit_id}/prescreen` — read the held Stage-1 result.
  - `POST /api/admin/reset` — demo reset.
  - `GET /api/departments` — distinct department strings seen on visits.
  - **There is no `/api/patients/{hn}` (or similar) endpoint at all.** No way
    to read/write a patient's HN-level history or last-known weight/height
    over HTTP, even though the SQLite table exists.
- **`hospital-his-mock/scripts/seed_db.py`** and **`sample_visits.csv`**
  seed only the `visits` table (pre-registration state for the synthetic
  sample). There is no `sample_patients.csv` or equivalent, and no seeding
  path populates `patients` at all — even the 12-row synthetic demo dataset
  has no matching HN rows today.

### 2.2 HIS adapter layer (`hospital-hotline-assistant-api/app/services/screening/his/`)

(Note: contrary to the exploration hint, this lives under
`app/services/screening/his/`, not `app/services/his/` — there is no
top-level `app/services/his/`.)

- **`his/adapter.py`** — the `HisAdapter` Protocol and `VisitInfo` dataclass
  (frozen, lines 15-26). `VisitInfo` carries `visit_id`, `patient_id` (this
  *is* the HN — populated from the HIS's `hn` field, see below),
  `patient_name`, `birthdate`, `age_years`, `vitals`, `appointment`, `raw`.
  There is **no history field** (`smoking_alcohol`/`allergies`/etc.) and no
  `last_weight`/`last_height`/`vitals_measured_at` — the protocol has no
  surface for §5.5/§5.2's "skip vitals if recent" requirement.
- **`his/mock.py`** — `MockHisAdapter.validate_visit` (lines 19-27) always
  returns a canned `VisitInfo(patient_name="Mock Patient", ...)` regardless
  of the `visit_id` passed in. It never actually calls the `hospital-his-mock`
  service; it's a pure in-process stub for tests/dev. **No name-confirmation
  or resume logic exists here.**
- **`his/http_adapter.py`** — `HttpHisAdapter.validate_visit` (lines 65-86)
  calls `GET /api/visits/{visit_id}` on the real HIS or `hospital-his-mock`
  and maps `data.get("hn")` → `VisitInfo.patient_id`. **Bug/gap:** the mock
  HIS's `visit_payload()` (`his_mock/main.py` lines 158-199) never emits a
  top-level `"hn"` key — it emits `"hnx"`. So `HttpHisAdapter` against the
  real `hospital-his-mock` service currently always gets `patient_id=None`.
  (Against the *real* hospital HIS this may differ; not verified here — flag
  as an open question, §6.)
- All write-back methods (`push_referral`, `push_follow_up`, `confirm_routing`)
  are visit-scoped only, matching the mock HIS's visit-centric endpoints.
- **`his/department_map.py`** — `CODE_TO_HIS` maps our 11 department codes to
  verbatim HIS department strings. No floor/room/location field anywhere.

### 2.3 Session model, VN linking, and resume

- **`sessions` table** (`migrations/001_hospital_hotline_schema.sql` lines
  10-19): `id UUID PK`, `language`, `status` (`active|completed|reset|escalated`),
  `started_at`, `ended_at`, `metadata JSONB`. **No `visit_id`/`hn` column** —
  the visit link lives entirely inside `metadata->'visit'` (JSONB), set by
  `link_visit` below. There is **no index on `metadata->'visit'->>'visit_id'`**
  and no unique constraint preventing two sessions from linking the same VN.
- **`POST /sessions/{session_id}/link-visit`**
  (`hospital-hotline-assistant-api/app/main.py` lines 451-525,
  `LinkVisitRequest`/`LinkVisitResponse` in `app/schemas.py` lines 76-87):
  - Calls `adapter.validate_visit(payload.visit_id)`. If found, writes
    `metadata["visit"] = {visit_id, hn, patient_name, birthdate, age_years,
    appointment, linked_at}` (lines 480-488) and seeds `metadata["vitals"]`
    from any HIS-known vitals (lines 491-496).
  - If the session has no messages yet, inserts a persisted greeting via
    `screening_templates.greeting_line(info.patient_name, language)` (lines
    508-517) — this is the **only** "personalization" that happens on link;
    there is **no name-confirmation question, no yes/no gate**. The patient
    is immediately greeted by name and the conversation proceeds.
  - **Nothing here checks for an existing session already linked to this
    `visit_id`.** Every call creates a brand-new `sessions` row upstream
    (see `POST /sessions`, lines ~415-448) before `link-visit` is ever
    called — confirmed in the frontend flow below. There is no "find and
    resume the in-progress session for VN X" path anywhere in `main.py`.
- **Frontend confirms there is no resume flow today.** In
  `hospital-hotline-assistant-web/src/pages/KioskSession.tsx`:
  - `handleLanguageSelect` (lines 93-117) **always** calls
    `api.createSession(...)` — a fresh UUID every time, regardless of VN.
  - `handleVisitSubmit` (lines 120-148) then calls `api.linkVisit(sessionId, visitId)`
    against that brand-new session. If the same VN is entered again
    (e.g. after a dropped call), a second, unrelated session gets linked to
    the same visit — the prior conversation state (`screening_sessions.state`,
    §2.4) is simply orphaned; the patient starts the interview over from
    turn zero.
  - The greeting phase (`phase === 'hello'`, lines 155-160) is a fixed
    2.2–3s timer that **auto-advances to `conversation`** — there is no
    "Is this you? Yes/No" prompt, no way to reprompt for VN from here. This
    is `VisitIdCapture.tsx` → `KioskSession.tsx`'s entire identity-check
    surface today: a not-found/link-error message (§2.6), nothing else.
- **`screening_sessions` table** (`migrations/013_screening_criteria.sql`
  lines 25-31): `session_id UUID PK REFERENCES sessions(id)`, `state JSONB`,
  `criteria_version_id`, `prompt_version`, `updated_at`. One-to-one with
  `sessions.id`; **keyed by session, not by visit/HN**, so it cannot be
  looked up by VN either — resuming would require first resolving
  VN → an existing `sessions.id`, then loading this row by that id (both are
  currently missing).

### 2.4 Screening engine state & graph (per-turn state machine)

- **`app/services/screening/state.py`** — `ScreeningState` (`Phase` = `intake
  | history | disposed | follow_up | done | escalated_to_nurse`, lines 13-15).
  No `history` phase is actually used by the graph yet (`graph.py` never
  routes into it — see below); it appears reserved for exactly this kind of
  future work (e.g. a pre-intake identity/history-collection phase).
  There are **no fields for smoking/alcohol/allergies/chronic
  conditions/surgeries/family history**, and no field for "recent
  weight/height on file" — `ScreeningState.vitals` is a flat `dict[str, float]`
  of the canonical rules-engine vital keys only (`vitals.py` aliases).
- **`app/services/screening/graph.py`** (lines 1-91) — the LangGraph state
  machine. `route_entry` (lines 39-47) dispatches on `phase` to exactly:
  `escalated_to_nurse → escalate`, `follow_up → followup`,
  `disposed|done → repeat`, else `→ ingest`. **There is no phase/route for
  VN confirmation or first-time-patient history intake** — any such flow
  would either need a new phase + graph node (in-conversation, bilingual,
  LLM-mediated) or — more simply for a kiosk demo — be handled entirely as
  pre-chat steps in the frontend/API before the graph's `ingest` node is
  ever invoked (see §5.3, §5.5 for the trade-off).
- **`app/services/screening/nodes/ingest.py`** already contains a robust,
  bilingual, regex-based **affirmation/negation/uncertainty classifier** used
  today for red-flag yes/no questions (lines 19-55):
  `_BARE_AFFIRMATION` (yes/yeah/ใช่/ครับ/ค่ะ...), `_BARE_DENIAL`
  (no/nope/none/ไม่/ไม่ใช่/เปล่า...), `_BARE_UNCERTAINTY`
  (not sure/ไม่แน่ใจ/ไม่รู้...). **This is the exact mechanism the VN-confirm
  reprompt-on-negation requirement needs** — it should be reused (imported
  or lifted into a small shared helper) rather than re-invented, so "no",
  "ไม่ใช่ค่ะ", "that's not me", etc. are recognized consistently with how the
  rest of the interview already handles negation. See §5.4.

### 2.5 Vitals / BP / `turn_context`

- **`app/services/screening/vitals.py`** — `normalize_vitals` (lines 67-85)
  maps kiosk/HIS raw keys (`systolic`/`diastolic`/`pulse_bpm`/`weight_kg`/
  `height_cm`/`temperature`) to canonical rules-engine keys (`sbp`/`dbp`/
  `hr`/`weight`/`height`/`temp`), deriving `map` from `sbp`/`dbp`.
  `apply_objective_findings` (lines 50-64) turns a measured `temp >= 37.8°C`
  into a `fever` finding directly (bypassing chat extraction) — the pattern
  to follow for any new objective-finding derivation (e.g. from history
  risk factors, §5.6).
- **`app/services/triage_service.py`** `_turn_context` (lines 98-117) is the
  seam that feeds `age_years`, `patient_name`, and `vitals` from
  `sessions.metadata` into the engine before the red-flag gate runs on every
  turn. Any HN-level "last known weight/height" or "recorded history risk
  factors" would flow through here too, once populated into `metadata`
  (see §4 for the proposed shape).
- **BP measurement in the criteria** (`app/data/screening_criteria_v1.json`):
  a `measurement`/`vital: sbp` question exists **per complaint template**
  (e.g. `gen_bp`, `cp_bp`, `dc_bp`, `hd_bp`, `fv_bp`, `pg_bp_measure` — asked
  unconditionally) but several templates only ask it when
  `"min_age_years": 60` (`ear_bp`, `nt_bp`, `eye_bp`, `mh_bp`, `msk_bp`,
  `ur_bp` — six of the ~14 complaint categories). **This contradicts the
  meeting's "vitals always recorded, can't skip" requirement** — today a
  40-year-old presenting with, say, eye pain is never asked for BP at all.
  Weight/height is asked once, universally, as a `pre_disposition_questions`
  entry (`pd_weight_height`, lines 5484-5493) with **no skip-if-recent
  logic** — it fires on every single disposed interview regardless of any
  HN history.
- **`bp_readings` table** (`migrations/012_bp_readings.sql`) — every cuff/
  manual BP reading is persisted immediately on capture (`session_id`
  nullable, `SET NULL` on session delete), independent of whether the
  patient continues. Endpoints: `POST /vitals/blood-pressure/fetch`,
  `POST /vitals/blood-pressure/watch` (`app/main.py` lines 760-857,
  `app/services/blood_pressure.py`). **There is no "15-minute rest before
  re-measure" gate anywhere.** The only existing 15-minute constant is
  `BloodPressureService._RECENT_WINDOW = timedelta(minutes=15)`
  (`blood_pressure.py` line 35) — this is a **device-clock-skew freshness
  check** (`is_recent()`, lines 288-291: "is this reading from the cuff's
  clock recent relative to server time"), a completely different concept
  from a clinical rest-before-remeasure timer. No code currently computes or
  stores a "next allowed remeasure time" for a patient/visit/session.
- **`SessionVitalsUpdate`** (`app/schemas.py` lines 42-49) is the manual-entry
  vitals shape (`systolic`/`diastolic`/`pulse_bpm`/`weight_kg`/`height_cm`/
  `temperature_c`) — used for patient-typed fallback vitals; no "skip" flag
  exists on it.

### 2.6 Patient slip / navigation instructions

- **`hospital-hotline-assistant-web/src/pages/SlipPage.tsx`** renders the
  printed slip: slip code, VN, patient name, department name, timestamp,
  vitals table (lines 123-196). **There is no navigation/wayfinding text
  line at all** — only the bare department name (`dd departmentName`, e.g.
  "OPD E.N.T (หู คอ จมูก)"). No floor/room info is fetched or shown.
- **`app/services/slip_code.py`** — `slip_code_for(session_id)` derives the
  human-readable slip code (`MCH-XXXX-XXXX`) from the session UUID; must
  match the frontend's `slipCode()` (`utils/slipCode.ts`) exactly. Unrelated
  to navigation text, but the natural place a "nav line" would be looked up
  alongside (by `session_id` → department → nav text).
- **Existing "please proceed to" copy already exists, just without a
  floor/room**, in `app/services/screening/templates.py`:
  `OPD_EXPLAIN`, `REPEAT_GUIDANCE`, `FOLLOW_UP_ACK`/`FOLLOW_UP_CLOSE` (and
  their `_NAMED` variants) all interpolate `{department}` from
  `department_display()` (lines 175-179) / the DB's bilingual department
  name. i18n mirror in the frontend: `proceedToGuidance` in
  `hospital-hotline-assistant-web/src/i18n/resources.ts` (lines 329, 1022):
  *"Please proceed to {{department}} — our staff will take care of you
  there."* **This is the exact template family to extend with a floor/room
  suffix** (§4.4, §5.7) — no new copy system is needed, just a data field.
- **`app/data/departments.json`** and the `departments` DB table/migrations
  (`001_hospital_hotline_schema.sql`, `015_departments_his_alignment.sql`)
  have **no floor/room/building column** for any of the 11 department codes.
- **Floor data already exists, but only in the frontend wayfinding map**,
  disconnected from the department model:
  `hospital-hotline-assistant-web/public/hospital-map/map-data.js` defines
  `FLOORS` (`Floor 1` line 12, `Floor 2` line 545) with per-location room
  data, but `RecommendationCard.tsx` (`getMapDestinationKey`, lines 40-47)
  only resolves **5 buckets** (`emergency`, `cardiology`, `neurology`,
  `pediatrics`, generic `opd`) from our 11 department codes — everything
  else falls back to generic OPD on the map. This is a real gap between "11
  clinically-routable departments" and "5 point locations on the map," which
  the nav-text feature will inherit unless department-level floor/room data
  is added independently of the map (recommended — see §4.4).

### 2.7 Screening criteria & additional patient history

- **`app/services/screening/rules/criteria_models.py`** — `FindingDef`
  (lines 216-223) already has an `is_risk_factor: bool` flag, and
  `TriageTuple.risk_factors_any` (lines 102-116) already lets a chronic
  condition/risk factor *modulate* (not just record) the triage decision —
  e.g. "cough ≥2 weeks" + risk factor "hemoptysis"/"evening_fever" forces a
  minimum level. **The schema mechanism for risk factors already exists and
  is proven** — it's a finding-catalog entry with `is_risk_factor: true`,
  referenced from `triage_tuples[].risk_factors_any`.
- **Existing risk-factor findings** in `app/data/screening_criteria_v1.json`
  (`finding_catalog`): `hypertension_history`, `diabetes_history`,
  `copd_history`, `heart_disease_history`, `oxygen_home`, `pregnancy`,
  `smoking` (lines ~1380-1438) — chronic conditions and smoking status
  **already exist as findings**, extracted today only when the patient
  happens to mention them conversationally (there is no dedicated intake
  question that asks for them upfront).
- **Missing from the finding catalog entirely:** `alcohol` (no alcohol
  finding of any kind — confirmed via full-text search), a generic
  `allergy_history`/drug-or-food-allergy risk factor (only
  `allergy_symptoms` exists, which is a *presenting symptom* — sneezing/itchy
  nose — not a history-of-allergy risk factor), `past_surgeries`/surgical
  history, and `family_history` of chronic conditions. None of these are
  referenced by any `triage_tuples` or `department_rules` today.
- **No "frequency" concept exists anywhere in the criteria schema.** Findings
  are binary (`present`/`absent`, `state.py` line 25); there's no scale/enum
  for "smokes daily" vs "smokes occasionally" vs "quit." The meeting's
  "alcohol & smoking (frequency)" requirement needs either (a) a new
  `FindingState`-like scale, or (b) storing frequency as free text on the HN
  patient record (§4.1) purely for the chart/nurse view, with only a
  binary/coarse risk-factor finding feeding the triage decision. Recommend
  (b) for v1 — simpler, and matches how `smoking` already works.
- **`app/services/screening/criteria_upload.py`** — the LLM-assisted
  extraction pipeline that turns an uploaded manual into a *draft* criteria
  version (upload → draft → pending_review → approved → active lifecycle,
  `screening_criteria_versions` table, `migrations/013_screening_criteria.sql`
  lines 4-23). Any new finding/risk-factor/question added for this meeting's
  history-collection requirement should go through this same versioning
  path (hand-edit `screening_criteria_v1.json` → bump to v2 via
  `scripts/seed_screening_criteria.py` or the admin upload/review UI), never
  a live edit to an active version. See `docs/triage-manual-vs-screening-criteria.md`
  for the full governance rationale.
- **Where new intake questions would live:** `ScreeningCriteria.universal_questions`
  (asked before any complaint-specific ones, every complaint) or a new
  dedicated list (e.g. `history_intake_questions`, parallel to
  `pre_disposition_questions`) gated to fire only when
  `state` (or `turn_context`) indicates a first-time patient (§4.1, §5.5).

### 2.8 Chief complaint generation & nurse review payloads

- **`app/services/screening/nodes/dispose.py`** `_summary(state)` (lines
  16-27) is the **entire** chief-complaint generator today:
  ```
  parts = [chief_complaint?, "findings: a, b, c"?, "onset: X"?, "duration: Y"?, "location: Z"?]
  "; ".join(parts)
  ```
  This produces strings like `"มีไข้; findings: fever, chills; onset: 1 day; location: -"`
  — a machine-readable fragment list, **not** a natural-language sentence.
  This value becomes `classification["symptoms_summary"]`
  (`build_classification`, line 48) and flows, unchanged, into:
  - `TriageResult.detected_symptoms` and disease-surveillance rows
    (`triage_service.py` lines 526-529, 561-568);
  - the HIS Stage-1 referral `complaint` field (`_maybe_push_referral`,
    line 797, → `hospital-his-mock`'s held `prescreen_results.complaint`,
    eventually published to `visits.nurse_chief_complaint` at Stage 2);
  - the nurse review queue's **`ai_chief_complaint`** column, read directly
    from `metadata->'triage_classification'->>'symptoms_summary'`
    (`app/main.py` lines 184, 1416, in the admin/nurse session list queries);
  - `assessment_reviews.chief_complaint`
    (`migrations/016_nurse_review_narrative.sql`) — the nurse-editable
    column a nurse can override at approve/correct time
    (`app/main.py` `AssessmentReviewApproveRequest`/`AssessmentReviewCorrectRequest`
    handling, lines ~1730-1822) — so today the nurse always starts from this
    fragment-list text as the default value to edit, rather than a
    ready-to-use sentence.
- **This is the single choke point to fix for requirement #6** — rewriting
  `_summary()` (or adding a new natural-language formatter called from
  `build_classification`) automatically improves the nurse queue, the HIS
  write-back, and disease surveillance simultaneously, with no other code
  changes required. See §5.8.
- `key_reason` (`build_classification` line 32) is a different field — the
  concatenated rule-citation reasons (e.g. red-flag rule labels) — this one
  is intentionally clinical/rules-oriented and is out of scope for the NL
  rewording (it maps to `nurse_patient_illness`/"illness note", not the
  chief complaint).

---

## 3. Gaps vs. requirements (summary table)

| # | Requirement | Current state | Gap |
|---|---|---|---|
| 1 | VN confirm name, reprompt on negation | `link_visit` greets by name immediately, no confirmation step (`app/main.py` §2.3) | No confirm-name phase/question; no reuse of existing negation regex (`ingest.py`) for this purpose |
| 2a | Vitals always recorded | BP measurement question is per-template and gated by `min_age_years: 60` for 6/14 categories (`screening_criteria_v1.json`) | Not universal; needs a `universal_questions`/always-fire BP question |
| 2b | Weight/height skip if recent | `pd_weight_height` fires unconditionally every time (`screening_criteria_v1.json` lines 5484-5493); `patients.last_weight/last_height/vitals_measured_at` columns exist but unused | No adapter/API surface exposes HN history to the engine; no skip predicate in `question_policy.py`/graph |
| 3 | Slip nav instruction (floor) | Slip shows department name only (`SlipPage.tsx`); no floor/room field in `departments` table or `departments.json`; floor only exists in frontend map data, mapped to 5 of 11 codes | Need a floor/room field on departments + a short nav-text template |
| 4a | Session resume on same-VN re-entry | `KioskSession.tsx` always creates a new session; `link_visit` never looks up an existing linked session | No "find active session by VN" endpoint/logic; no unique/lookup index on `metadata->'visit'->>'visit_id'` |
| 4b | BP 15-min rest-until timer, persisted across patients | Only a *device-freshness* 15-min window exists (`blood_pressure.py` `_RECENT_WINDOW`) — unrelated concept; `bp_readings` has no "rest until" concept | Need a new persisted "rest until" timestamp keyed by HN/visit, not session |
| 5a | Collect smoking/alcohol/allergies/chronic/surgical/family history for first-time patients | `patients` table has the right columns but zero API/adapter/UI wiring; `history_recorded_at` unused | Need mock-HIS `/api/patients/{hn}` endpoints, adapter methods, a kiosk history-intake step, and persistence back to HN |
| 5b | Feed history into the assessment | `smoking`/`hypertension_history`/etc. already work as `is_risk_factor` findings feeding `triage_tuples` (`criteria_models.py`) — mechanism exists | `alcohol`, `allergy_history`, `past_surgeries`, `family_history` findings don't exist yet; no wiring from collected history → `turn_context`/`state.findings` |
| 6 | Natural-language chief complaint | `_summary()` in `dispose.py` builds a fragment list, feeding nurse queue + HIS + surveillance | Needs an NL formatter (template-based or LLM-phrased-and-validated) |

---

## 4. Proposed data model

All additions below are **additive** (new tables/columns, no destructive
migrations) to keep with the repo's existing migration style (numbered,
idempotent `IF NOT EXISTS`, see `migrations/012_bp_readings.sql` for the most
recent example of the house style to follow).

### 4.1 HN (patient) master record — mock HIS side

Already scaffolded in `hospital-his-mock/his_mock/database.py` `patients`
table (§2.1) — just needs an API surface and wiring:

```sql
-- Already exists in his_mock/database.py; no migration needed there, it's
-- SQLite created at connect() time. Summarized here for the linkage design:
patients (
  hn                   TEXT PRIMARY KEY,
  patient_name         TEXT,
  birthdate            TEXT,
  smoking_alcohol      TEXT,   -- free text, e.g. "smokes ~5 cig/day; drinks socially"
  allergies            TEXT,   -- free text, e.g. "penicillin (rash); shrimp"
  chronic_conditions   TEXT,
  past_surgeries       TEXT,
  family_history       TEXT,
  history_recorded_at  TEXT,   -- NULL => first-time patient (drives §5.5)
  last_weight          REAL,
  last_height          REAL,
  vitals_measured_at   TEXT
)
```

Proposed new mock-HIS endpoints (in `his_mock/main.py`, alongside the
existing visit endpoints):

- `GET /api/patients/{hn}` → patient row + `is_first_time = history_recorded_at IS NULL`.
- `PUT /api/patients/{hn}/history` → upsert
  `smoking_alcohol/allergies/chronic_conditions/past_surgeries/family_history`
  + stamp `history_recorded_at = now()`.
- `PUT /api/patients/{hn}/vitals` (or fold into the existing prescreen
  write-back) → upsert `last_weight/last_height/vitals_measured_at` so the
  *next* visit's booth can decide to skip asking.
- `visit_payload()` should join `patients` and add an `"hn"` key (fixing the
  `hnx`-vs-`hn` mismatch noted in §2.2) plus a nested `"patient"` object
  carrying the history + recency fields, so `HttpHisAdapter.validate_visit`
  can populate them in one round trip.

### 4.2 `HisAdapter` protocol additions (Postgres-app side)

Extend `VisitInfo` (`app/services/screening/his/adapter.py`) with an
optional nested patient-history payload (kept optional/backward compatible
so `MockHisAdapter` and any real hospital HIS without this data still work):

```python
@dataclass(frozen=True)
class PatientHistory:
    is_first_time: bool
    smoking_alcohol: str | None = None
    allergies: str | None = None
    chronic_conditions: str | None = None
    past_surgeries: str | None = None
    family_history: str | None = None
    last_weight_kg: float | None = None
    last_height_cm: float | None = None
    vitals_measured_at: str | None = None  # ISO timestamp

@dataclass(frozen=True)
class VisitInfo:
    ...  # existing fields unchanged
    patient_history: "PatientHistory | None" = None
```

New adapter method (both `MockHisAdapter` and `HttpHisAdapter` implement it;
mock returns a canned "first-time" record, HTTP calls `PUT /api/patients/{hn}/history`):

```python
async def push_patient_history(self, hn: str, history: dict[str, Any]) -> bool: ...
```

### 4.3 Postgres additions (triage-app side)

**(a) BP rest-until timer — new table, keyed by patient/visit, not session:**

```sql
-- migrations/020_bp_rest_timer.sql (illustrative — actual number picked at
-- implementation time; follow the existing numbered/IF-NOT-EXISTS style)
CREATE TABLE IF NOT EXISTS bp_rest_windows (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Keyed by HN when known (so it survives across visits/sessions for the
    -- same patient); falls back to visit_id when no HN is linked yet, since
    -- the meeting's requirement is "persist across intervening patients"
    -- which really means "persist per patient, independent of kiosk/session
    -- state" — HN is the correct key once available.
    hn                  TEXT,
    visit_id            TEXT,
    triggered_by_reading UUID REFERENCES bp_readings(id) ON DELETE SET NULL,
    rest_until          TIMESTAMPTZ NOT NULL,
    reason              VARCHAR(50) NOT NULL DEFAULT 'hypertensive_crisis',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_bp_rest_windows_hn ON bp_rest_windows(hn);
CREATE INDEX IF NOT EXISTS idx_bp_rest_windows_visit_id ON bp_rest_windows(visit_id);
```

Flow: when a BP reading triggers `dv_adult_bp_crisis`
(`screening_criteria_v1.json` line 1794) or any danger-vital BP rule, insert
a row with `rest_until = now() + interval '15 minutes'`. Before allowing a
*repeat* measurement in the same or a later visit for the same HN, check for
an unresolved row where `rest_until > now()` and block/inform the kiosk UI
("please wait Xm before remeasuring") instead of accepting a too-soon reading.
This is deliberately **not** on `sessions` (as the user's hypothesis
suggested) because a session is per-visit/per-kiosk-run — the requirement is
patient-level persistence, which only HN (or, degraded, visit_id) satisfies.

**(b) Session ↔ visit linkage — index/lookup support for resume:**

No new column strictly required (the visit link already lives in
`sessions.metadata->'visit'->>'visit_id'`), but resume needs a lookup path:

```sql
CREATE INDEX IF NOT EXISTS idx_sessions_visit_id
    ON sessions ((metadata->'visit'->>'visit_id'))
    WHERE metadata->'visit'->>'visit_id' IS NOT NULL;
```

Resume query shape: "most recent `sessions` row with
`metadata->'visit'->>'visit_id' = :vn` AND `status = 'active'`" → if found,
return that `session_id` to the kiosk instead of creating a new one (see §5.2
for exact endpoint design — either a new `POST /sessions/resume-visit` or
folding the lookup into `link-visit`).

**(c) Departments — floor/room for nav text:**

```sql
ALTER TABLE departments
    ADD COLUMN IF NOT EXISTS floor VARCHAR(50),
    ADD COLUMN IF NOT EXISTS room VARCHAR(100),
    ADD COLUMN IF NOT EXISTS nav_hint_en TEXT,
    ADD COLUMN IF NOT EXISTS nav_hint_th TEXT;
```

`nav_hint_*` as an override escape hatch (e.g. "next to the pharmacy") in
case floor/room alone isn't clear enough for a given department; both
nullable so existing rows/tests are unaffected.

**(d) Finding catalog additions (criteria JSON, versioned — not a SQL migration):**

New `finding_catalog` entries in a **new criteria version** (never edit v1 in
place — see §2.7 governance note):
`alcohol_use` (is_risk_factor), `allergy_history` (is_risk_factor, distinct
from the existing symptom-level `allergy_symptoms`), `past_surgery_history`
(is_risk_factor), `family_history_chronic` (is_risk_factor). These are
*binary* present/absent findings for the rules engine; the rich free-text
detail (frequency, which allergy, which surgery) stays on the HN
`patients` record (§4.1) for chart/nurse display only.

### 4.4 Entity-relationship summary

```
patients (HN, mock HIS)  1 ──── * visits (VN, mock HIS)
     │  smoking_alcohol, allergies,          │  visit_id, hnx→hn, birthdate,
     │  chronic_conditions, past_surgeries,   │  first/second_location, vitals
     │  family_history, history_recorded_at,  │
     │  last_weight/height, vitals_measured_at│
     │                                        │
     └──────────────┬─────────────────────────┘
                     │ (validate_visit / push_patient_history via HisAdapter)
                     ▼
sessions (Postgres)  ── metadata->'visit' = {visit_id, hn, patient_name, ...}
     │
     ├── screening_sessions (1:1, engine state JSONB)
     ├── bp_readings (N, session_id nullable)
     ├── bp_rest_windows (N, keyed by hn/visit_id — NOT session_id)
     └── assessment_reviews (N, incl. nurse-editable chief_complaint/illness_note)

departments  +floor/room/nav_hint_en/nav_hint_th  →  patient slip nav line
```

---

## 5. Phased implementation plan (ordered, demo-ready)

Each phase is independently demo-able; later phases build on earlier ones.
Rough sizing included for planning, not a commitment.

### Phase 1 — Mock HIS: HN table + VN↔HN linkage (foundation) — **implemented**

> **Status (2026-07-21): done.** `patients` is now seeded (`sample_patients.csv`,
> half first-time/half returning) and wired: `GET /api/patients/{hn}`,
> `PUT /api/patients/{hn}/history`, `PUT /api/patients/{hn}/vitals`;
> `GET /api/visits/{id}` emits `"hn"` and a nested `"patient"` object;
> `POST /api/admin/reset` gained `reset_history`. On the app side,
> `VisitInfo.patient_history`/`PatientHistory` and
> `HisAdapter.push_patient_history` are wired as plumbing (parsed from the
> mock's nested `"patient"`, not yet consumed by `link_visit`/the engine —
> that's Phase 5). See `docs/his-integration.md` §0.1 for the short version.
> Session resume is Phase 2 (also done — see below).

1. Add `sample_patients.csv` (synthetic, matching `sample_visits.csv`'s
   `hnx` values) and a `seed_from_csv`-equivalent for `patients` in
   `his_mock/database.py`/`seed_db.py`.
2. Add `GET /api/patients/{hn}`, `PUT /api/patients/{hn}/history`,
   `PUT /api/patients/{hn}/vitals` to `his_mock/main.py`.
3. Fix `visit_payload()` to expose `"hn"` (not just `"hnx"`) and nest a
   `"patient"` object (history + recency), so a single `GET /api/visits/{id}`
   gives the triage-app everything it needs.
4. Update `_RESET_COLUMNS`/`/api/admin/reset` semantics if needed (decide:
   does reset also clear patient history for demo repeatability? Recommend
   a separate `reset_history: bool` flag on `ResetIn`, defaulting to
   `false`, so repeat demos of the *visit* flow don't keep re-triggering the
   first-time-patient history flow unless desired).
5. Tests: extend `hospital-his-mock/tests/test_his_api.py` for the new
   endpoints; a golden "first visit → history captured → second visit →
   `is_first_time=false`, last weight/height returned" test.

### Phase 2 — Session resume on same-VN re-entry — **implemented**

> **Status (2026-07-21): done.** Migration `020_sessions_visit_id_index.sql`
> adds `idx_sessions_visit_id`. Lookup helper
> `app/services/session_resume.py` + `GET /sessions/by-visit/{visit_id}`
> returns `{found, visit_id, session, patient_name}` for the most recent
> `active` session. Kiosk (`KioskSession.tsx`) and landing
> (`LandingPage.tsx`) check by-visit before create+link; resume skips the
> hello beat and goes straight to conversation. Abandoned mid-interview
> sessions stay `active` (no disconnect status change) so they remain
> resumable — TTL/cron for stale actives is still out of scope (§6).

1. Backend: add a lookup — either a new endpoint
   `GET /sessions/by-visit/{visit_id}?status=active` or extend
   `POST /sessions/{id}/link-visit` so the caller can pass a "resume if
   possible" flag and the handler checks
   `idx_sessions_visit_id` (§4.3b) before creating fresh state.
   Recommend a **new, explicit** endpoint (`GET /sessions/by-visit/{visit_id}`)
   rather than overloading `link-visit`, since the frontend needs to decide
   *before* creating a new session at all (today it creates the session
   first, then links — see §2.3 sequence). New flow:
   `check by-visit → resume (skip create) OR create + link (first time)`.
2. Frontend (`KioskSession.tsx`): before `api.createSession`, call the new
   lookup with the entered VN; if an active session is returned, hydrate
   local state (`setSessionId`, restore `patientName`, replay/scroll to
   current turn) and skip straight to `conversation` (or wherever the
   resumed `screening_sessions.state.phase` indicates) instead of `language`
   → `visit` → `hello`. This likely means moving VN entry earlier than
   language selection, or accepting that resume only works within the same
   language (simplest for v1 — flag as an open question, §6).
3. Decide session `status` semantics for "hung up mid-session": today
   nothing marks a session `completed`/`reset` on disconnect — it just stays
   `active` forever (`PATCH /sessions/{id}` is the only status-setter, and
   nothing calls it on disconnect). This is actually convenient for resume
   (an abandoned session is still `active` and resumable) but means stale
   `active` sessions accumulate — consider a TTL/cron note for later
   (§6), out of scope for the demo.
4. Tests: a `tests/screening/` or `tests/` integration test simulating
   link → a few turns → "disconnect" (just stop calling `/chat`) → same VN
   `by-visit` lookup → same `session_id` returned, `screening_sessions.state`
   unchanged.

### Phase 3 — VN confirm-name loop — **implemented**

> **Status (2026-07-21): done.** Shared classifier extracted to
> `app/services/screening/nlu_yesno.py` (`classify_yes_no`); ingest imports
> the same patterns. New endpoints:
> `POST /sessions/{id}/confirm-visit-name` (button or free-text → yes/no/
> uncertain; no unlinks) and `DELETE /sessions/{id}/link-visit`.
> `link-visit` stamps `metadata.visit.name_confirmed=false`. Kiosk shows
> `ConfirmNameStep` after a named link (and on resume if not yet confirmed);
> Yes → conversation, No → back to VN entry.

1. Decide implementation locus (see trade-off in §2.4): **recommend the
   simpler, frontend/API-orchestrated approach for the demo** rather than a
   new LangGraph phase:
   - After `link-visit` returns `patient_name`, the kiosk shows an explicit
     "Is this you, {name}? Yes/No" step (replacing today's silent
     auto-advancing `hello` phase in `KioskSession.tsx`) with two buttons
     **and** a free-text/voice input for a natural-language response.
   - Yes → proceed to `conversation` as today.
   - No / negation → clear the linked visit (a small new endpoint,
     `DELETE /sessions/{id}/link-visit` or reuse `link-visit` with an
     "unlink" semantic) and return to the VN-entry (`visit`) phase with the
     rejected VN pre-cleared, so the patient retypes.
   - For **voice/call** flows (not just kiosk-text), the same confirm step
     needs a bilingual spoken prompt + STT answer classified by the
     existing `_BARE_AFFIRMATION`/`_BARE_DENIAL` regexes (§2.4) — extract
     those regexes from `nodes/ingest.py` into a small shared module (e.g.
     `app/services/screening/nlu_yesno.py`) so both the graph and this new
     pre-chat confirm step import the same classifier instead of
     duplicating regex logic.
2. Backend: no schema change needed — this is orchestration over the
   existing `link-visit`/session metadata. Optionally record
   `metadata["visit"]["name_confirmed"] = true/false` for audit/nurse
   visibility.
3. Tests: unit tests for the extracted yes/no/uncertain classifier (reuse
   `tests/screening/test_ingest_negation*.py`-style cases if present, else
   new); a frontend interaction test or manual QA script for the kiosk
   confirm step.

### Phase 4 — Vitals always-recorded + BP 15-minute rest timer — **implemented**

> **Status (2026-07-21): done.** Dropped `min_age_years: 60` from all six
> age-gated BP measurement questions in `screening_criteria_v1.json`
> (refreshed active v1). Weight/height skip-if-recent (90 days) via
> `weight_height.py`, wired in `link_visit` from HN `patient_history`.
> Migration `021_bp_rest_windows.sql` + `app/services/bp_rest.py`; crisis
> BP (SBP>180 or DBP>110) opens a 15-min window on `PUT .../vitals`.
> `GET /vitals/blood-pressure/rest-status` and fetch/watch return
> `status=resting` while blocked; MeasurementCard shows a rest countdown.

1. Criteria change (new version, per §2.7 governance): move the BP
   `measurement`/`vital: sbp` question out of the six age-gated templates
   into `universal_questions` (or drop `min_age_years` from all of them) so
   BP is asked for every complaint category, every age — matching "vitals
   always recorded."
2. Weight/height skip-if-recent (§5.5 also touches this — implement once,
   shared): add a predicate consulted by `question_policy.next_question`
   (or a pre-check in `nodes/question.py`) — if `turn_context`/`state` carries
   `last_weight_kg`/`last_height_cm`/`vitals_measured_at` within a
   configurable recency window (propose 30–90 days; confirm with clinical
   stakeholders, §6) **and** no fresh cuff/manual entry exists yet this
   visit, mark `pd_weight_height` as resolved/skippable rather than firing
   it. Still allow the patient/kiosk to override and re-enter if they want.
3. `bp_rest_windows` (§4.3a): implement write path (insert on
   `dv_adult_bp_crisis`/danger-vital BP hit in `dispose.py` or a small hook
   in `vitals.py`) and read path (checked before accepting a *new* BP
   measurement attempt — likely in the `/vitals/blood-pressure/fetch|watch`
   endpoints or a new `GET /vitals/blood-pressure/rest-status?hn=...`
   the kiosk polls to show a live countdown).
4. Kiosk UI: when blocked, show "Please rest Xm before remeasuring" instead
   of the fetch/watch controls (reuse the existing BP fetch-error UI pattern
   in `BloodPressureFetchError`/`BpFetchRequest` handling for consistency).
5. Tests: `tests/screening/test_disposition.py`-style unit test that a BP
   crisis reading inserts a rest window with the right `rest_until`; an API
   test that a second reading attempt inside the window is rejected/flagged
   and one after is allowed.

### Phase 5 — First-time-patient additional history intake — **implemented**

> **Status (2026-07-21): done.** `link_visit` already stores
> `metadata.patient_history` (+ `is_first_time` on `LinkVisitResponse`).
> New findings in criteria: `alcohol_use`, `allergy_history`,
> `past_surgery_history`, `family_history_chronic`.
> `history_findings.apply_history_findings` + engine turn_context wiring.
> `POST /sessions/{id}/patient-history` pushes to HIS HN and marks
> `intake_complete`. Kiosk `HistoryIntakeStep` after name confirm when
> first-time; resume uses `needs_history_intake`.

1. Wire `HisAdapter.validate_visit` (§4.2) so `is_first_time` and any prior
   history reach `sessions.metadata` alongside the existing `visit`/`vitals`
   keys (extend `link_visit` in `app/main.py`, mirroring how `his_vitals`
   is merged today, lines 491-496).
2. Add a history-intake step, gated on `is_first_time`:
   - Kiosk/API-orchestrated (recommended, consistent with Phase 3's
     approach): a short structured form/voice Q&A *before* the symptom
     interview starts — smoking/alcohol frequency, allergies (meds/food/
     other, free text), chronic conditions, past surgeries, family history.
     Simple free-text or chip-based per field; no need for LLM extraction
     here since it's explicit structured intake, not conversational.
   - Persist via `HisAdapter.push_patient_history(hn, {...})` (§4.2) so it
     lands on the HN record in the mock HIS (`PUT /api/patients/{hn}/history`,
     Phase 1) — **not** only in `sessions.metadata`, since the point is it
     should carry forward to future visits.
   - Also stash a condensed version into `sessions.metadata["patient_history"]`
     for this visit's nurse-facing display and for feeding the engine
     (next step).
3. Criteria update (new version, per §2.7): add the four missing
   `is_risk_factor` findings (`alcohol_use`, `allergy_history`,
   `past_surgery_history`, `family_history_chronic`, §4.3d). Extend relevant
   `triage_tuples`/`department_rules` where clinically appropriate — this
   needs a short clinical-content pass (flag for nurse/clinical review, not
   a pure-engineering decision; see §6).
4. Wire the collected history into `state.findings` at turn start —
   mirroring `vitals.apply_objective_findings` (§2.5): a new
   `apply_history_findings(state, patient_history)` in `vitals.py` (or a new
   `history.py` alongside it) that sets `present` findings for e.g.
   `smoking` (already exists), `alcohol_use`, `hypertension_history`,
   `diabetes_history` etc. directly from structured HN data — bypassing the
   need for the patient to *also* mention it conversationally, same pattern
   as objective vitals beating chat extraction.
5. Tests: `tests/screening/` unit test that a synthetic first-time patient
   with `chronic_conditions="diabetes"` produces a `diabetes_history`
   finding at turn 1 without the patient mentioning it in chat.

### Phase 6 — Natural-language chief complaint — **implemented**

> **Status (2026-07-21): done.** Template formatter in
> `app/services/screening/chief_complaint.py` (`format_chief_complaint_summary`);
> `nodes/dispose.py` `_summary` delegates to it. Bilingual sentences like
> *"Fever for one day prior to hospital visit."* / Thai equivalent. No LLM
> (phase 6a only). Tests in `tests/screening/test_chief_complaint.py`.

1. Replace/augment `_summary(state)` in `nodes/dispose.py` (§2.8) with a
   template-based NL formatter as the safe default (no new LLM call, no
   validator risk): given `chief_complaint` text + resolved slots
   (`onset`/`duration`/`location`/`character`), compose a sentence per a
   small bilingual template set, e.g.
   `"{complaint} for {duration} prior to hospital visit"` /
   `"{complaint} มา {duration} ก่อนมาโรงพยาบาล"`, falling back gracefully
   when a slot is missing (mirrors how `templates.py` already does
   department-name interpolation with bilingual dict pairs).
2. Optional stronger version (phase 6b, if time allows): route the raw
   materials (chief complaint + slots + present findings) through the
   existing validated `explain` node pattern (`nodes/explain.py`) — i.e. an
   LLM phrases the sentence, `validator.py` checks it never leaks level/
   color/diagnosis, template fallback on any failure — consistent with the
   "LLM only phrases, rules decide" principle already documented in
   `CLAUDE.md`/`docs/triage-manual-vs-screening-criteria.md`. Start with 6a;
   only invest in 6b if template composition feels too mechanical in demo
   dry-runs.
3. No other call site changes needed — `build_classification` already
   funnels this single value everywhere it's needed (§2.8).
4. Tests: extend `tests/screening/test_golden_transcripts.py`-style fixtures
   asserting the new `symptoms_summary` reads as a sentence for a few
   representative complaint categories/languages.

### Phase 7 — Patient slip navigation text — **implemented**

> **Status (2026-07-21): done.** Migration `022_department_nav_fields.sql`
> adds `floor`/`room`/`nav_hint_en`/`nav_hint_th` with demo floor backfill
> (ENT = 3). `templates.nav_line()` composes bilingual instructions;
> `GET /departments` returns `nav_line_en`/`nav_line_th`. Slip page and
> `RecommendationCard` show the line (e.g. *"Please proceed to OPD ENT,
> 3rd Floor."*).

1. Migration: add `floor`/`room`/`nav_hint_en`/`nav_hint_th` to `departments`
   (§4.3c); backfill real MFU floor/room data for the 11 routable
   departments (content task, not engineering — coordinate with whoever
   supplied the HIS department strings in `docs/his-integration.md` §1.1).
2. Backend: extend `GET /departments` (already used by `SlipPage.tsx`) to
   include the new fields — no new endpoint needed, `DepartmentOut` in
   `app/schemas.py` just gains the columns.
3. Compose the short nav line server-side or client-side (recommend
   server-side, alongside the existing `templates.department_display`
   pattern, so voice and slip and any future channel share one formatter):
   `nav_line(department, language) = nav_hint_* override, else
   "{floor ordinal} Floor" / "ชั้น {floor}"` composed with the department
   name, e.g. *"Please proceed to the ENT Clinic, 3rd Floor."*
4. Frontend: add the nav line to `SlipPage.tsx` (a new `<p>` under the
   department `<dd>`) and reuse it for the existing `proceedToGuidance` i18n
   string in `RecommendationCard.tsx` so the in-chat recommendation and the
   printed slip say the same thing.
5. Tests: a schema/contract test that every active department code has
   non-null floor/room (or an explicit `nav_hint_*` override) — prevents a
   silent "—" on the printed slip in production.

---

## 6. Open questions / risks

1. **Real hospital HIS `hn` field name** — `HttpHisAdapter` currently reads
   `data.get("hn")`, but the mock HIS emits `hnx`. Confirm with the hospital
   IT contact (per `docs/hospital-integration-security.md`) whether the
   *real* HIS export uses `hn` or `hnx` (or both) for the field
   `HttpHisAdapter.validate_visit` should read, and fix
   `hospital-his-mock/his_mock/main.py`'s `visit_payload()` to match
   whichever is authoritative, so demo and production agree.
2. **Resume UX when language differs** — if a patient starts in Thai,
   disconnects, and re-enters the same VN choosing English, should the
   system resume the Thai session (in English going forward) or force a
   fresh session? Recommend: resume regardless of language re-selection,
   updating `sessions.language` and `screening_sessions.state.language` in
   place — but confirm this is acceptable for the demo script.
3. **BP rest-timer key when no visit is linked** — an anonymous
   (VN-skipped) patient has no HN to key `bp_rest_windows` on. Falling back
   to `visit_id`, and further to `session_id`, degrades "persist across
   intervening patients" to "persist only within this one session" for
   anonymous flows — acceptable given VN-linking is meeting requirement #4's
   explicit precondition, but worth stating clearly so it isn't assumed to
   work for walk-ins who skip VN entirely.
4. **Weight/height recency window** — no clinical guidance yet on how many
   days/weeks a prior weight/height stays "recent enough" to skip
   remeasuring. Needs a number from a clinical stakeholder before Phase 4
   ships (30 days? 90 days? same calendar visit only?).
5. **Which risk factors actually change triage decisions** — §5.5 adds the
   *schema* mechanism (new findings + risk-factor linkage), but *deciding*
   which `triage_tuples`/`department_rules` should reference
   `alcohol_use`/`allergy_history`/`past_surgery_history`/
   `family_history_chronic`, and with what clinical justification/citation
   (the criteria's citation-per-rule convention, e.g.
   `"citation": "MFU Triage — ..."`), is a clinical-content task, not
   something to invent unilaterally in code. Flag for nurse/clinical review
   before activating any new criteria version that uses them.
6. **Demo-reset semantics for patient history** — Phase 1's `ResetIn`
   extension (§5.1 step 4) needs a product decision: should the standard
   demo "reset all visits" button also wipe `patients.history_recorded_at`
   (so the first-time flow can be re-demoed on the same synthetic HN), or
   should that require an explicit separate action? Recommend a separate
   `reset_history` flag defaulting `false`, but confirm.
7. **Floor/room data source of truth** — is there an authoritative MFU
   facility floor plan/directory beyond what's already hand-encoded in
   `hospital-map/map-data.js` (which only covers 5 of 11 routable
   departments)? If not, the nav-text feature (Phase 7) may need the same
   manual-data-gathering effort the map itself required.
8. **VN confirm-name and voice/call parity** — Phase 3's plan covers both
   kiosk-text and voice, but voice adds real STT-accuracy risk (a
   misheard "yes" could wrongly confirm a wrong-VN match). Consider whether
   voice should require an explicit repeat-back of the name by the patient
   rather than a bare yes/no, or whether the existing yes/no confidence is
   acceptable for a nurse-reviewed, non-diagnostic identity check.
9. **`is_recent()`/15-minute naming collision** — implementers should be
   careful not to conflate `BloodPressureService._RECENT_WINDOW` (device
   clock-skew freshness, §2.5) with the new clinical rest-until timer
   (§4.3a) — they are unrelated 15-minute constants that happen to share a
   number. Recommend clearly distinct names in code/docs going forward
   (e.g. `DEVICE_FRESHNESS_WINDOW` vs. `bp_rest_windows`) to avoid future
   confusion.

---

## 7. Suggested next coding tasks (concrete, small, ordered)

These map to Phase 1–2 (the foundation everything else depends on) and are
sized to be single, reviewable changes:

1. Add `PatientHistory`/HN fields to `VisitInfo`
   (`app/services/screening/his/adapter.py`) and a
   `push_patient_history` method on the `HisAdapter` protocol +
   both implementations (`his/mock.py`, `his/http_adapter.py`) — pure
   plumbing, no behavior change yet (mock returns `is_first_time=True`
   canned data; HTTP adapter's new call is unused until Phase 1's mock-HIS
   endpoint exists).
2. `hospital-his-mock`: add `GET /api/patients/{hn}` and
   `PUT /api/patients/{hn}/history` to `his_mock/main.py`, backed by the
   already-existing `patients` table; add a `sample_patients.csv` + seeding
   helper; unit tests in `hospital-his-mock/tests/test_his_api.py`.
3. Fix `visit_payload()` to emit `"hn"` (§2.2/§6.1) and nest patient history;
   update `HttpHisAdapter.validate_visit` to read the nested shape into the
   new `VisitInfo.patient_history`.
4. Add `idx_sessions_visit_id` migration (§4.3b) and a new
   `GET /sessions/by-visit/{visit_id}` endpoint in `app/main.py` returning
   the most recent `active` session for that VN (404/`{found: false}` when
   none) — no frontend wiring yet, just the API + tests, so Phase 2's
   frontend work has something to call.
5. Extract the yes/no/uncertainty classifier from
   `app/services/screening/nodes/ingest.py` (`_BARE_AFFIRMATION`,
   `_BARE_DENIAL`, `_BARE_UNCERTAINTY` and their helper regexes) into a
   standalone module (e.g. `app/services/screening/nlu_yesno.py`) with unit
   tests, importing it back into `ingest.py` unchanged — pure refactor,
   zero behavior change, but unblocks Phase 3's confirm-name reuse cleanly.
6. Rewrite `_summary()` in `app/services/screening/nodes/dispose.py` to a
   template-composed natural-language sentence (Phase 6a) — self-contained,
   testable via `tests/screening/test_golden_transcripts.py`-style fixtures,
   immediately improves the nurse queue/HIS/surveillance without touching
   any other file (§2.8 confirms it's a single choke point).
7. `bp_rest_windows` migration (§4.3a) + a pure-function helper
   `compute_rest_until(reading, criteria) -> datetime | None` (no endpoint
   wiring yet) with unit tests against the existing `dv_adult_bp_crisis`
   rule shape — lands the schema and logic ahead of wiring it into the fetch/
   watch endpoints in Phase 4.
8. `departments` migration adding `floor`/`room`/`nav_hint_en`/`nav_hint_th`
   (§4.3c) + backfill for the 11 seeded department rows (content, small) +
   a `nav_line()` formatter next to `templates.department_display` with
   unit tests — lands ahead of the `SlipPage.tsx` UI change in Phase 7.
