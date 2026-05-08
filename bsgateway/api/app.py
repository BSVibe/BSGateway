from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

import structlog
from bsvibe_fastapi import add_cors_middleware, make_health_router
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from bsgateway.audit.repository import AuditRepository
from bsgateway.audit_publisher import build_audit_outbox
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
            from bsgateway.routing.cache_classifier import CachingClassifier
            from bsgateway.routing.hook import proxy_handler_instance

            proxy_handler_instance.attach_cache(app.state.cache)
            # Phase Audit Batch 2 — once the cache wrapper is in place,
            # plumb app.state through so sampled cache hits can emit
            # ``gateway.classifier.cache_hit``. Idempotent if the wrapping
            # was skipped (e.g. classifier strategy != static).
            classifier = getattr(proxy_handler_instance, "classifier", None)
            if isinstance(classifier, CachingClassifier):
                classifier.attach_audit_state(app.state)
        except Exception:
            logger.warning("classifier_cache_attach_failed", exc_info=True)

    # Phase 3 / TASK-004 — wire the per-tenant model registry into the
    # routing hook. The yaml side comes from the already-loaded routing
    # config; the DB side is read by ``ModelsRepository`` against the
    # ``models`` table created in alembic 0004. A 60s LRU bounds the
    # impact of a cold cache; admin mutations call ``invalidate`` so a
    # newly added model becomes routable without a process restart.
    try:
        from bsgateway.routing.hook import proxy_handler_instance
        from bsgateway.routing.models_repository import ModelsRepository
        from bsgateway.routing.registry import ModelRegistryService

        models_repo = ModelsRepository(pool)
        registry = ModelRegistryService(
            yaml_models=proxy_handler_instance.config.yaml_model_list,
            repo=models_repo,
        )
        proxy_handler_instance.attach_registry(registry)
        app.state.model_registry = registry
        logger.info(
            "model_registry_attached",
            yaml_count=len(proxy_handler_instance.config.yaml_model_list),
        )
    except Exception:
        logger.warning("model_registry_attach_failed", exc_info=True)
        app.state.model_registry = None

    # Phase 0 P0.7 — attach BSupervisor client so the LiteLLM proxy hook
    # can fire run.pre/run.post directly. We only attach when the
    # operator opts in (``bsupervisor_audit_enabled``) and the
    # service-account credential is provisioned.
    app.state.bsupervisor_client = None
    app.state.bsupervisor_token_minter = None
    if (
        settings.bsupervisor_audit_enabled
        and settings.bsupervisor_url
        and settings.bsvibe_client_id
        and settings.bsvibe_client_secret
    ):
        try:
            from bsgateway.routing.hook import proxy_handler_instance
            from bsgateway.supervisor import (
                BSupervisorClient,
                ServiceTokenMinter,
            )

            minter = ServiceTokenMinter(
                auth_url=settings.bsvibe_auth_url,
                client_id=settings.bsvibe_client_id,
                client_secret=settings.bsvibe_client_secret,
                audience="bsupervisor",
                scope=["bsupervisor.write"],
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

    # Phase Audit Batch 2 — bsvibe-audit outbox emitter + (optional) relay.
    # The emitter is the in-process contract: each gateway.* event goes
    # into the audit_outbox via SQLAlchemy. The relay drains the outbox
    # to BSVibe-Auth's `/api/audit/events`. Both default off — the
    # operator opts in via BSVIBE_AUDIT_OUTBOX_ENABLED + BSVIBE_AUTH_AUDIT_URL.
    emitter, audit_session_factory = build_audit_outbox(
        enabled=settings.bsvibe_audit_outbox_enabled,
        collector_database_url=settings.collector_database_url or "",
    )
    app.state.audit_emitter = emitter
    app.state.audit_outbox_session_factory = audit_session_factory
    app.state.audit_outbox_relay = None
    if emitter is not None and audit_session_factory is not None:
        try:
            from bsvibe_audit import AuditSettings, OutboxRelay

            audit_settings = AuditSettings()
            relay = OutboxRelay.from_settings(
                audit_settings,
                session_factory=audit_session_factory,
            )
            await relay.start()
            app.state.audit_outbox_relay = relay
            logger.info(
                "audit_outbox_relay_started",
                relay_enabled=audit_settings.relay_enabled,
            )
        except Exception:
            logger.warning("audit_outbox_relay_start_failed", exc_info=True)

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

    # Phase Audit Batch 2 — drain the OutboxRelay before tearing down the
    # SQLAlchemy engine. Failures here are best-effort: shutdown is more
    # important than draining the last few audit rows (the relay's own
    # retry on next boot will pick them up).
    relay = getattr(app.state, "audit_outbox_relay", None)
    if relay is not None:
        try:
            await relay.stop()
        except Exception:
            logger.warning("audit_outbox_relay_stop_failed", exc_info=True)

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

    # CORS — bsvibe_fastapi.add_cors_middleware honours
    # FastApiSettings.cors_allowed_origins (Annotated[list[str], NoDecode]
    # + parse_csv_list field_validator). When the deployer provides no
    # value the field falls back to FastApiSettings's default
    # (["http://localhost:3500"]); BSGateway prefers a port-aware
    # localhost so we keep the local override here.
    if settings.cors_allowed_origins == ["http://localhost:3500"]:
        # Default-only branch: emit the legacy warning and use a
        # port-aware origin so the dashboard still talks to the API.
        local_origin = f"http://localhost:{settings.api_port}"
        logger.warning(
            "cors_fallback_to_localhost",
            origins=[local_origin],
            hint="Set CORS_ALLOWED_ORIGINS for production",
        )
        add_cors_middleware(app, settings, allow_origins=[local_origin])
    else:
        add_cors_middleware(app, settings)

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
    app.include_router(mcp_router, prefix="/api/v1")
    app.include_router(execute_router, prefix="/api/v1")
    app.include_router(workers_router, prefix="/api/v1")

    # ─── Demo mode (separate deployment, BSVIBE_DEMO_MODE=true) ─────────
    # When the demo flag is set the backend exposes /api/v1/demo/session and
    # swaps the prod auth dep for a demo-JWT-aware one. Prod backends never
    # reach this branch.
    from bsgateway.demo.guard import is_demo_mode

    if is_demo_mode():
        from bsgateway.api.deps import get_auth_context
        from bsgateway.demo.auth import demo_auth_context
        from bsgateway.demo.router import demo_router

        app.include_router(demo_router, prefix="/api/v1")
        app.dependency_overrides[get_auth_context] = demo_auth_context
        logger.info("demo_mode_active", router="/api/v1/demo")

    # /health — shared liveness probe (always 200, no DI). Phase A Batch 5
    # adopts ``bsvibe_fastapi.make_health_router`` for parity across the
    # four products. ``/health/ready`` (deep readiness with DB+Redis
    # checks + per-dependency status keys) is BSGateway-specific and
    # stays inline — production probes already scrape its envelope.
    app.include_router(make_health_router())

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
