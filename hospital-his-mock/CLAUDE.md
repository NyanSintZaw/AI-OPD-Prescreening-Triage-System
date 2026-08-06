# Mock hospital HIS (SQLite, :8001)

- Simulates the hospital's visit API for demos — the real integration is always REST, never direct DB access. Backend talks to it via `HttpHisAdapter` when `HIS_MODE=http`.
- Runs via root `docker compose up -d`; auto-seeds itself from `sample_patients.csv`/`sample_visits.csv` on startup (`init_db.py` in the api repo only health-checks it).
- `visits` table is a column-for-column mirror of the real MFU `Prescreen` export — don't rename/add columns casually; the hospital IT demo depends on it looking identical.
- Before/after demo model: visits start post-registration with screening fields blank. Our system fills them in two stages: Stage 1 `POST /api/visits/{id}/prescreen` (measurements + booth location, status→`screened`); Stage 2 `POST /api/v1/patient-assignments` (nurse-confirmed routing, iMed-shaped — replaced the retired `PUT /api/visits/{id}/routing`). Details: `docs/his-integration.md`, `docs/imed-integration-plan.md`.
- Own uv project with its own tests; separate from the api's pytest run.
- `POST /api/v1/patient-assignments` mirrors the hospital's real iMed contract: `STATUS_SUCCESS`/`STATUS_BUSINESS_ERROR` envelope, 400/403/409/422 codes, idempotent per `request_id` (a replay returns the ORIGINAL result — our change request 7, not their draft). Auth accepts Bearer or X-API-Key. `service_points` holds ⚠️ PLACEHOLDER spids that must stay in lockstep with `CODE_TO_SPID` in the api repo.
- The container bakes the source into its image — after editing, `docker compose up -d --build his-mock`, or the old code keeps serving.
