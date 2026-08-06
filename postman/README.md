# Postman collections

Generated from the FastAPI app's own OpenAPI definition — never hand-edited,
so they cannot drift from the code.

| Path | What |
|---|---|
| `collections/AI OPD Prescreening API/` | our whole API (76 requests, folders by URL prefix) |
| `collections/HIS Integration (hospital-facing)/` | **the one to share with hospital IT** — what we send to their real iMed assignment API, split into `imed-assignment/from-contract` (contract-compliant, what we will actually send) and `imed-assignment/proposed` (our numbered change requests, made runnable) |
| `collections/Mock HIS (demo only)/` | the calls our adapter makes against our own demo mock. **Our assumptions, not their API** — kept separate so it cannot be mistaken for the contract |
| `environments/mfu-triage local.environment.yaml` | `baseUrl`, seeded login, auto-filled `token` / `session_id` |
| `environments/mfu-his local.environment.yaml` | `hisBaseUrl`, `imedBaseUrl`, `hisToken`, seeded VN/HN |

**Format is Postman v3 YAML**, not the old single-file JSON — Local Mode
dropped JSON support, so a `.json` collection here makes the desktop app show
an "Upgrade files" banner instead of loading it. Each collection is a
*directory*: one `.request.yaml` per request, `.resources/definition.yaml` for
the collection/folder metadata, and saved response examples under
`.resources/<request>.resources/examples/`.

The generator builds v2.1 (which maps cleanly from OpenAPI) and then runs
`postman collection migrate` to produce v3, so the format is whatever Postman
actually expects rather than something we hand-wrote. **This means the Postman
CLI must be installed to regenerate** — the generator fails loudly if it is not.

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

Do **not** import these — Local Mode reads them from disk, which is the point:
regenerating updates Postman instead of leaving a stale copy behind. (Import
also used to fail on the cloud-sync step for these files.)

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
# whole collection (point at the DIRECTORY, not a file)
postman collection run "postman/collections/AI OPD Prescreening API" \
  -e "postman/environments/mfu-triage local.environment.yaml"

# just a few requests
postman collection run "postman/collections/AI OPD Prescreening API" \
  -e "postman/environments/mfu-triage local.environment.yaml" \
  -i "POST /admin/login" -i "GET /admin/reviews"

# the hospital-facing one, against the mock HIS
postman collection run "postman/collections/HIS Integration (hospital-facing)" \
  -e "postman/environments/mfu-his local.environment.yaml"

# override a variable without editing the file
... --env-var baseUrl=http://staging-host:8000

# static check, no server needed
postman collection lint "postman/collections/AI OPD Prescreening API"
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
aren't expressible in the collection format. Create one by hand against
`ws://localhost:8000/ws/voice/<session_id>?language=th`; the binary/JSON frame
contract is in `docs/api-reference.md`.

## Cloud workspace sync

The files above are the source of truth and live in git. Postman's own
two-way Git integration is an Enterprise feature; without it, pushing to a
Postman cloud workspace means importing (above) or a one-way push through the
Postman API with a personal API key. Ask if you want that scripted.
