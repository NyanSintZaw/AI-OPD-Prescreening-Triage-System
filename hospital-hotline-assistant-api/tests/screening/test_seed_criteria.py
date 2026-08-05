"""Seed-script logic tests (scripts/seed_screening_criteria.py) — fake
asyncpg connection, no DB. Covers v1-active/v2-draft seeding, idempotent
re-runs, and the --activate-v2 transition (retire previous active)."""

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

    async def fetchrow(self, query, *args):
        assert "WHERE version_no" in query
        return self.rows.get(args[0] if args else 2)

    async def fetch(self, query, *args):
        return [self.rows[k] for k in sorted(self.rows)]

    async def execute(self, query, *args):
        q = query.strip()
        if q.startswith("INSERT"):
            version_no, status, criteria_json, _summary, is_active = args
            assert is_active == (status == "active")
            assert version_no not in self.rows, "duplicate insert"
            self.rows[version_no] = {
                "id": f"id-{version_no}",
                "version_no": version_no,
                "status": status,
                "criteria": criteria_json,
            }
        elif "SET criteria" in q:
            criteria_json, row_id = args
            next(r for r in self.rows.values() if r["id"] == row_id)["criteria"] = criteria_json
        elif "SET status = 'retired' WHERE status = 'active'" in q:
            for row in self.rows.values():
                if row["status"] == "active":
                    row["status"] = "retired"
        elif "SET status = 'active'" in q:
            (row_id,) = args
            next(r for r in self.rows.values() if r["id"] == row_id)["status"] = "active"
        else:
            raise AssertionError(f"unexpected SQL: {q}")

    def transaction(self):
        return _NullTx()


async def _seed_all(conn):
    for version_no, path, status, summary in seed.SEEDS:
        await seed.seed_version(conn, version_no, path, status, summary)


async def test_seed_v1_active_v2_draft_and_idempotent():
    conn = FakeConn()
    await _seed_all(conn)
    assert conn.rows[1]["status"] == "active"
    assert conn.rows[2]["status"] == "draft"
    before = {k: dict(v) for k, v in conn.rows.items()}
    await _seed_all(conn)  # re-run: no duplicates, no changes
    assert conn.rows == before


async def test_activate_v2_retires_previous_active():
    conn = FakeConn()
    await _seed_all(conn)
    await seed.activate_v2(conn)
    assert conn.rows[1]["status"] == "retired"
    assert conn.rows[2]["status"] == "active"
    await seed.activate_v2(conn)  # idempotent
    assert conn.rows[2]["status"] == "active"
    before = {k: dict(v) for k, v in conn.rows.items()}
    await _seed_all(conn)  # re-seed after activation: statuses untouched
    assert conn.rows == before
