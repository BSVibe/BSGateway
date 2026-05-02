"""Run all schema migrations against the database.

.. deprecated:: Sprint 3 / S3-5

    Schema management has moved to Alembic. New deployments should run::

        uv run alembic upgrade head

    instead of ``python -m bsgateway.core.migrate``. The raw-SQL bootstrap
    here is kept as a fallback so existing CI / docker-compose flows that
    invoke it directly do not break in the same PR. Lockin decision #3
    governs the prod transition: stamp head once on the live DB, then use
    ``alembic upgrade head`` thereafter.

Usage:
    python -m bsgateway.core.migrate         # legacy path (still works)
    uv run alembic upgrade head              # canonical going forward
"""

from __future__ import annotations

import asyncio

import asyncpg
import structlog

from bsgateway.audit.repository import AuditRepository
from bsgateway.core.config import settings
from bsgateway.core.database import execute_schema
from bsgateway.presets.repository import FeedbackRepository
from bsgateway.routing.collector import SqlLoader
from bsgateway.rules.repository import RulesRepository
from bsgateway.tenant.repository import TenantRepository

logger = structlog.get_logger(__name__)


async def run_migrations() -> None:
    """Apply all schema migrations."""
    if not settings.collector_database_url:
        logger.error("database_url_not_configured")
        raise RuntimeError("collector_database_url is required")

    pool = await asyncpg.create_pool(settings.collector_database_url, min_size=1, max_size=2)
    try:
        # routing_logs must exist before tenant_schema (which ALTERs it)
        routing_sql = SqlLoader()
        await execute_schema(pool, routing_sql.schema())
        logger.info("schema_applied", schema="routing_logs")

        tenant_repo = TenantRepository(pool)
        await tenant_repo.init_schema()
        logger.info("schema_applied", schema="tenant")

        rules_repo = RulesRepository(pool)
        await rules_repo.init_schema()
        logger.info("schema_applied", schema="rules")

        feedback_repo = FeedbackRepository(pool)
        await feedback_repo.init_schema()
        logger.info("schema_applied", schema="feedback")

        audit_repo = AuditRepository(pool)
        await audit_repo.init_schema()
        logger.info("schema_applied", schema="audit")

        logger.info("all_migrations_completed")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
