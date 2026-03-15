from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import asyncpg
import structlog

logger = structlog.get_logger(__name__)


class TenantSqlLoader:
    """Load named queries from tenant_queries.sql."""

    def __init__(self) -> None:
        self._sql_dir = Path(__file__).parent.parent / "routing" / "sql"
        self._queries: dict[str, str] = {}

    def schema(self) -> str:
        return (self._sql_dir / "tenant_schema.sql").read_text()

    def query(self, name: str) -> str:
        if not self._queries:
            self._parse_queries()
        return self._queries[name]

    def _parse_queries(self) -> None:
        content = (self._sql_dir / "tenant_queries.sql").read_text()
        current_name: str | None = None
        current_lines: list[str] = []
        for line in content.splitlines():
            if line.strip().startswith("-- name:"):
                if current_name:
                    self._queries[current_name] = "\n".join(current_lines).strip()
                current_name = line.strip().split("-- name:")[1].strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_name:
            self._queries[current_name] = "\n".join(current_lines).strip()


sql = TenantSqlLoader()


class TenantRepository:
    """Database access for tenants, API keys, and tenant models."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        schema = sql.schema()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for statement in schema.split(";"):
                    statement = statement.strip()
                    if statement:
                        await conn.execute(statement)

    # -- Tenants --

    async def create_tenant(
        self, name: str, slug: str, settings: dict | None = None,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("insert_tenant"),
                name, slug, json.dumps(settings or {}),
            )

    async def get_tenant(self, tenant_id: UUID) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql.query("get_tenant_by_id"), tenant_id)

    async def get_tenant_by_slug(self, slug: str) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql.query("get_tenant_by_slug"), slug)

    async def list_tenants(self, limit: int = 50, offset: int = 0) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql.query("list_tenants"), limit, offset)

    async def update_tenant(
        self, tenant_id: UUID, name: str, slug: str, settings: dict,
    ) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("update_tenant"),
                tenant_id, name, slug, json.dumps(settings),
            )

    async def deactivate_tenant(self, tenant_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(sql.query("deactivate_tenant"), tenant_id)

    # -- API Keys --

    async def create_api_key(
        self,
        tenant_id: UUID,
        key_hash: str,
        key_prefix: str,
        name: str = "",
        scopes: list[str] | None = None,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("insert_api_key"),
                tenant_id, key_hash, key_prefix, name, scopes or [],
            )

    async def get_api_key_by_hash(self, key_hash: str) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql.query("get_api_key_by_hash"), key_hash)

    async def list_api_keys(self, tenant_id: UUID) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql.query("list_api_keys"), tenant_id)

    async def revoke_api_key(self, key_id: UUID, tenant_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(sql.query("revoke_api_key"), key_id, tenant_id)

    async def touch_api_key(self, key_hash: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(sql.query("touch_api_key"), key_hash)

    # -- Tenant Models --

    async def create_model(
        self,
        tenant_id: UUID,
        model_name: str,
        provider: str,
        litellm_model: str,
        api_key_encrypted: str | None = None,
        api_base: str | None = None,
        extra_params: dict | None = None,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("insert_tenant_model"),
                tenant_id,
                model_name,
                provider,
                litellm_model,
                api_key_encrypted,
                api_base,
                json.dumps(extra_params or {}),
            )

    async def get_model(self, model_id: UUID, tenant_id: UUID) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql.query("get_tenant_model"), model_id, tenant_id)

    async def get_model_by_name(
        self, tenant_id: UUID, model_name: str,
    ) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("get_tenant_model_by_name"), tenant_id, model_name,
            )

    async def list_models(self, tenant_id: UUID) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql.query("list_tenant_models"), tenant_id)

    async def update_model(
        self,
        model_id: UUID,
        tenant_id: UUID,
        model_name: str,
        provider: str,
        litellm_model: str,
        api_key_encrypted: str | None,
        api_base: str | None,
        extra_params: dict,
    ) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("update_tenant_model"),
                model_id,
                tenant_id,
                model_name,
                provider,
                litellm_model,
                api_key_encrypted,
                api_base,
                json.dumps(extra_params),
            )

    async def delete_model(self, model_id: UUID, tenant_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(sql.query("delete_tenant_model"), model_id, tenant_id)
