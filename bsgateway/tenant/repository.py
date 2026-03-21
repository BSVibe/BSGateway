from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import asyncpg
import structlog

from bsgateway.core.cache import (
    CACHE_TTL_API_KEYS,
    CACHE_TTL_MODELS,
    CACHE_TTL_TENANTS,
    CacheManager,
    cache_key_api_keys,
    cache_key_models,
    cache_key_tenants,
)
from bsgateway.core.exceptions import DuplicateError

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
    """Database access for tenants, API keys, and tenant models with caching."""

    def __init__(self, pool: asyncpg.Pool, cache: CacheManager | None = None) -> None:
        self._pool = pool
        self._cache = cache

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
        self,
        name: str,
        slug: str,
        settings: dict | None = None,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    sql.query("insert_tenant"),
                    name,
                    slug,
                    json.dumps(settings or {}),
                )
            except asyncpg.UniqueViolationError as e:
                detail = e.as_dict().get("detail", str(e))
                raise DuplicateError(
                    f"Tenant with this name or slug already exists: {detail}"
                ) from e

        if self._cache:
            await self._cache.delete(cache_key_tenants())

        return row

    async def get_tenant(self, tenant_id: UUID) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql.query("get_tenant_by_id"), tenant_id)

    async def get_tenant_by_slug(self, slug: str) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql.query("get_tenant_by_slug"), slug)

    async def list_tenants(self, limit: int = 50, offset: int = 0) -> list[asyncpg.Record]:
        if self._cache:
            key = cache_key_tenants()
            cached = await self._cache.get(key)
            if cached is not None:
                return [dict(row) for row in cached]

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql.query("list_tenants"), limit, offset)

        if self._cache and rows:
            key = cache_key_tenants()
            await self._cache.set(key, [dict(row) for row in rows], CACHE_TTL_TENANTS)

        return rows

    async def update_tenant(
        self,
        tenant_id: UUID,
        name: str,
        slug: str,
        settings: dict,
    ) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                sql.query("update_tenant"),
                tenant_id,
                name,
                slug,
                json.dumps(settings),
            )

        if self._cache:
            await self._cache.delete(cache_key_tenants())

        return row

    async def deactivate_tenant(self, tenant_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(sql.query("deactivate_tenant"), tenant_id)

        if self._cache:
            await self._cache.delete(cache_key_tenants())

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
            row = await conn.fetchrow(
                sql.query("insert_api_key"),
                tenant_id,
                key_hash,
                key_prefix,
                name,
                scopes or [],
            )

        if self._cache:
            await self._cache.delete(cache_key_api_keys(str(tenant_id)))

        return row

    async def get_api_key_by_hash(self, key_hash: str) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql.query("get_api_key_by_hash"), key_hash)

    async def list_api_keys(self, tenant_id: UUID) -> list[asyncpg.Record]:
        if self._cache:
            key = cache_key_api_keys(str(tenant_id))
            cached = await self._cache.get(key)
            if cached is not None:
                return [dict(row) for row in cached]

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql.query("list_api_keys"), tenant_id)

        if self._cache and rows:
            key = cache_key_api_keys(str(tenant_id))
            await self._cache.set(key, [dict(row) for row in rows], CACHE_TTL_API_KEYS)

        return rows

    async def revoke_api_key(self, key_id: UUID, tenant_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(sql.query("revoke_api_key"), key_id, tenant_id)

        if self._cache:
            await self._cache.delete(cache_key_api_keys(str(tenant_id)))

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
        # Invalidate cache before returning to prevent stale reads
        cache_k = cache_key_models(str(tenant_id)) if self._cache else None

        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    sql.query("insert_tenant_model"),
                    tenant_id,
                    model_name,
                    provider,
                    litellm_model,
                    api_key_encrypted,
                    api_base,
                    json.dumps(extra_params or {}),
                )
            except asyncpg.UniqueViolationError as e:
                raise DuplicateError(f"Model '{model_name}' already exists for this tenant") from e

        if self._cache and cache_k:
            await self._cache.delete(cache_k)

        return row

    async def get_model(self, model_id: UUID, tenant_id: UUID) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql.query("get_tenant_model"), model_id, tenant_id)

    async def get_model_by_name(
        self,
        tenant_id: UUID,
        model_name: str,
    ) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("get_tenant_model_by_name"),
                tenant_id,
                model_name,
            )

    async def list_models(self, tenant_id: UUID) -> list[asyncpg.Record]:
        # Try cache first
        if self._cache:
            key = cache_key_models(str(tenant_id))
            cached = await self._cache.get(key)
            if cached is not None:
                return [dict(row) for row in cached]

        # Fetch from DB
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql.query("list_tenant_models"), tenant_id)

        # Cache result
        if self._cache and rows:
            key = cache_key_models(str(tenant_id))
            await self._cache.set(key, [dict(row) for row in rows], CACHE_TTL_MODELS)

        return rows

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
            row = await conn.fetchrow(
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

        if self._cache:
            await self._cache.delete(cache_key_models(str(tenant_id)))

        return row

    async def delete_model(self, model_id: UUID, tenant_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(sql.query("delete_tenant_model"), model_id, tenant_id)

        if self._cache:
            await self._cache.delete(cache_key_models(str(tenant_id)))
