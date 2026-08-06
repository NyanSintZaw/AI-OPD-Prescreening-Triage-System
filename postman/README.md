# Postman collections

Generated from the FastAPI app's own OpenAPI definition — never hand-edited,
so they cannot drift from the code.

| File | What |
|---|---|
| `ai-opd-prescreening-api.postman_collection.json` | our whole API (75 requests, folders by URL prefix) |
| `his-integration.postman_collection.json` | only the calls **we make to the hospital HIS** (adapter calls + the real iMed contract) — this is the one to share with hospital IT |
| `local.postman_environment.json` | `baseUrl`, seeded login, auto-filled `token` / `session_id` |
| `his-local.postman_environment.json` | `hisBaseUrl`, `imedBaseUrl`, `hisToken` |

## Regenerating after an API change

```bash
cd hospital-hotline-assistant-api
uv run python scripts/api_docs/generate.py
```

Rewrites these files plus `docs/api-reference*.md`. Ids are deterministic, so
regenerating produces no spurious git diff. Postman does **not** watch the
files — re-import (desktop/VS Code) to pick changes up; the CLI always reads
the current file.

## Connecting

**Desktop app** — Import → drop in both `*_collection.json` and both
`*_environment.json` files → pick `mfu-triage local` in the environment
selector (top right). Re-importing after a regen updates in place.

Windows desktop app reading these WSL files: use the UNC path
`\\wsl.localhost\<distro>\home\timmy\AI-OPD-Prescreening-Triage-System\postman`.

**VS Code extension** (`postman.postman-for-vscode`) — Postman icon in the
sidebar → sign in → Collections → import the same files. Runs against
`localhost:8000` directly since the extension lives in the WSL remote.

**CLI** — no import needed, it runs the files as they are:

```bash
# whole collection
postman collection run postman/ai-opd-prescreening-api.postman_collection.json \
  -e postman/local.postman_environment.json

# just a few requests
postman collection run postman/ai-opd-prescreening-api.postman_collection.json \
  -e postman/local.postman_environment.json \
  -i "POST /admin/login" -i "GET /admin/reviews"

# override a variable without editing the file
... --env-var baseUrl=http://staging-host:8000
```

## How auth works

Collection-level **bearer** auth reads `{{token}}`; every role-protected
request inherits it and public kiosk routes are explicitly `noauth`, so
Postman's Auth tab always shows the truth.

`POST /admin/login` is the first folder (so CLI runs get a token before
reaching protected folders) and its test script captures `access_token` into
the environment automatically. `POST /sessions` captures `session_id` the same
way. Other path variables (`assessment_id`, `visit_id`, `doctor_id`, …) are
empty env slots — fill them from a real response.

Login credentials come from `{{email}}` / `{{password}}`, seeded to the dev
nurse account (`opd.nurse@mfu.local` / `nurse1234`, role `nurse`). Swap them
for `ops.admin@mfu.local` / `admin1234` to exercise super_admin-only routes —
as the nurse, `/admin/users` correctly returns 403.

## Not included

`WS /ws/voice/{session_id}` — Postman supports WebSocket requests but they
aren't expressible in the v2.1 collection format. Create one by hand against
`ws://localhost:8000/ws/voice/<session_id>?language=th`; the binary/JSON frame
contract is in `docs/api-reference.md`.

## Cloud workspace sync

The files above are the source of truth and live in git. Postman's own
two-way Git integration is an Enterprise feature; without it, pushing to a
Postman cloud workspace means importing (above) or a one-way push through the
Postman API with a personal API key. Ask if you want that scripted.
