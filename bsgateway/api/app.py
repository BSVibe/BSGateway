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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from bsgateway.audit.repository import AuditRepository
from bsgateway.core.cache import CacheManager
from bsgateway.core.config import settings
from bsgateway.core.database import close_pool, execute_schema, get_pool
from bsgateway.presets.repository import FeedbackRepository
from bsgateway.routing.collector import SqlLoader
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
    from bsvibe_auth import BsvibeAuthProvider

    app.state.auth_provider = BsvibeAuthProvider(auth_url=settings.bsvibe_auth_url)

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

    # Sprint 3 / S3-3: wire the Redis cache into the LiteLLM proxy router so
    # the static classifier's deterministic keyword scan gets memoised. The
    # router instance is created at module import (before lifespan), so we
    # patch in the cache after CacheManager is constructed.
    if app.state.cache is not None:
        try:
            from bsgateway.routing.hook import proxy_handler_instance

            proxy_handler_instance.attach_cache(app.state.cache)
        except Exception:
            logger.warning("classifier_cache_attach_failed", exc_info=True)

    # Phase 0 P0.7 — attach BSupervisor client so the LiteLLM proxy hook
    # can fire run.pre/run.post directly. We only attach when the
    # operator opts in (``bsupervisor_audit_enabled``) and the
    # service-account credential is provisioned.
    app.state.bsupervisor_client = None
    app.state.bsupervisor_token_minter = None
    if (
        settings.bsupervisor_audit_enabled
        and settings.bsupervisor_url
        and settings.bsvibe_service_account_token
        and settings.bsvibe_service_account_tenant_id
    ):
        try:
            from bsgateway.routing.hook import proxy_handler_instance
            from bsgateway.supervisor import (
                BSupervisorClient,
                ServiceTokenMinter,
            )

            minter = ServiceTokenMinter(
                auth_url=settings.bsvibe_auth_url,
                service_account_token=settings.bsvibe_service_account_token,
                service_account_tenant_id=settings.bsvibe_service_account_tenant_id,
                audience="bsupervisor",
                scope=["bsupervisor.events"],
            )
            client = BSupervisorClient(
                base_url=settings.bsupervisor_url,
                token_minter=minter,
                timeout_ms=settings.bsupervisor_audit_timeout_ms,
                fail_mode=settings.bsupervisor_audit_fail_mode,
            )
            proxy_handler_instance.attach_supervisor(client)
            app.state.bsupervisor_client = client
            app.state.bsupervisor_token_minter = minter
            logger.info(
                "bsupervisor_attached",
                fail_mode=settings.bsupervisor_audit_fail_mode,
                timeout_ms=settings.bsupervisor_audit_timeout_ms,
            )
        except Exception:
            logger.warning("bsupervisor_attach_failed", exc_info=True)
    else:
        logger.info(
            "bsupervisor_disabled",
            reason="bsupervisor_audit_enabled=False or credentials missing",
        )

    # Initialize schemas — routing_logs must exist first (tenant_schema ALTERs it)
    routing_sql = SqlLoader()
    await execute_schema(pool, routing_sql.schema())

    tenant_repo = TenantRepository(pool, cache=app.state.cache)
    await tenant_repo.init_schema()

    rules_repo = RulesRepository(pool, cache=app.state.cache)
    await rules_repo.init_schema()

    feedback_repo = FeedbackRepository(pool)
    await feedback_repo.init_schema()

    audit_repo = AuditRepository(pool)
    await audit_repo.init_schema()

    from bsgateway.apikey.repository import ApiKeyRepository

    apikey_repo = ApiKeyRepository(pool)
    await apikey_repo.init_schema()

    # Executor schema (workers + executor_tasks)
    from bsgateway.executor.sql_loader import ExecutorSqlLoader

    executor_sql = ExecutorSqlLoader()
    await execute_schema(pool, executor_sql.schema())

    # Initialize RedisStreamManager if Redis is available
    if app.state.redis:
        from bsgateway.streams import RedisStreamManager

        app.state.stream_manager = RedisStreamManager(app.state.redis)
    else:
        app.state.stream_manager = None

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

    # Close the BSGateway router (drains its own background tasks +
    # closes the RoutingCollector pool — audit issue H15). The router is
    # constructed at module import time as a side effect of importing
    # bsgateway.routing.hook so we resolve it lazily here.
    try:
        from bsgateway.routing.hook import proxy_handler_instance

        await proxy_handler_instance.aclose()
    except Exception:
        logger.warning("router_aclose_failed", exc_info=True)

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

    from bsgateway.api.routers.apikeys import router as apikeys_router
    from bsgateway.api.routers.audit import router as audit_router
    from bsgateway.api.routers.chat import router as chat_router
    from bsgateway.api.routers.execute import router as execute_router
    from bsgateway.api.routers.feedback import router as feedback_router
    from bsgateway.api.routers.intents import router as intents_router
    from bsgateway.api.routers.presets import router as presets_router
    from bsgateway.api.routers.rules import router as rules_router
    from bsgateway.api.routers.tenants import router as tenants_router
    from bsgateway.api.routers.usage import router as usage_router
    from bsgateway.api.routers.workers import router as workers_router
    from bsgateway.mcp.router import router as mcp_router

    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(tenants_router, prefix="/api/v1")
    app.include_router(rules_router, prefix="/api/v1")
    app.include_router(intents_router, prefix="/api/v1")
    app.include_router(presets_router, prefix="/api/v1")
    app.include_router(feedback_router, prefix="/api/v1")
    app.include_router(usage_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    app.include_router(apikeys_router, prefix="/api/v1")
    app.include_router(mcp_router, prefix="/api/v1")
    app.include_router(execute_router, prefix="/api/v1")
    app.include_router(workers_router, prefix="/api/v1")

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def health_ready() -> JSONResponse:
        """Deep health check: verify database and Redis connectivity."""
        checks: dict[str, str] = {}
        all_ok = True

        # Check PostgreSQL
        try:
            pool = app.state.db_pool
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            checks["database"] = "ok"
        except Exception as exc:
            logger.error("health_check_database_failed", error=str(exc))
            checks["database"] = f"error: {exc}"
            all_ok = False

        # Check Redis
        try:
            redis = app.state.redis
            if redis is None:
                checks["redis"] = "not_configured"
            else:
                await redis.ping()
                checks["redis"] = "ok"
        except Exception as exc:
            logger.error("health_check_redis_failed", error=str(exc))
            checks["redis"] = f"error: {exc}"
            all_ok = False

        status_code = 200 if all_ok else 503
        return JSONResponse(
            content={"status": "ready" if all_ok else "unavailable", **checks},
            status_code=status_code,
        )

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
