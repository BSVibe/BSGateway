from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from bsgateway.core.database import execute_schema
from bsgateway.routing.collector import SqlLoader

if TYPE_CHECKING:
    import asyncpg

logger = structlog.get_logger(__name__)

_sql = SqlLoader()


class AuditRepository:
    """Database access layer for audit logs."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        """Create audit_logs table if it doesn't exist."""
        schema_path = Path(__file__).parent.parent / "routing" / "sql" / "audit_schema.sql"
        schema_sql = schema_path.read_text()
        await execute_schema(self._pool, schema_sql)
        logger.info("audit_schema_initialized")

    async def record(
        self,
        tenant_id: UUID,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
    ) -> asyncpg.Record:
        """Insert an audit log entry."""
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                _sql.query("insert_audit_log"),
                tenant_id,
                actor,
                action,
                resource_type,
                resource_id,
                json.dumps(details or {}),
            )

    async def list_by_tenant(
        self,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[asyncpg.Record]:
        """List audit logs for a tenant."""
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                _sql.query("list_audit_logs"),
                tenant_id,
                limit,
                offset,
            )

    async def count_by_tenant(self, tenant_id: UUID) -> int:
        """Count total audit logs for a tenant."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                _sql.query("count_audit_logs"),
                tenant_id,
            )
            return row["total"] if row else 0
