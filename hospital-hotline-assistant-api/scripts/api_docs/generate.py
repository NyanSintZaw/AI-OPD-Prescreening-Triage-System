"""Regenerate ALL API artifacts from the running code — one command:

    cd hospital-hotline-assistant-api
    uv run python scripts/api_docs/generate.py

Produces, straight from the FastAPI apps' own OpenAPI definitions:
  - docs/api-reference.md           (internal, incl. mock HIS)
  - docs/api-reference-hospital.md  (hospital-IT-facing, our API only)
  - postman/                        (Postman collections + environments)

Run it after any endpoint/schema change; re-import (or Postman-VS-Code
reopens) the regenerated files from disk.
"""
import json
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))

# 1. dump the main API spec
from app.main import app  # noqa: E402  (backend venv)

json.dump(app.openapi(), open(HERE / "openapi.json", "w"), ensure_ascii=False, indent=1)
print("dumped main spec:", len(app.openapi()["paths"]), "paths")

# 2. dump the mock-HIS spec (skip gracefully if its deps aren't importable)
try:
    sys.path.insert(0, str(ROOT / "hospital-his-mock"))
    from his_mock.main import app as his_app

    json.dump(
        his_app.openapi(), open(HERE / "openapi_his.json", "w"), ensure_ascii=False, indent=1
    )
    print("dumped mock-HIS spec:", len(his_app.openapi()["paths"]), "paths")
except Exception as exc:  # keep the last committed openapi_his.json
    print(f"mock-HIS dump skipped ({exc}); reusing existing openapi_his.json")

# 3. markdown fragments -> docs -> postman collections
runpy.run_path(str(HERE / "gen_api_doc.py"))
runpy.run_path(str(HERE / "assemble_docs.py"))
runpy.run_path(str(HERE / "postman_gen.py"))
print("done: docs/api-reference*.md + postman/ regenerated")
