"""One-off DB readiness check. Safe to delete after demo setup."""

import asyncio
import os
import sys

import asyncpg


DEFAULT_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5433/hospital_hotline",
)
SUPER_URL = DEFAULT_URL.rsplit("/", 1)[0] + "/postgres"


async def ensure_database() -> bool:
    try:
        conn = await asyncpg.connect(DEFAULT_URL)
        await conn.close()
        return True
    except asyncpg.InvalidCatalogNameError:
        pass
    except Exception as exc:
        print(f"Cannot reach Postgres at {DEFAULT_URL}: {exc}")
        return False

    print("Database hospital_hotline does not exist. Creating it...")
    super_conn = await asyncpg.connect(SUPER_URL)
    await super_conn.execute("CREATE DATABASE hospital_hotline")
    await super_conn.close()
    return True


async def list_tables() -> list[str]:
    conn = await asyncpg.connect(DEFAULT_URL)
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
    )
    await conn.close()
    return [row["table_name"] for row in rows]


async def main() -> int:
    if not await ensure_database():
        return 1
    tables = await list_tables()
    if not tables:
        print("EMPTY: schema not applied")
        return 2
    print("OK: tables present:")
    for name in tables:
        print(" -", name)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
