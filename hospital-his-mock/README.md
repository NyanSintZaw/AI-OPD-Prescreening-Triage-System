# Hospital HIS (mock)

A standalone service that **simulates the hospital's side** of the integration
for demos. In production the hospital exposes an API over their own visit
database — we never connect to their database directly. This mock plays that
role: its data lives in its own SQLite store and is reachable only through the
REST API, exactly like the real HIS.

The triage backend talks to it through `HttpHisAdapter`
(`hospital-hotline-assistant-api/app/services/screening/his/http_adapter.py`).

## Data

- **`sample_visits.csv`** — a small, fully **synthetic** set of demo visits
  (fabricated IDs, HNs, and clinical text). Committed so the demo runs with no
  real data.
- **Real hospital exports stay out of git** (`.gitignore` blocks `Prescreen*.csv`
  and `*.db`). Point the loader at one with `HIS_MOCK_DATA_PATH`.

The CSV layout matches the hospital's 7-day prescreen export
(`visit_id, hnx, appointment, birthdate, pressure, temperature, pulse,
nurse_chief_complaint, …, first/second_location_*`).

## Run

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
for the demo: watch a visit's prescreen record appear (stage 1) and flip to
`confirmed`/`rerouted` (stage 2) as the flow runs.

## API

All endpoints require `X-API-Key` (default `demo-his-key`, override with
`HIS_MOCK_API_KEY`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/visits/{visit_id}` | Visit + patient birthdate + HIS vitals (booth reads this after the patient types their visit ID) |
| POST | `/api/visits/{visit_id}/prescreen` | **Stage 1**: AI booth pushes the pending prescreen (dept, complaint, vitals, reasons) |
| PUT | `/api/visits/{visit_id}/routing` | **Stage 2**: nurse confirms or reroutes at the destination |
| GET | `/api/visits/{visit_id}/prescreen` | Read the current prescreen record |
| GET | `/api/departments` | Distinct department names known to the HIS |

## Config

| Env | Default | Meaning |
|---|---|---|
| `HIS_MOCK_DB_PATH` | `his_mock.db` | SQLite file |
| `HIS_MOCK_DATA_PATH` | _(unset)_ | CSV to seed from when the DB is empty; falls back to `sample_visits.csv` |
| `HIS_MOCK_API_KEY` | `demo-his-key` | required in `X-API-Key` |
