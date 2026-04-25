from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from bsgateway.core.sql_loader import NamedSqlLoader

if TYPE_CHECKING:
    import asyncpg

logger = structlog.get_logger(__name__)

_sql = NamedSqlLoader("apikey_schema.sql", "apikey_queries.sql")


class ApiKeyRepository:
    """Database access for API keys."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        schema = _sql.schema()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for statement in schema.split(";"):
                    statement = statement.strip()
                    if statement:
                        await conn.execute(statement)

    async def create(
        self,
        tenant_id: UUID,
        name: str,
        key_hash: str,
        key_prefix: str,
        scopes: list[str],
        expires_at: datetime | None = None,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                _sql.query("insert_api_key"),
                tenant_id,
                name,
                key_hash,
                key_prefix,
                json.dumps(scopes),
                expires_at,
            )

    async def list_active_by_prefix(self, key_prefix: str) -> list[asyncpg.Record]:
        """Return active rows whose key_prefix matches.

        With salted PBKDF2 hashes we can no longer look up by ``key_hash``
        (each verify needs the per-row salt). The 12-char prefix is already
        indexed and almost always returns at most one row.
        """
        async with self._pool.acquire() as conn:
            return await conn.fetch(_sql.query("list_api_keys_by_prefix"), key_prefix)

    async def list_by_tenant(self, tenant_id: UUID) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(_sql.query("list_api_keys_by_tenant"), tenant_id)

    async def revoke(self, key_id: UUID, tenant_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(_sql.query("revoke_api_key"), key_id, tenant_id)

    async def touch_last_used(self, key_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(_sql.query("touch_last_used"), key_id)
