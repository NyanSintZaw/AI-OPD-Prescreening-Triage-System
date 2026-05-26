"""Idempotent database bootstrap for local demo / dev.

Run with: ``uv run python scripts/init_db.py``.

What it does, in order:

1. Connects to the cluster pointed at by ``DATABASE_URL`` (defaults to
   ``postgresql://postgres:postgres@localhost:5432/hospital_hotline``).
2. If the target database does not exist, creates it via the ``postgres``
   maintenance database in the same cluster.
3. Applies every ``migrations/NNN_*.sql`` file in lexicographic order
   inside a single transaction per file.
4. Skips any migration whose every statement is already a no-op (we rely
   on each migration being written to be idempotent: ``CREATE TABLE IF
   NOT EXISTS`` etc.). Today's only migration uses unconditional
   ``CREATE TABLE`` / ``CREATE TYPE`` / ``INSERT INTO`` so re-running on
   an already-initialised DB will raise ``DuplicateTableError`` -- in
   that case we detect it and exit successfully with a clear message
   instead of crashing.
5. Prints a summary of tables, plus the row counts for the seed tables
   (``departments``, ``emergency_triggers``, ``routing_rules``) so the
   operator can verify before running the demo.

This script is intentionally dependency-free beyond ``asyncpg`` (already
in pyproject) so it works on a fresh checkout with just ``uv sync``.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

import asyncpg


DEFAULT_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/hospital_hotline",
)
SUPER_URL = DEFAULT_URL.rsplit("/", 1)[0] + "/postgres"
MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent / "migrations"

# Tables we expect after the bootstrap migration so the summary at the
# end can give the operator a quick "yes, seeds landed" signal.
SEED_TABLES = ("departments", "emergency_triggers", "routing_rules")


async def ensure_database() -> bool:
    """Make sure the target DB exists. Returns True on success."""

    try:
        conn = await asyncpg.connect(DEFAULT_URL)
        await conn.close()
        return True
    except asyncpg.InvalidCatalogNameError:
        pass  # fall through to create
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


async def apply_migration(conn: asyncpg.Connection, path: pathlib.Path) -> str:
    """Apply a single SQL file. Returns a one-word status for the summary."""

    sql = path.read_text(encoding="utf-8")
    try:
        async with conn.transaction():
            await conn.execute(sql)
        return "applied"
    except asyncpg.DuplicateTableError:
        # First migration already ran; subsequent migrations would have
        # their own idempotency guards. Treat as a success.
        return "skipped (already applied)"
    except asyncpg.DuplicateObjectError:
        return "skipped (already applied)"


async def list_tables(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
        """
    )
    return [row["table_name"] for row in rows]


async def count_rows(conn: asyncpg.Connection, table: str) -> int | None:
    try:
        return await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
    except asyncpg.UndefinedTableError:
        return None


async def main() -> int:
    if not await ensure_database():
        return 1

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print(f"ERROR: no .sql files found in {MIGRATIONS_DIR}")
        return 2

    conn = await asyncpg.connect(DEFAULT_URL)
    try:
        print(f"Applying {len(migration_files)} migration file(s):")
        for path in migration_files:
            status = await apply_migration(conn, path)
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

    print("\nDB is ready. Start the API with: uv run uvicorn app.main:app --reload")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
