"""Idempotent database bootstrap for local demo / dev.

Run with: ``uv run python scripts/init_db.py``.

Readies BOTH databases the demo needs, in one command:

**Postgres** (our database):
1. Connects to the cluster pointed at by ``DATABASE_URL`` (defaults to
   ``postgresql://postgres:postgres@localhost:5432/hospital_hotline``).
2. If the target database does not exist, creates it via the ``postgres``
   maintenance database in the same cluster.
3. Ensures a ``schema_migrations`` tracking table exists so each migration
   file is applied at most once, even across repeated runs on the same DB.
4. Applies every ``migrations/NNN_*.sql`` file in lexicographic order
   inside a single transaction per file, then records it in
   ``schema_migrations``.  Already-recorded files are skipped.
5. Seeds screening-criteria v1 (idempotent — same as
   ``seed_screening_criteria.py``) so the criteria-governance UI shows an
   active version. The engine also falls back to the bundled JSON, so this
   is a convenience, not a hard requirement.
6. Prints a summary of tables + seed-table row counts.

**Mock hospital DB (HIS, SQLite)**: a separate service that auto-seeds its
own SQLite on startup, so there is nothing to create here — this script just
health-checks it (``HIS_BASE_URL``, default ``http://localhost:8001``) and
reports whether it is up and seeded, so one run confirms both databases.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import urllib.request

import asyncpg


DEFAULT_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/hospital_hotline",
)
SUPER_URL = DEFAULT_URL.rsplit("/", 1)[0] + "/postgres"
MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent / "migrations"

SEED_TABLES = ("departments", "emergency_triggers", "routing_rules")


async def ensure_database() -> bool:
    """Make sure the target DB exists. Returns True on success."""

    try:
        conn = await asyncpg.connect(DEFAULT_URL)
        await conn.close()
        return True
    except asyncpg.InvalidCatalogNameError:
        pass
    except Exception as exc:
        print(f"ERROR: cannot reach Postgres at {DEFAULT_URL}: {exc}")
        return False

    print(f"Database does not exist yet. Creating via {SUPER_URL}...")
    try:
        super_conn = await asyncpg.connect(SUPER_URL)
        try:
            await super_conn.execute(
                "CREATE DATABASE " + DEFAULT_URL.rsplit("/", 1)[1]
            )
        finally:
            await super_conn.close()
    except Exception as exc:
        print(f"ERROR: failed to create database: {exc}")
        return False
    return True


async def ensure_migrations_table(conn: asyncpg.Connection) -> None:
    """Create the schema_migrations tracking table if it doesn't exist."""
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


async def get_applied_migrations(conn: asyncpg.Connection) -> set[str]:
    """Return the set of filenames that have already been applied."""
    rows = await conn.fetch("SELECT filename FROM schema_migrations")
    return {row["filename"] for row in rows}


async def apply_migration(
    conn: asyncpg.Connection,
    path: pathlib.Path,
    applied: set[str],
) -> str:
    """Apply a single SQL file unless already recorded. Returns a status string."""

    filename = path.name

    if filename in applied:
        return "skipped (already applied)"

    sql = path.read_text(encoding="utf-8")
    try:
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES ($1)",
                filename,
            )
        return "applied"
    except (
        asyncpg.DuplicateTableError,
        asyncpg.DuplicateObjectError,
        asyncpg.UndefinedColumnError,
        asyncpg.UndefinedTableError,
    ):
        # Migration was run manually, or a superseded migration references
        # columns/tables that no longer exist (e.g. 006 referencing
        # day_of_week after 007 replaced the schema). Record it as done so
        # future runs always skip it cleanly.
        await conn.execute(
            "INSERT INTO schema_migrations (filename) VALUES ($1) ON CONFLICT DO NOTHING",
            filename,
        )
        return "skipped (already applied / superseded)"


async def list_tables(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name <> 'schema_migrations'
        ORDER BY table_name
        """
    )
    return [row["table_name"] for row in rows]


async def count_rows(conn: asyncpg.Connection, table: str) -> int | None:
    try:
        return await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
    except asyncpg.UndefinedTableError:
        return None


async def seed_criteria() -> None:
    """Seed screening-criteria v1 (reuses seed_screening_criteria.main).

    Runs after migrations so the screening_criteria_versions table exists.
    Non-fatal: the engine falls back to the bundled JSON if this fails."""
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import seed_screening_criteria  # scripts/ is on sys.path[0]

        await seed_screening_criteria.main()
    except Exception as exc:  # noqa: BLE001 - best-effort convenience step
        print(f"  WARNING: criteria seed skipped ({exc})")


def check_his_mock() -> None:
    """Health-check the mock hospital HIS (separate SQLite service).

    It auto-seeds itself, so we only confirm it's reachable + seeded."""
    base = os.getenv("HIS_BASE_URL", "http://localhost:8001").rstrip("/")
    key = os.getenv("HIS_API_KEY", "demo-his-key")
    req = urllib.request.Request(f"{base}/api/visits", headers={"X-API-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310 - local demo URL
            data = json.load(resp)
        count = len(data.get("visits", []))
        print(f"  reachable at {base}: {count} visit(s) seeded")
    except Exception as exc:  # noqa: BLE001
        print(f"  NOT reachable at {base} ({exc}).")
        print("  Start the databases with:  docker compose up -d")


async def main() -> int:
    if not await ensure_database():
        return 1

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print(f"ERROR: no .sql files found in {MIGRATIONS_DIR}")
        return 2

    conn = await asyncpg.connect(DEFAULT_URL)
    try:
        await ensure_migrations_table(conn)

        # Seed the tracking table for migrations that were applied in
        # a previous session before this script had the tracking table.
        # We detect them by catching errors and recording them gracefully
        # inside apply_migration.
        applied = await get_applied_migrations(conn)

        print(f"Applying {len(migration_files)} migration file(s):")
        for path in migration_files:
            status = await apply_migration(conn, path, applied)
            print(f"  - {path.name}: {status}")

        tables = await list_tables(conn)
        print(f"\nTables present ({len(tables)}):")
        for name in tables:
            print(f"  - {name}")

        print("\nSeed row counts:")
        for table in SEED_TABLES:
            count = await count_rows(conn, table)
            label = "missing" if count is None else f"{count} rows"
            print(f"  - {table}: {label}")
    finally:
        await conn.close()

    print("\nSeeding screening criteria v1 (Postgres):")
    await seed_criteria()

    print("\nMock hospital DB (HIS, SQLite):")
    check_his_mock()

    print("\nPostgres is ready. Start the API with: uv run uvicorn app.main:app --reload")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
