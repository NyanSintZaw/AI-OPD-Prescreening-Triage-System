from collections.abc import AsyncIterator
import json
import asyncpg
from fastapi import Request
from app.config import settings

async def create_pool() -> asyncpg.Pool:
    async def init_connection(connection: asyncpg.Connection) -> None:
        for type_name in ("json", "jsonb"):
            await connection.set_type_codec(
                type_name,
                encoder=json.dumps,
                decoder=json.loads,
                schema="pg_catalog",
            )

    return await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=10,
        init=init_connection,
    )

async def get_connection(request: Request) -> AsyncIterator[asyncpg.Connection]:
    pool: asyncpg.Pool = request.app.state.db_pool
    async with pool.acquire() as connection:
        yield connection

def record_to_dict(record: asyncpg.Record | None) -> dict | None:
    if record is None:
        return None
    return dict(record)

def records_to_dicts(records: list[asyncpg.Record]) -> list[dict]:
    return [dict(record) for record in records]