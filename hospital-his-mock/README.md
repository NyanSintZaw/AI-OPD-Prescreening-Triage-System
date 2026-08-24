# Hospital HIS (mock)

A standalone service that **simulates the hospital's side** of the integration
for demos. In production the hospital exposes an API over their own visit
database — we never connect to their database directly. This mock plays that
role: its data lives in its own SQLite store and is reachable only through the
REST API, exactly like the real HIS.

The triage backend talks to it through `HttpHisAdapter`
(`hospital-hotline-assistant-api/app/services/screening/his/http_adapter.py`).

The `visits` table is a **faithful, column-for-column mirror** of the real MFU
`Prescreen` export, so the hospital IT team sees literally their own screening
table.

### Before/after demo model

Each visit starts in its **post-registration, pre-screening** state — only
`visit_id`/`hnx`/`birthdate`/`appointment` are filled; every screening field
is blank. Then our system fills the blanks in two stages:

- **Stage 1** (`POST /api/visits/{id}/prescreen`, at the patient's receipt):
  measurements (`pressure`, `pulse`, `weight`, `height`, `bmi`, `temperature`)
  + our booth as `measure_*`/`first_location_*`. Status → `screened`.
- **Stage 2** (`POST /api/v1/patient-assignments`, on nurse confirm): the held
  clinical narrative (`nurse_chief_complaint`, `nurse_patient_illness`) +
  `second_location` (department). Status → `routed`.

`waist_width` is never written (a field we don't measure). See
`docs/his-integration.md` §0 for the full field-ownership table.

## Data

- **`sample_visits.csv`** — a small, fully **synthetic** set of demo visits
  loaded in **pre-registration state** (only the registration fields filled).
  Committed so the demo runs with no real data.
- **`sample_patients.csv`** — the matching HN (patient) master records for
  those visits' `hnx` values: demographics + booth-collected history
  (smoking/alcohol, allergies, chronic conditions, past surgeries, family
  history) + last-known weight/height. A blank `history_recorded_at` is a
  **first-time** patient; a filled one is **returning**. Half the sample is
  seeded each way so the demo shows both paths. Any visit whose `hnx` isn't
  in this CSV (e.g. a real export) gets a bare, first-time patient record
  auto-created on startup.
- **Real hospital exports stay out of git** (`.gitignore` blocks `Prescreen*.csv`
  and `*.db`). Point the loader at one with `HIS_MOCK_DATA_PATH` — a real export
  loads complete rows; the synthetic sample loads pre-registration. A matching
  real patients export can be pointed to with `HIS_MOCK_PATIENTS_DATA_PATH`.

## Run

### With Docker (recommended for the team — just like Postgres)

No Python/uv needed — only Docker. Same pattern as starting the Postgres DB:

```bash
cd hospital-his-mock
docker compose up -d          # API on http://localhost:8001
docker compose down           # stop
docker compose down && docker compose up -d --build   # reset to clean before-state
```

A fresh container auto-seeds the synthetic pre-registration sample. To load a
real export instead, uncomment the `volumes` + `HIS_MOCK_DATA_PATH` block in
`docker-compose.yml`.

### Locally with uv

```bash
cd hospital-his-mock
uv sync

# seed from the synthetic sample …
uv run python scripts/seed_db.py --sample
# … or from a real export kept outside the repo
HIS_MOCK_DATA_PATH=/path/to/Prescreen_7Day.csv uv run python scripts/seed_db.py

uv run uvicorn his_mock.main:app --port 8001
```

Open http://localhost:8001/docs — this doubles as the **"hospital side" window**
for the demo: watch a visit's record go blank → `screened` (stage 1) →
`routed` (stage 2) as the flow runs.

## API

Two families. **`/api/v1/*`** is the hospital contract per the *Data
Requirements Specification V1* (2026-08-11) — what `HttpHisAdapter` calls;
auth is `Authorization: Bearer` **or** `X-API-Key`. **`/api/*`** is the
legacy/admin family (admin Hospital DB tab, demo reset); `X-API-Key` only.
Default key `demo-his-key`, override with `HIS_MOCK_API_KEY`.

### `/api/v1` — the hospital contract (HN-first)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/patients/{hn}` | **The booth's identity read**: demographics, split history (`smoking`/`alcohol`, `post_surgeries`), `last_vitals` (`hight` — the contract's spelling), `is_first_time`, plus our extensions `gender` and `current_visit` (newest routable visit — the VN passthrough) |
| PUT | `/api/v1/patients/{hn}/history` | Fill-only history write-back (never overwrites); V1 §1.3 fields |
| PUT | `/api/v1/patients/{hn}/gender` | Fill-only gender write-back (our extension — V1 has no gender field) |
| POST | `/api/v1/patient-prescreens` | **Stage 1** (V1 §2.1/§4.3): objective vitals with per-vital `sources` + `bmi`, `measured_at`, booth as `first_location`. `visit_id` optional — resolves the HN's newest visit |
| POST | `/api/v1/patient-assignments` | **Stage 2** (V1 §2.2/§4.4): `base_department_id` (the mock picks the service point itself), `hn`, SBAR, `mfu_prescreen` stored verbatim → returns `queue_number`. Idempotent per `request_id`; `visit_id` optional with HN fallback |
| GET | `/api/v1/patient-assignments/{request_id}` | Read an assignment back by its idempotency key (incl. SBAR + `mfu_prescreen`) |
| GET | `/api/v1/visits/{visit_id}` | VN lookup per V1 §1.1 — implemented for contract fidelity; the HN-first booth flow no longer calls it |
| GET | `/api/v1/departments` | `{id, name, active}` per department (V1 §3.1) |

### `/api` — legacy/admin family

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/visits` | List all visits with `screening_status` (registered/screened/routed) — powers the admin Hospital DB tab |
| GET | `/api/visits/{visit_id}` | Full visit row plus nested `patient` object and both `hnx`/`hn` keys |
| GET | `/api/visits/{visit_id}/prescreen` | Read the held/staged prescreen record (incl. `measured_at` + vitals `sources`) |
| POST | `/api/visits/{visit_id}/prescreen` | Legacy Stage-1 write (dept/complaint held pending) |
| GET | `/api/patients` · GET `/api/patients/{hn}` | HN master records (+ `visit_count` on the list) |
| PUT | `/api/patients/{hn}/history` · `/vitals` | Unconditional history write / last-known weight-height |
| GET | `/api/departments` | Distinct department names seen in visit rows |
| POST | `/api/admin/reset` | Reset visits to pre-registration; `reset_history: true` also wipes the affected patients back to first-time |

## Config

| Env | Default | Meaning |
|---|---|---|
| `HIS_MOCK_DB_PATH` | `his_mock.db` | SQLite file |
| `HIS_MOCK_DATA_PATH` | _(unset)_ | Visits CSV to seed from when the DB is empty; falls back to `sample_visits.csv` |
| `HIS_MOCK_PATIENTS_DATA_PATH` | _(unset)_ | Patients CSV to seed from when the DB is empty; falls back to `sample_patients.csv` |
| `HIS_MOCK_API_KEY` | `demo-his-key` | required in `X-API-Key` |
