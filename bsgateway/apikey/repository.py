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


def split_sql_statements(sql: str) -> list[str]:
    """Split SQL script on statement semicolons, ignoring line-comment text."""
    statements: list[str] = []
    current: list[str] = []
    in_line_comment = False
    in_single_quote = False
    in_double_quote = False
    i = 0

    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""

        if in_line_comment:
            current.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if not in_single_quote and not in_double_quote and ch == "-" and nxt == "-":
            in_line_comment = True
            current.extend((ch, nxt))
            i += 2
            continue

        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(ch)
            i += 1
            continue

        if ch == ";" and not in_single_quote and not in_double_quote:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


class ApiKeyRepository:
    """Database access for API keys."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        schema = _sql.schema()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for statement in split_sql_statements(schema):
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
