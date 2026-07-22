# HIS Integration — Scope, Caveats & Benchmark Method

> Security architecture and the production-connection discussion with the
> hospital IT team live in [hospital-integration-security.md](hospital-integration-security.md).

This document records the deliberate scope decisions behind the hospital
HIS integration and the pre-screening booth flow, plus the method for the
optional replay benchmark (H7). It exists so the hospital IT team and
future developers understand **why** the system routes where it does — the
gaps below are choices, not oversights.

Context: MFU shared a 7-day prescreen export (`Prescreen_7Day`, 11,624
encounters). The real file is kept **out of git**; a synthetic sample lives
in `hospital-his-mock/sample_visits.csv`. All figures below are from that
7-day export.

---

## 0. What we READ vs what/when we WRITE (the demo's core model)

The mock hospital DB (`hospital-his-mock`, a faithful mirror of the
`Prescreen` export) starts each visit in its **post-registration,
pre-screening** state: only the fields the hospital already knows are
filled; everything the screening produces is blank until our system writes
it back. The two write-backs are split by data ownership and human sign-off.

| Field(s) | State | Who / when |
|---|---|---|
| `visit_id`, `hnx`, `birthdate`, `appointment` | pre-filled at registration | **hospital** — we only READ (birthdate → age) |
| `weight`, `height`, `bmi`, `pressure`, `pulse`, `temperature` | blank → filled | **Stage 1** (instant, at receipt) — measured at our booth |
| `measure_*`, `first_location_*` | blank → filled | **Stage 1** — our AI booth identity |
| `nurse_chief_complaint` (our `symptoms_summary`, not the raw chat) | blank → filled | **Stage 2** — nurse sign-off |
| `nurse_patient_illness` (our routing reason = `key_reason`) | blank → filled | **Stage 2** — held from Stage 1, published on confirm |
| `second_location_*` (the department) | blank → filled | **Stage 2** — nurse confirms/reroutes at the destination |
| `waist_width` | stays blank | nobody — a field we deliberately don't touch |

**Stage 1** fires the instant the patient finishes and gets their receipt
(session id on the slip): objective booth measurements + which booth. The
recommended department and reason are **held** on our side (patient slip +
`prescreen_results` pending) — NOT written to the hospital record.
**Stage 2** fires only when the patient reaches the routed department and the
nurse looks them up by session id and confirms/reroutes; that sign-off is
what publishes the clinical narrative + department. The raw multi-turn
conversation is never written to the hospital DB (only the engine's condensed
`symptoms_summary` / `key_reason`).

Status the demo shows on the admin **Hospital DB** tab: `registered` →
`screened` (Stage 1) → `routed` (Stage 2).

---

## 0.1 HN (patient) master record — Phase 1 of the backend/AI plan

> See [`meeting-2026-07-17-backend-ai-plan.md`](meeting-2026-07-17-backend-ai-plan.md)
> §4.1/§5 (Phase 1) for the full design; this is the short "what shipped"
> note.

The mock HIS's `patients` table (HN — hospital number) is now wired up
alongside `visits` (VN — visit number). Every visit's `hnx` links to a
`patients` row holding demographics, booth-collected history
(smoking/alcohol, allergies, chronic conditions, past surgeries, family
history), and the last-known weight/height — so a return visit's booth can
skip re-asking for history/vitals it already has on file.

- **`GET /api/visits/{visit_id}`** now also emits an `"hn"` key (an alias of
  `"hnx"`, fixing the naming mismatch `HttpHisAdapter` used to read — the
  real hospital HIS's field name is still an open question, see the backend/AI
  plan §6 item 1) and a nested `"patient"` object with that HN's history/last
  vitals, so one round trip gives the app everything it needs.
- **`GET /api/patients/{hn}`**, **`PUT /api/patients/{hn}/history`**,
  **`PUT /api/patients/{hn}/vitals`** — read/write the HN record directly.
  `is_first_time` is `true` iff `history_recorded_at IS NULL`.
- `hospital-his-mock/sample_patients.csv` seeds 8 synthetic patients matching
  `sample_visits.csv`'s HNs — half first-time, half returning — so the demo
  shows both paths. Any visit whose HN isn't in that CSV (e.g. a real export)
  gets a bare first-time patient record auto-created on startup.
- `POST /api/admin/reset` takes an optional `reset_history: true` to also
  wipe the affected patients back to first-time, for repeatable demos.
- On the triage-app side, `HisAdapter.push_referral`'s Stage-1 write-back is
  visit-scoped and unchanged. `VisitInfo` (`app/services/screening/his/adapter.py`)
  gained an optional `patient_history: PatientHistory | None` field parsed
  from the nested `"patient"` object, and adapters gained
  `push_patient_history(hn, history)`. **This is plumbing only** — nothing
  yet reads `patient_history` into session metadata or the screening engine;
  that's a later phase (first-time-patient history intake) per the plan.

---

## 1. Departments: what we route to, and what we don't

The AI engine routes to **11 destinations**. The hospital's export contains
**48 distinct departments**. The difference is intentional: most of the
other 37 are not triage destinations — they are recurring-treatment
programs, procedure rooms, inpatient wards, or service points a patient is
sent to *after* a clinical decision, not *as* one.

### 1.1 Routable destinations (our 11)

Mapped in `app/services/screening/his/department_map.py` (and mirrored in
migration `015_departments_his_alignment.sql` + `departments.json`):

| Our code | HIS department (verbatim) |
|---|---|
| `emergency` | แผนก ER (อุบัติเหตุและฉุกเฉิน) |
| `opd_general` | แผนก OPD GP (ทั่วไป ชั้น1) |
| `opd_internal_medicine` | แผนก OPD MED (อายุรกรรม) |
| `opd_pediatrics` | แผนก OPD PEDIATRIC (กุมารเวชกรรม) |
| `opd_cardiology` | แผนก OPD HEART (หน่วยตรวจหัวใจและหลอดเลือด) |
| `opd_orthopedics` | แผนก OPD ORTHOPEDIC (โรคกระดูกและข้อ) |
| `opd_ent` | แผนก OPD E.N.T (หู คอ จมูก) |
| `opd_surgery` | แผนก OPD SURGICAL (ศัลยศาสตร์) |
| `opd_ophthalmology` | แผนก OPD EYE (ตา) |
| `opd_psychiatry` | แผนก จิตเวช |
| `opd_obgyn` | แผนก OPD OB-GYN (สูติ-นรีเวชกรรม) |

In the 7-day data these 11 account for **7,393 of 11,606** routed
encounters (~64%).

### 1.2 Non-routable destinations (the other ~4,213 encounters)

These are real HIS destinations we deliberately do **not** produce as a
triage outcome. Grouped by why:

| Category | Examples (with 7-day volume) | Why excluded |
|---|---|---|
| **Recurring treatment programs** | HEMODIALYSIS ไตเทียม (1,046); IPD Ward 11B เคมีบำบัด / chemo (185) | Patients are on a standing schedule; they arrive *for* dialysis/chemo, not to be triaged. |
| **Preventive / community** | ส่งเสริมสุขภาพ PCU (789); WELL BABY เด็กดี (189) | Health-promotion and well-child visits, not symptom triage. |
| **Private after-hours (SMC)** | คลินิกพิเศษนอกเวลา SMC (379); SMC-EYE (86); SMC-ENT (33); SMC-HEART (5) | Separate after-hours private clinic track with its own booking. |
| **Integrative medicine** | MCH แพทย์บูรณาการ (266); MFU แพทย์บูรณาการ (236) | Specialty program outside the acute OPD triage scope. |
| **Rehab / therapy** | Rehabilitation เวชศาสตร์ฟื้นฟู (66); PHYSICAL กายภาพ (19); Occupational Therapy (9) | Referred *after* a physician assessment, not from front-desk triage. |
| **Procedure / theatre units** | Endoscopy Center (6); ห้องผ่าตัด OR (4); Labour Room ห้องคลอด (1) | Scheduled procedures, reached via a clinic first. |
| **Service points (non-clinical)** | CASHIER การเงิน (359 + 264 + 63 = 686); REGISTER / เวชระเบียน; ห้องยา pharmacy; ประสานสิทธิ์ rights; สังคมสงเคราะห์ social work; โภชนาการ nutrition | Payment, registration, records, dispensing — steps around a visit, not clinical destinations. |
| **Assessment / holding** | หน่วยตรวจชั้น 14 (190); ผู้ป่วยนอก(หน่วยคัดกรอง) screening (3) | Internal screening/holding points. |
| **Forensic** | นิติเวช (1) | Routes to ER per the manual; not a standalone OPD outcome. |

These are catalogued as *known HIS destinations* for display/write-back
context but are **not** added to the triage criteria. Adding any of them
later is a criteria-governance change (upload → review → approve), not a
code change.

---

## 2. Data-shape caveats (why raw "agreement" with the nurses is fuzzy)

The export captures a **different moment** in the patient journey than our
booth does, so a naive "did the AI pick the same department as the nurse"
comparison understates the engine. Specifics:

- **Most rows are appointment follow-ups.** 8,552 of 11,624 (74%) have
  `appointment=1` — patients arriving *for a scheduled visit* ("มาตามนัด
  ฟังผลเลือด" / "come as scheduled to hear blood results"). Their routing is
  driven by the existing appointment, not by fresh symptom triage. Only
  **3,072 (26%) are walk-ins** (`appointment=0`) — the population our booth
  actually serves.
- **The screening happens at the hospital, post-arrival.** These are
  nurse-station measurements on people already inside; our booth screens at
  or before arrival. Vitals, context, and available destinations differ.
- **The nurse's `nurse_chief_complaint` is free text, often non-symptomatic**
  ("มาตามนัด", "ปรึกษาผ่าตัด" / consult for surgery, "ฟังผลตรวจสุขภาพ" /
  hear checkup results) — not always a triage-able presentation.
- **Destination granularity is finer than triage.** The nurse can send to
  any of 48 points including the service points above; the engine emits one
  of 11 clinical destinations. A "disagreement" is often the engine
  correctly picking the clinical department while the nurse recorded a
  downstream step (cashier, lab, floor-14).

**Implication:** the honest comparison is on **walk-in, symptom-bearing
rows routed to one of our 11 destinations**, and the headline metric should
be the safety one (emergency recall), not overall department agreement.

---

## 3. Clinical / vitals caveats

- **Vitals are self-reported or cuff-measured, not a full monitored set.**
  The booth has BP (Omron cuff) + patient-typed weight/height/temperature.
  SpO₂, respiratory rate, and true resting HR are not captured, so
  danger-vital rules that need them stay dormant until kiosk hardware
  exists. Encoded now (criteria v1), idle until measured.
- **Hypotension is not a v1 danger-vital.** The adult danger-vital rules
  fire on hypertensive crisis (`sbp>180` / `dbp>110`) and tachycardia
  (`hr>120`), per the MFU manual. A low reading like 84/53 does **not**
  auto-escalate on vitals alone — it escalates via findings (e.g. chest
  pain + diaphoresis). This matches the hand-encoded manual; changing it is
  a criteria edit.
- **Vitals key mapping lives in one place** (`app/services/screening/
  vitals.py`): kiosk/HIS `systolic/diastolic/pulse_bpm/temperature` →
  rules-engine `sbp/dbp/hr/temp`, with MAP derived from sbp/dbp.

---

## 4. Data privacy

- The real hospital export is **never committed** (`hospital-his-mock/
  .gitignore` blocks `Prescreen*.csv` and `*.db`).
- Only `hospital-his-mock/sample_visits.csv` — 12 **fully synthetic** rows
  (fabricated IDs, HNs, and clinical text) — is in git, for tests and a
  CSV-less demo.
- The mock HIS loads the real file only from a path supplied at runtime
  (`HIS_MOCK_DATA_PATH`), and its SQLite store is gitignored.

---

## 5. Replay benchmark (H7) — method

**Not yet built** — pending a decision on scope (see §2). This section is
the design so we can agree before running it. It requires **live LLM calls**
(extraction runs through the configured model) and therefore Google
credentials + quota; it cannot run in CI.

### 5.1 Goal

Produce a credibility figure for the demo: how the deterministic engine's
routing compares to the nurses' real routing on the walk-in population,
with the **safety metric** (did we catch everyone they sent to the ER)
front and centre.

### 5.2 Pipeline (`scripts/replay_his_benchmark.py`, offline, resumable)

1. **Load & filter** the export. Keep `appointment=0` walk-ins whose
   `nurse_chief_complaint` looks symptom-bearing (drop "มาตามนัด…",
   "ฟังผล…", pure "ปรึกษา…"). Expect ~a few thousand rows → far fewer after
   the symptom filter.
2. **Build a synthetic patient utterance per row** from
   `nurse_chief_complaint` + `nurse_patient_illness`, with real
   `birthdate → age` and parsed vitals (`pressure`, `pulse`, `temperature`)
   as `turn_context` — the same objective inputs the booth would supply.
3. **Run the engine per row** (extraction → rules → disposition). One or a
   few turns; no interactive follow-up (we can't ask the historical patient
   questions, so budget-exhaustion disposes on what's present).
4. **Map** the nurse's `second_location_department` to our 11 codes where
   possible; rows whose nurse destination is non-routable (§1.2) are
   reported separately, not counted as disagreements.
5. **Score** and emit a Markdown report:
   - **Emergency recall** (primary): of rows the nurse sent to ER, how many
     the engine also flagged emergency. Target: high — misses are the only
     truly costly error.
   - **Emergency precision**: of engine-flagged emergencies, how many the
     nurse also sent to ER (over-triage rate).
   - **Department agreement** on mappable, non-emergency walk-ins.
   - **Disagreement examples** with the full rules trace (which rule fired,
     which finding was/wasn't extracted) so clinicians can adjudicate.
6. **Resumability**: checkpoint each row's result to JSONL; re-runs skip
   done rows. `--sample N` runs N random rows first for a cheap sanity pass
   before a full run.

### 5.3 How to read the result (framing matters)

- A department "disagreement" is **not** necessarily an engine error — it
  may be the granularity mismatch of §2 (engine picks the clinical dept;
  nurse recorded a downstream step) or a genuinely ambiguous case.
- The number to trust and to present is **emergency recall**. Everything
  else is context, and each disagreement is a concrete, inspectable case
  (with its rule trace) for the nurses to rule on — which itself is useful
  input to the next criteria version.

### 5.4 Scope decision (recorded 2026-07-07)

**Decided: (a) safety-focused, deferred.** The first run — when built — will
report emergency recall + precision + department agreement on the
clearly-mappable walk-in subset, and keep the raw per-row JSONL so the
broader confusion matrix (b) can be computed later without re-spending
LLM quota. (a) is the credible, defensible story for the hospital IT team;
(b) is noisier given the §2 data-shape caveats.

**Status: not yet built.** Deferred until after the live E2E demo dry-run,
because it needs Google credentials + quota and cannot run in CI. Build is a
single offline script (`scripts/replay_his_benchmark.py`) per §5.2.
