# Postman collections

Generated from the FastAPI app's own OpenAPI definition — never hand-edited,
so they cannot drift from the code.

| File | What |
|---|---|
| `collections/ai-opd-prescreening-api.postman_collection.json` | our whole API (75 requests, folders by URL prefix) |
| `collections/his-integration.postman_collection.json` | only the calls **we make to the hospital HIS** (adapter calls + the real iMed contract) — this is the one to share with hospital IT |
| `environments/local.postman_environment.json` | `baseUrl`, seeded login, auto-filled `token` / `session_id` |
| `environments/his-local.postman_environment.json` | `hisBaseUrl`, `imedBaseUrl`, `hisToken` |

The `collections/` + `environments/` split is **required**: Postman's local
workspace auto-registers everything inside a `postman/` folder and ignores
loose files at the folder root.

## Regenerating after an API change

```bash
cd hospital-hotline-assistant-api
uv run python scripts/api_docs/generate.py
```

Rewrites these files plus `docs/api-reference*.md`. Ids are deterministic, so
regenerating produces no spurious git diff. A folder-backed Postman workspace
(below) picks the changes up from disk; the CLI always reads the current file.

## Connecting

Both collections validate cleanly against Postman's official v2.1.0 schema,
so if an **Import** shows a red (!) with "Retry", that is Postman's
cloud-sync step failing, not a malformed file — retry, or skip importing and
use one of the file-backed options below (which are better anyway, because
regenerating updates Postman instead of leaving a stale copy).

**Desktop app — "Work with your local codebase"** (recommended). Point it at a
*workspace root* — the folder that **contains** `postman/`, not `postman/`
itself. For this project that is the repo root.

- Best: open the repo root. The Windows picker cannot browse WSL, so paste
  this into the dialog's *Folder:* field:
  `\\wsl.localhost\Ubuntu\home\timmy\AI-OPD-Prescreening-Triage-System`
  Postman then reads `postman/collections` + `postman/environments` directly —
  one copy, always current, and since the repo is already git, Postman's
  branch-aware/cloud-sync actions light up without "Set up Git".
- Fallback if UNC is unreliable: use a Windows-side mirror such as
  `D:\postman` (open *that* folder — it contains its own `postman/`) and
  always regenerate with the mirror flag so it never goes stale:

  ```bash
  cd hospital-hotline-assistant-api
  POSTMAN_MIRROR_DIR=/mnt/d/postman uv run python scripts/api_docs/generate.py
  ```

Postman writes its own `.postman/resources.yaml` into whichever folder you
open; it holds an account-specific workspace id and is gitignored.

**VS Code extension** (`postman.postman-for-vscode`) — signs in to your
Postman workspace; the same cloud-sync caveat applies to its importer.

**CLI** (no import, no sign-in — this is what the collections were verified
with). It runs the repo files as they are:

```bash
# whole collection
postman collection run postman/collections/ai-opd-prescreening-api.postman_collection.json \
  -e postman/environments/local.postman_environment.json

# just a few requests
postman collection run postman/collections/ai-opd-prescreening-api.postman_collection.json \
  -e postman/environments/local.postman_environment.json \
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
