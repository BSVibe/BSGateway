from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from bsgateway.audit.repository import AuditRepository
from bsgateway.core.cache import CacheManager
from bsgateway.core.config import settings
from bsgateway.core.database import close_pool, get_pool
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
        logger.error("redis_connection_failed", exc_info=True)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: DB pool creation and teardown."""
    if not settings.collector_database_url:
        logger.error("database_url_not_configured")
        raise RuntimeError("collector_database_url is required for the API server")

    # Validate encryption key early — fail fast on misconfiguration
    encryption_key = settings.encryption_key_bytes

    # Initialize BSVibe-Auth provider
    if not settings.supabase_url and not settings.supabase_jwt_secret:
        raise RuntimeError(
            "SUPABASE_URL (recommended) or SUPABASE_JWT_SECRET is required. "
            "Set SUPABASE_URL to your project URL (e.g. https://xxx.supabase.co)."
        )

    from bsvibe_auth import SupabaseAuthProvider

    app.state.auth_provider = SupabaseAuthProvider(
        supabase_url=settings.supabase_url or None,
        jwt_secret=settings.supabase_jwt_secret,
    )

    pool = await get_pool(settings.collector_database_url)
    app.state.db_pool = pool
    app.state.encryption_key = encryption_key

    # Global background task set for graceful shutdown tracking.
    # Tasks auto-remove themselves on completion via done callback.
    app.state.background_tasks: set[asyncio.Task] = set()

    # Initialize Redis (optional, used for rate limiting and caching)
    app.state.redis = await _init_redis()

    # Initialize cache manager if Redis is available
    app.state.cache = CacheManager(app.state.redis) if app.state.redis else None

    # Initialize schemas
    tenant_repo = TenantRepository(pool, cache=app.state.cache)
    await tenant_repo.init_schema()

    rules_repo = RulesRepository(pool, cache=app.state.cache)
    await rules_repo.init_schema()

    feedback_repo = FeedbackRepository(pool)
    await feedback_repo.init_schema()

    audit_repo = AuditRepository(pool)
    await audit_repo.init_schema()

    logger.info("api_server_started", port=settings.api_port)
    yield

    # Drain background tasks before closing connections
    if app.state.background_tasks:
        total = len(app.state.background_tasks)
        logger.info("draining_background_tasks", count=total)
        _done, _pending = await asyncio.wait(app.state.background_tasks, timeout=25.0)
        logger.info(
            "background_tasks_drained",
            completed=len(_done),
            timed_out=len(_pending),
        )
        for t in _pending:
            logger.warning("cancelling_background_task", task=t.get_name())
            t.cancel()

    # Cleanup Redis
    if app.state.redis:
        await app.state.redis.aclose()

    await close_pool()
    logger.info("api_server_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="BSGateway API",
        version="0.5.0",
        description=(
            "Multi-tenant LLM routing gateway with complexity-based model selection. "
            "Provides OpenAI-compatible chat completions, rule-based routing, "
            "usage analytics, and audit logging."
        ),
        lifespan=lifespan,
    )

    # CORS — configurable via CORS_ALLOWED_ORIGINS env var
    if settings.cors_allowed_origins:
        cors_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    else:
        cors_origins = [f"http://localhost:{settings.api_port}"]
        logger.warning(
            "cors_fallback_to_localhost",
            origins=cors_origins,
            hint="Set CORS_ALLOWED_ORIGINS for production",
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    from bsgateway.api.routers.audit import router as audit_router
    from bsgateway.api.routers.chat import router as chat_router
    from bsgateway.api.routers.feedback import router as feedback_router
    from bsgateway.api.routers.intents import router as intents_router
    from bsgateway.api.routers.presets import router as presets_router
    from bsgateway.api.routers.rules import router as rules_router
    from bsgateway.api.routers.tenants import router as tenants_router
    from bsgateway.api.routers.usage import router as usage_router

    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(tenants_router, prefix="/api/v1")
    app.include_router(rules_router, prefix="/api/v1")
    app.include_router(intents_router, prefix="/api/v1")
    app.include_router(presets_router, prefix="/api/v1")
    app.include_router(feedback_router, prefix="/api/v1")
    app.include_router(usage_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok"}

    # Serve frontend dashboard (only if build directory exists)
    if settings.frontend_dist_dir:
        frontend_dist = Path(settings.frontend_dist_dir)
    else:
        frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount(
            "/dashboard",
            StaticFiles(directory=str(frontend_dist), html=True),
            name="dashboard",
        )

    return app
