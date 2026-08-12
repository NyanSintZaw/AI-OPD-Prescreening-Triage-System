"""Seed-script logic tests (scripts/seed_screening_criteria.py) — fake
asyncpg connection, no DB. Covers the initial version-1-active insert,
idempotent re-runs, refresh-while-active, and --reset-to-initial collapsing
the history to a single row."""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))

import seed_screening_criteria as seed  # noqa: E402


class _NullTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    """Understands only the exact statements the seed script issues."""

    def __init__(self):
        self.rows: dict[int, dict] = {}  # version_no -> row dict
        self.unpinned_sessions = False
        self.unpinned_audit = False

    async def fetchrow(self, query, *args):
        assert "WHERE version_no = 1" in query
        return self.rows.get(1)

    async def fetch(self, query, *args):
        return [self.rows[k] for k in sorted(self.rows)]

    async def execute(self, query, *args):
        q = query.strip()
        if q.startswith("INSERT"):
            criteria_json, _summary = args
            assert 1 not in self.rows, "duplicate insert"
            self.rows[1] = {
                "id": "id-1",
                "version_no": 1,
                "status": "active",
                "criteria": criteria_json,
            }
        elif q.startswith("UPDATE screening_sessions"):
            self.unpinned_sessions = True
            return "UPDATE 0"
        elif q.startswith("UPDATE ai_inference_audit"):
            self.unpinned_audit = True
            return "UPDATE 0"
        elif "SET criteria" in q:
            criteria_json, row_id = args
            next(r for r in self.rows.values() if r["id"] == row_id)["criteria"] = criteria_json
        elif q.startswith("DELETE FROM screening_criteria_versions"):
            n = len(self.rows)
            self.rows.clear()
            return f"DELETE {n}"
        else:
            raise AssertionError(f"unexpected SQL: {q}")

    def transaction(self):
        return _NullTx()


async def test_seed_inserts_version1_active_and_is_idempotent():
    conn = FakeConn()
    await seed.seed(conn)
    assert list(conn.rows) == [1]
    assert conn.rows[1]["status"] == "active"
    before = {k: dict(v) for k, v in conn.rows.items()}
    await seed.seed(conn)  # re-run: no duplicates, no changes
    assert conn.rows == before


async def test_seed_refreshes_active_row_from_edited_file():
    conn = FakeConn()
    await seed.seed(conn)
    conn.rows[1]["criteria"] = json.dumps({"schema_version": 2})  # simulate drift
    await seed.seed(conn)
    assert json.loads(conn.rows[1]["criteria"]) == json.loads(
        seed.CRITERIA_PATH.read_text(encoding="utf-8")
    )


async def test_seed_leaves_non_active_version1_alone():
    conn = FakeConn()
    await seed.seed(conn)
    conn.rows[1]["status"] = "retired"
    conn.rows[1]["criteria"] = "{}"
    await seed.seed(conn)  # refresh branch must NOT fire on a retired row
    assert conn.rows[1]["criteria"] == "{}"


async def test_reset_to_initial_collapses_history_to_one_active_row():
    conn = FakeConn()
    await seed.seed(conn)
    conn.rows[2] = {"id": "id-2", "version_no": 2, "status": "retired", "criteria": "{}"}
    conn.rows[3] = {"id": "id-3", "version_no": 3, "status": "active", "criteria": "{}"}
    await seed.reset_to_initial(conn)
    assert list(conn.rows) == [1]
    assert conn.rows[1]["status"] == "active"
    # FK references are nulled before the delete so it cannot fail
    assert conn.unpinned_sessions and conn.unpinned_audit
