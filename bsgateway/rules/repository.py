from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from bsgateway.core.cache import CACHE_TTL_RULES, CacheManager, cache_key_rules
from bsgateway.core.exceptions import DuplicateError
from bsgateway.core.sql_loader import NamedSqlLoader

logger = structlog.get_logger(__name__)

sql = NamedSqlLoader("rules_schema.sql", "rules_queries.sql")


class RulesRepository:
    """Database access for routing rules, conditions, and intents with caching."""

    def __init__(self, pool: asyncpg.Pool, cache: CacheManager | None = None) -> None:
        self._pool = pool
        self._sql = sql
        self._cache = cache

    async def init_schema(self) -> None:
        schema = sql.schema()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for statement in schema.split(";"):
                    statement = statement.strip()
                    if statement:
                        await conn.execute(statement)

    # -- Rules --

    async def create_rule(
        self,
        tenant_id: UUID,
        name: str,
        priority: int,
        target_model: str,
        is_default: bool = False,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    sql.query("insert_rule"),
                    tenant_id,
                    name,
                    priority,
                    is_default,
                    target_model,
                )
            except asyncpg.UniqueViolationError as e:
                raise DuplicateError("Rule with this name or priority already exists") from e

        # Invalidate cache
        if self._cache:
            key = cache_key_rules(str(tenant_id))
            await self._cache.delete(key)

        return row

    async def get_rule(
        self,
        rule_id: UUID,
        tenant_id: UUID,
    ) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("get_rule"),
                rule_id,
                tenant_id,
            )

    async def list_rules(self, tenant_id: UUID) -> list[asyncpg.Record]:
        # Try cache first
        if self._cache:
            key = cache_key_rules(str(tenant_id))
            cached = await self._cache.get(key)
            if cached is not None:
                return [dict(row) for row in cached]

        # Fetch from DB
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql.query("list_rules"), tenant_id)

        # Cache result
        if self._cache and rows:
            key = cache_key_rules(str(tenant_id))
            await self._cache.set(key, [dict(row) for row in rows], CACHE_TTL_RULES)

        return rows

    async def update_rule(
        self,
        rule_id: UUID,
        tenant_id: UUID,
        name: str,
        priority: int,
        is_default: bool,
        target_model: str,
    ) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                sql.query("update_rule"),
                rule_id,
                tenant_id,
                name,
                priority,
                is_default,
                target_model,
            )

        # Invalidate cache
        if self._cache:
            key = cache_key_rules(str(tenant_id))
            await self._cache.delete(key)

        return row

    async def delete_rule(self, rule_id: UUID, tenant_id: UUID) -> bool:
        async with self._pool.acquire() as conn:
            status = await conn.execute(sql.query("delete_rule"), rule_id, tenant_id)

        deleted = status == "DELETE 1"
        # Invalidate cache
        if deleted and self._cache:
            key = cache_key_rules(str(tenant_id))
            await self._cache.delete(key)
        return deleted

    async def reorder_rules(
        self,
        tenant_id: UUID,
        priorities: dict[UUID, int],
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # UNIQUE(tenant_id, priority) is DEFERRABLE INITIALLY DEFERRED,
                # so constraint checks happen at commit, not per-statement.
                for rule_id, priority in priorities.items():
                    await conn.execute(
                        sql.query("update_rule_priority"),
                        rule_id,
                        tenant_id,
                        priority,
                    )

        # Invalidate cache
        if self._cache:
            key = cache_key_rules(str(tenant_id))
            await self._cache.delete(key)

    # -- Conditions --

    async def create_condition(
        self,
        rule_id: UUID,
        condition_type: str,
        operator: str,
        field: str,
        value: Any,
        negate: bool = False,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("insert_condition"),
                rule_id,
                condition_type,
                operator,
                field,
                json.dumps(value),
                negate,
            )

    async def list_conditions(self, rule_id: UUID) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql.query("list_conditions"), rule_id)

    async def replace_conditions(
        self,
        rule_id: UUID,
        conditions: list[dict],
    ) -> list[asyncpg.Record]:
        """Delete all conditions for a rule and insert new ones."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    sql.query("delete_conditions_for_rule"),
                    rule_id,
                )
                results = []
                for c in conditions:
                    row = await conn.fetchrow(
                        sql.query("insert_condition"),
                        rule_id,
                        c["condition_type"],
                        c.get("operator", "eq"),
                        c["field"],
                        json.dumps(c["value"]),
                        c.get("negate", False),
                    )
                    results.append(row)
                return results

    async def list_conditions_for_tenant(
        self,
        tenant_id: UUID,
    ) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                sql.query("list_conditions_for_tenant"),
                tenant_id,
            )

    # -- Intents --

    async def create_intent(
        self,
        tenant_id: UUID,
        name: str,
        description: str = "",
        threshold: float = 0.7,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("insert_intent"),
                tenant_id,
                name,
                description,
                threshold,
            )

    async def get_intent(
        self,
        intent_id: UUID,
        tenant_id: UUID,
    ) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("get_intent"),
                intent_id,
                tenant_id,
            )

    async def list_intents(self, tenant_id: UUID) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql.query("list_intents"), tenant_id)

    async def update_intent(
        self,
        intent_id: UUID,
        tenant_id: UUID,
        name: str,
        description: str,
        threshold: float,
    ) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("update_intent"),
                intent_id,
                tenant_id,
                name,
                description,
                threshold,
            )

    async def delete_intent(
        self,
        intent_id: UUID,
        tenant_id: UUID,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql.query("delete_intent"),
                intent_id,
                tenant_id,
            )

    # -- Intent Examples --

    async def add_example(
        self,
        intent_id: UUID,
        text: str,
        embedding: bytes | None = None,
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("insert_intent_example"),
                intent_id,
                text,
                embedding,
            )

    async def list_examples(
        self,
        intent_id: UUID,
    ) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                sql.query("list_intent_examples"),
                intent_id,
            )

    async def delete_example(
        self,
        example_id: UUID,
        intent_id: UUID,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql.query("delete_intent_example"),
                example_id,
                intent_id,
            )

    async def list_examples_for_tenant(
        self,
        tenant_id: UUID,
    ) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                sql.query("list_intent_examples_for_tenant"),
                tenant_id,
            )
