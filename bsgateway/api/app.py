from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bsgateway.audit.repository import AuditRepository
from bsgateway.core.config import settings
from bsgateway.core.database import close_pool, get_pool
from bsgateway.core.security import hash_api_key
from bsgateway.presets.repository import FeedbackRepository
from bsgateway.rules.repository import RulesRepository
from bsgateway.tenant.repository import TenantRepository

logger = structlog.get_logger(__name__)


async def _init_redis() -> Redis | None:
    """Create a Redis client if configured, otherwise return None."""
    if not settings.redis_host:
        return None
    try:
        from redis.asyncio import Redis

        client = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            decode_responses=False,
        )
        await client.ping()  # type: ignore[misc]
        logger.info("redis_connected", host=settings.redis_host, port=settings.redis_port)
        return client
    except Exception:
        logger.warning("redis_connection_failed", exc_info=True)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: DB pool creation and teardown."""
    if not settings.collector_database_url:
        logger.error("database_url_not_configured")
        raise RuntimeError("collector_database_url is required for the API server")

    pool = await get_pool(settings.collector_database_url)
    app.state.db_pool = pool
    app.state.encryption_key = settings.encryption_key_bytes
    app.state.superadmin_key_hash = (
        hash_api_key(settings.superadmin_key) if settings.superadmin_key else ""
    )
    app.state.jwt_secret = settings.jwt_secret

    # Initialize schemas
    tenant_repo = TenantRepository(pool)
    await tenant_repo.init_schema()

    rules_repo = RulesRepository(pool)
    await rules_repo.init_schema()

    feedback_repo = FeedbackRepository(pool)
    await feedback_repo.init_schema()

    audit_repo = AuditRepository(pool)
    await audit_repo.init_schema()

    # Seed development data (if enabled)
    if settings.seed_dev_data:
        from bsgateway.core.seed import seed_dev_data

        await seed_dev_data(pool, settings.encryption_key_bytes)

    # Initialize Redis (optional, used for rate limiting and budget tracking)
    app.state.redis = await _init_redis()

    logger.info("api_server_started", port=settings.api_port)
    yield

    # Cleanup Redis
    if app.state.redis:
        await app.state.redis.aclose()

    await close_pool()
    logger.info("api_server_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="BSGateway API",
        version="0.4.0",
        description=(
            "Multi-tenant LLM routing gateway with complexity-based model selection. "
            "Provides OpenAI-compatible chat completions, rule-based routing, "
            "usage analytics, and audit logging."
        ),
        lifespan=lifespan,
    )

    from bsgateway.api.routers.audit import router as audit_router
    from bsgateway.api.routers.auth import router as auth_router
    from bsgateway.api.routers.chat import router as chat_router
    from bsgateway.api.routers.feedback import router as feedback_router
    from bsgateway.api.routers.intents import router as intents_router
    from bsgateway.api.routers.presets import router as presets_router
    from bsgateway.api.routers.rules import router as rules_router
    from bsgateway.api.routers.tenants import router as tenants_router
    from bsgateway.api.routers.usage import router as usage_router

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(tenants_router, prefix="/api/v1")
    app.include_router(rules_router, prefix="/api/v1")
    app.include_router(intents_router, prefix="/api/v1")
    app.include_router(presets_router, prefix="/api/v1")
    app.include_router(feedback_router, prefix="/api/v1")
    app.include_router(usage_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")

    # Serve frontend dashboard (only if build directory exists)
    frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount(
            "/dashboard",
            StaticFiles(directory=str(frontend_dist), html=True),
            name="dashboard",
        )

    return app
