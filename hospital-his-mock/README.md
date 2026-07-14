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
- **Stage 2** (`PUT /api/visits/{id}/routing`, on nurse confirm): the held
  clinical narrative (`nurse_chief_complaint`, `nurse_patient_illness`) +
  `second_location` (department). Status → `routed`.

`waist_width` is never written (a field we don't measure). See
`docs/his-integration.md` §0 for the full field-ownership table.

## Data

- **`sample_visits.csv`** — a small, fully **synthetic** set of demo visits
  loaded in **pre-registration state** (only the registration fields filled).
  Committed so the demo runs with no real data.
- **Real hospital exports stay out of git** (`.gitignore` blocks `Prescreen*.csv`
  and `*.db`). Point the loader at one with `HIS_MOCK_DATA_PATH` — a real export
  loads complete rows; the synthetic sample loads pre-registration.

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

All endpoints require `X-API-Key` (default `demo-his-key`, override with
`HIS_MOCK_API_KEY`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/visits` | List all visits with `screening_status` (registered/screened/routed) — powers the admin Hospital DB tab |
| GET | `/api/visits/{visit_id}` | Full visit row (demographics + any filled screening fields); booth reads this after the patient types their visit ID |
| POST | `/api/visits/{visit_id}/prescreen` | **Stage 1**: write booth measurements + booth location; hold dept/complaint/reason pending |
| PUT | `/api/visits/{visit_id}/routing` | **Stage 2**: nurse confirms/reroutes → publish narrative + second_location |
| GET | `/api/visits/{visit_id}/prescreen` | Read the held/finalized prescreen record |
| GET | `/api/departments` | Distinct department names known to the HIS |

## Config

| Env | Default | Meaning |
|---|---|---|
| `HIS_MOCK_DB_PATH` | `his_mock.db` | SQLite file |
| `HIS_MOCK_DATA_PATH` | _(unset)_ | CSV to seed from when the DB is empty; falls back to `sample_visits.csv` |
| `HIS_MOCK_API_KEY` | `demo-his-key` | required in `X-API-Key` |
