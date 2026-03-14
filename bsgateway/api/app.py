from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from bsgateway.core.config import settings
from bsgateway.core.database import close_pool, get_pool
from bsgateway.tenant.repository import TenantRepository

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: DB pool creation and teardown."""
    if not settings.collector_database_url:
        logger.error("database_url_not_configured")
        raise RuntimeError("collector_database_url is required for the API server")

    pool = await get_pool(settings.collector_database_url)
    app.state.db_pool = pool
    app.state.encryption_key = settings.encryption_key_bytes
    app.state.superadmin_key = settings.superadmin_key

    # Initialize tenant schema
    repo = TenantRepository(pool)
    await repo.init_schema()

    logger.info("api_server_started", port=settings.api_port)
    yield

    await close_pool()
    logger.info("api_server_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="BSGateway API",
        version="0.1.0",
        description="Multi-tenant LLM routing gateway",
        lifespan=lifespan,
    )

    from bsgateway.api.routers.intents import router as intents_router
    from bsgateway.api.routers.presets import router as presets_router
    from bsgateway.api.routers.rules import router as rules_router
    from bsgateway.api.routers.tenants import router as tenants_router

    app.include_router(tenants_router, prefix="/api/v1")
    app.include_router(rules_router, prefix="/api/v1")
    app.include_router(intents_router, prefix="/api/v1")
    app.include_router(presets_router, prefix="/api/v1")

    return app
