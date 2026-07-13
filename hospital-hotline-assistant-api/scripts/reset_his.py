"""Reset the mock hospital HIS to its pre-registration ("registered") state.

Testing convenience: after a demo run, visits are left ``screened``/``routed``
with booth measurements + narrative written back. This clears that so the same
visit IDs can be demoed again.

Usage (from hospital-hotline-assistant-api/):

    uv run python scripts/reset_his.py                 # reset ALL visits
    uv run python scripts/reset_his.py 990000000000000003 990000000000000005

Config (env / .env): ``HIS_BASE_URL`` (default http://localhost:8001) and
``HIS_API_KEY`` (default demo-his-key), the same values the backend uses to
reach the mock. Talks to the mock's ``POST /api/admin/reset`` endpoint.
"""

import os
import sys

import httpx

BASE_URL = os.getenv("HIS_BASE_URL", "http://localhost:8001").rstrip("/")
API_KEY = os.getenv("HIS_API_KEY", "demo-his-key")


def main(argv: list[str]) -> int:
    visit_ids = [v for v in argv if v.strip()]
    url = f"{BASE_URL}/api/admin/reset"
    try:
        resp = httpx.post(
            url,
            headers={"X-API-Key": API_KEY},
            json={"visit_ids": visit_ids},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        print(f"Cannot reach the mock HIS at {BASE_URL}: {exc}")
        print("Is it running?  docker compose up -d his-mock")
        return 1

    if resp.status_code == 401:
        print(f"Unauthorized — HIS_API_KEY does not match the mock (tried {API_KEY!r}).")
        return 1
    if resp.status_code != 200:
        print(f"Reset failed ({resp.status_code}): {resp.text}")
        return 1

    body = resp.json()
    scope = f"{len(visit_ids)} visit(s)" if visit_ids else "ALL visits"
    print(f"Reset {body.get('reset')} visit(s) to registered ({scope}).")
    for vid in body.get("visit_ids", []):
        print(" -", vid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
