"""Department names must stay aligned across the three sources that carry
the hospital's real HIS strings: the CODE_TO_HIS write-back map, migration
015, and departments.json. A drift here means the write-back or the nurse
dropdown would show a name the hospital doesn't recognize."""

import json
import re
from pathlib import Path

from app.services.screening.his.department_map import CODE_TO_HIS

API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = API_ROOT / "migrations" / "015_departments_his_alignment.sql"
DEPARTMENTS_JSON = API_ROOT / "app" / "data" / "departments.json"


def _migration_names() -> dict[str, str]:
    text = MIGRATION.read_text(encoding="utf-8")
    pairs = re.findall(
        r"SET name_th = '([^']+)'\s+WHERE code = '([a-z_]+)'", text
    )
    return {code: name for name, code in pairs}


def test_migration_matches_code_to_his():
    assert _migration_names() == CODE_TO_HIS


def test_departments_json_matches_code_to_his():
    payload = json.loads(DEPARTMENTS_JSON.read_text(encoding="utf-8"))
    by_code = {d["code"]: d.get("name_th") for d in payload["departments"]}
    for code, his_name in CODE_TO_HIS.items():
        assert by_code.get(code) == his_name, f"{code} name_th drift"
