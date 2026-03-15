from __future__ import annotations

from pathlib import Path
from uuid import UUID

import asyncpg
import structlog

logger = structlog.get_logger(__name__)


class FeedbackSqlLoader:
    """Load named queries from feedback_queries.sql."""

    def __init__(self) -> None:
        self._sql_dir = Path(__file__).parent.parent / "routing" / "sql"
        self._queries: dict[str, str] = {}

    def schema(self) -> str:
        return (self._sql_dir / "feedback_schema.sql").read_text()

    def query(self, name: str) -> str:
        if not self._queries:
            self._parse_queries()
        return self._queries[name]

    def _parse_queries(self) -> None:
        content = (self._sql_dir / "feedback_queries.sql").read_text()
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


sql = FeedbackSqlLoader()


class FeedbackRepository:
    """Database access for routing feedback."""

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

    async def create_feedback(
        self,
        tenant_id: UUID,
        routing_id: str,
        rating: int,
        comment: str = "",
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("insert_feedback"),
                tenant_id, routing_id, rating, comment,
            )

    async def list_feedback(
        self,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                sql.query("list_feedback"), tenant_id, limit, offset,
            )

    async def get_stats(self, tenant_id: UUID) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                sql.query("get_feedback_stats"), tenant_id,
            )
