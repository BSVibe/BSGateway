"""Tenant-scoped repository for the ``routing_logs`` table.

Centralizes every read and write so that tenant isolation cannot be
bypassed by ad-hoc SQL — the ``tenant_id`` parameter is mandatory on
every method.

See `Docs/BSVibe_Ecosystem_Audit.md` §5.1 (C2) for the underlying
issue this layer prevents.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from bsgateway.routing.collector import SqlLoader

if TYPE_CHECKING:
    import asyncpg

logger = structlog.get_logger(__name__)

_sql = SqlLoader()


class RoutingLogsRepository:
    """All ``routing_logs`` access funnels through this object.

    Every public method takes ``tenant_id`` as the first parameter.
    Helpers that read aggregates always emit ``WHERE tenant_id = $1``.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # --- Writes -------------------------------------------------------

    async def insert_routing_log(
        self,
        *,
        tenant_id: UUID,
        rule_id: UUID | None,
        user_text: str,
        system_prompt: str,
        features: dict[str, Any],
        tier: str,
        strategy: str,
        score: int | None,
        original_model: str,
        resolved_model: str,
        embedding: bytes | None,
        nexus_task_type: str | None,
        nexus_priority: str | None,
        nexus_complexity_hint: int | None,
        decision_source: str | None,
    ) -> None:
        """Insert a routing decision row.

        ``tenant_id`` is required — there is intentionally no overload
        that allows logging without it.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                _sql.query("insert_routing_log"),
                tenant_id,
                rule_id,
                user_text,
                system_prompt,
                features["token_count"],
                features["conversation_turns"],
                features["code_block_count"],
                features["code_lines"],
                features["has_error_trace"],
                features["tool_count"],
                tier,
                strategy,
                score,
                original_model,
                resolved_model,
                embedding,
                nexus_task_type,
                nexus_priority,
                nexus_complexity_hint,
                decision_source,
            )

    # --- Aggregated reads --------------------------------------------

    async def usage_total(
        self,
        tenant_id: UUID,
        start: datetime,
        end: datetime,
    ) -> dict[str, int]:
        """Sum of requests + tokens for ``tenant_id`` in [start, end)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                _sql.query("usage_total"),
                tenant_id,
                start,
                end,
            )
        if not row:
            return {"total_requests": 0, "total_tokens": 0}
        return {
            "total_requests": row["total_requests"],
            "total_tokens": row["total_tokens"],
        }

    async def usage_by_model(
        self,
        tenant_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Per-day per-resolved-model request + token counts."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                _sql.query("usage_by_model"),
                tenant_id,
                start,
                end,
            )
        return [dict(row) for row in rows]

    async def usage_by_rule(
        self,
        tenant_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Per-rule request counts in window."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                _sql.query("usage_by_rule"),
                tenant_id,
                start,
                end,
            )
        return [dict(row) for row in rows]
