"""Worker registration, heartbeat, polling, and result reporting."""

from __future__ import annotations

import hashlib
import io
import json
import secrets
import tarfile
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from bsgateway.api.deps import (
    GatewayAuthContext,
    get_auth_context,
    get_pool,
    require_permission,
)
from bsgateway.core.cache import cache_key_models
from bsgateway.core.utils import parse_jsonb_value
from bsgateway.executor.install_token import (
    generate_install_token,
    has_install_token,
    hash_install_token,
    resolve_install_token_tenant,
    set_install_token_hash,
)
from bsgateway.executor.sql_loader import ExecutorSqlLoader
from bsgateway.routing.collector import SqlLoader as RoutingSqlLoader
from bsgateway.streams import RedisStreamManager

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workers", tags=["workers"])
_sql = ExecutorSqlLoader()
_routing_sql = RoutingSqlLoader()

# Worker source lives next to the bsgateway package (./worker/)
_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKER_DIR = _REPO_ROOT / "worker"
_INSTALL_SCRIPT = _WORKER_DIR / "install.sh"
_cached_tarball: bytes | None = None


async def _invalidate_models_cache(request: Request, tenant_id: UUID) -> None:
    cache = getattr(request.app.state, "cache", None)
    if cache:
        await cache.delete(cache_key_models(str(tenant_id)))


# TODO: index `tenants.settings->>'worker_install_token_hash'` once tenant
# count grows — the install-token lookup (resolve_install_token_tenant)
# otherwise does a seq scan. Partial expression index:
#   CREATE INDEX tenants_worker_install_token_hash
#   ON tenants ((settings->>'worker_install_token_hash'))
#   WHERE settings ? 'worker_install_token_hash';


def _build_worker_tarball() -> bytes:
    """Build worker source tarball. Cached after first call."""
    global _cached_tarball
    if _cached_tarball is not None:
        return _cached_tarball

    pyproject = _WORKER_DIR / "pyproject.toml"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(str(pyproject), arcname="pyproject.toml")
        for f in _WORKER_DIR.rglob("*.py"):
            # skip __pycache__ etc.
            if "__pycache__" in f.parts:
                continue
            tar.add(str(f), arcname=f"worker/{f.relative_to(_WORKER_DIR)}")
    _cached_tarball = buf.getvalue()
    return _cached_tarball


def _request_origin(request: Request) -> str:
    """Resolve the backend-facing origin used by the installed worker.

    We want the installed worker to talk DIRECTLY to this backend, not through
    whatever frontend/CDN proxied the install.sh request. So prefer the real
    Host header over x-forwarded-host. (Vercel rewrites to an external URL
    set Host to the destination, so this works even when users curl the
    frontend domain.)
    """
    host = request.headers.get("host") or "localhost:8000"
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{host}"


@router.get("/install.sh", response_class=PlainTextResponse, include_in_schema=False)
async def get_install_script(request: Request) -> PlainTextResponse:
    """Serve the worker install script with server URL auto-injected."""
    if not _INSTALL_SCRIPT.is_file():
        raise HTTPException(status_code=404, detail="install.sh not found")
    origin = _request_origin(request)
    content = _INSTALL_SCRIPT.read_text().replace(
        'SERVER_URL="${BSGATEWAY_SERVER_URL:-}"',
        f'SERVER_URL="${{BSGATEWAY_SERVER_URL:-{origin}}}"',
    )
    return PlainTextResponse(content, media_type="text/plain")


@router.get("/source.tar.gz", include_in_schema=False)
async def get_worker_source() -> StreamingResponse:
    """Serve the worker source as a tarball for remote installation."""
    if not (_WORKER_DIR / "pyproject.toml").is_file():
        raise HTTPException(status_code=404, detail="Worker source not found")
    data = _build_worker_tarball()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/gzip",
        headers={"Content-Disposition": "attachment; filename=bsgateway-worker.tar.gz"},
    )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _get_streams(request: Request) -> RedisStreamManager:
    sm = getattr(request.app.state, "stream_manager", None)
    if sm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis not available for worker dispatch",
        )
    return sm


# ── Schemas ─────────────────────────────────────────────────────────


class WorkerRegisterBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    labels: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class WorkerRegisterResponse(BaseModel):
    id: UUID
    token: str


class WorkerTaskMessage(BaseModel):
    task_id: str
    executor_type: str
    prompt: str
    action: str = "execute"
    dispatched_at: str | None = None


class WorkerResultBody(BaseModel):
    task_id: UUID
    success: bool
    output: str = ""
    error_message: str | None = None


# ── Auth helper ─────────────────────────────────────────────────────


async def _auth_worker(request: Request) -> asyncpg.Record:
    """Authenticate a worker via X-Worker-Token header."""
    token = request.headers.get("X-Worker-Token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Missing X-Worker-Token")
    pool: asyncpg.Pool = get_pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_sql.query("get_worker_by_token"), _hash_token(token))
    if not row:
        raise HTTPException(status_code=401, detail="Invalid worker token")
    return row


# ── Endpoints ───────────────────────────────────────────────────────


class InstallTokenResponse(BaseModel):
    token: str | None = None  # plaintext only on create; never on GET
    has_token: bool = False


@router.get(
    "/install-token",
    response_model=InstallTokenResponse,
    summary="Check install token status",
)
async def get_install_token_status(
    request: Request,
    _allowed: None = Depends(require_permission("bsgateway.workers.read")),
    auth: GatewayAuthContext = Depends(get_auth_context),
) -> InstallTokenResponse:
    """Return whether an install token exists for this tenant."""
    pool = get_pool(request)
    exists = await has_install_token(pool, auth.tenant_id)
    return InstallTokenResponse(has_token=exists)


@router.post(
    "/install-token",
    response_model=InstallTokenResponse,
    summary="Generate install token",
)
async def create_install_token(
    request: Request,
    _allowed: None = Depends(require_permission("bsgateway.workers.write")),
    auth: GatewayAuthContext = Depends(get_auth_context),
) -> InstallTokenResponse:
    """Mint a new install token for this tenant (replaces any existing)."""
    pool = get_pool(request)
    token = generate_install_token()
    await set_install_token_hash(pool, auth.tenant_id, hash_install_token(token))
    logger.info("install_token_minted", tenant_id=str(auth.tenant_id))
    return InstallTokenResponse(token=token, has_token=True)


@router.delete(
    "/install-token",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke install token",
)
async def revoke_install_token(
    request: Request,
    _allowed: None = Depends(require_permission("bsgateway.workers.write")),
    auth: GatewayAuthContext = Depends(get_auth_context),
) -> None:
    pool = get_pool(request)
    await set_install_token_hash(pool, auth.tenant_id, None)
    logger.info("install_token_revoked", tenant_id=str(auth.tenant_id))


@router.post(
    "/register",
    response_model=WorkerRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a worker",
)
async def register_worker(
    body: WorkerRegisterBody,
    request: Request,
) -> WorkerRegisterResponse:
    """Register a new worker.

    Requires ``X-Install-Token`` header — admins mint one via
    ``POST /api/v1/workers/install-token`` and share it with worker machines.
    """
    install_token = request.headers.get("X-Install-Token", "")
    if not install_token:
        raise HTTPException(status_code=401, detail="Missing X-Install-Token header")

    pool = get_pool(request)
    tenant_id = await resolve_install_token_tenant(pool, install_token)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Invalid install token")

    token = secrets.token_urlsafe(32)
    capabilities = body.capabilities or ["claude_code"]

    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            _sql.query("create_worker"),
            tenant_id,
            body.name,
            json.dumps(body.labels),
            json.dumps(capabilities),
            _hash_token(token),
        )
        # Each registered capability becomes its own routable tenant_model
        # row, all pinned to this worker_id. Single-cap workers keep the
        # bare worker name (backwards compatible); multi-cap workers get a
        # ``{name} ({executor_type})`` suffix so they don't collide.
        for cap in capabilities:
            model_name = body.name if len(capabilities) == 1 else f"{body.name} ({cap})"
            await conn.fetchrow(
                _routing_sql.query("upsert_worker_model"),
                tenant_id,
                model_name,
                f"executor/{cap}",
                json.dumps({"worker_id": str(row["id"]), "executor_type": cap}),
            )

    await _invalidate_models_cache(request, tenant_id)

    logger.info(
        "worker_registered",
        worker_id=str(row["id"]),
        tenant_id=str(tenant_id),
        name=body.name,
    )
    return WorkerRegisterResponse(id=row["id"], token=token)


@router.post("/heartbeat", summary="Worker heartbeat")
async def heartbeat(request: Request) -> dict[str, str]:
    worker = await _auth_worker(request)
    pool = get_pool(request)
    async with pool.acquire() as conn:
        await conn.fetchrow(_sql.query("update_heartbeat"), worker["id"])
    return {"status": "ok"}


@router.post("/poll", summary="Poll for tasks")
async def poll_tasks(
    request: Request,
    count: int = 1,
) -> list[dict[str, Any]]:
    """Poll the worker's Redis stream for pending tasks."""
    worker = await _auth_worker(request)
    sm = _get_streams(request)

    stream_name = f"tasks:worker:{worker['id']}"
    group_name = f"worker-{worker['id']}"
    consumer = f"worker-{worker['id']}-0"

    messages = await sm.consume(stream_name, group_name, consumer, count=count)

    # Auto-ACK after delivery
    for msg in messages:
        mid = msg.pop("_message_id", None)
        if mid:
            await sm.acknowledge(stream_name, group_name, mid)

    return messages


@router.post("/result", summary="Report task result")
async def report_result(
    body: WorkerResultBody,
    request: Request,
) -> dict[str, str]:
    """Worker reports execution result for a task."""
    await _auth_worker(request)
    pool = get_pool(request)
    async with pool.acquire() as conn:
        await conn.fetchrow(
            _sql.query("update_task_result"),
            body.task_id,
            body.success,
            body.output,
            body.error_message,
        )
    logger.info("task_result_reported", task_id=str(body.task_id), success=body.success)
    return {"status": "ok"}


@router.get("", summary="List workers")
async def list_workers(
    request: Request,
    _allowed: None = Depends(require_permission("bsgateway.workers.read")),
    auth: GatewayAuthContext = Depends(get_auth_context),
) -> list[dict[str, Any]]:
    pool = get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(_sql.query("list_workers"), auth.tenant_id)
    result = []
    for r in rows:
        row = dict(r)
        for k in ("labels", "capabilities"):
            val = parse_jsonb_value(row.get(k))
            row[k] = val if isinstance(val, list) else []
        result.append(row)
    return result


@router.delete(
    "/{worker_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deregister a worker",
)
async def delete_worker(
    worker_id: UUID,
    request: Request,
    _allowed: None = Depends(require_permission("bsgateway.workers.write")),
    auth: GatewayAuthContext = Depends(get_auth_context),
) -> None:
    """Soft-delete a worker and drop its auto-registered tenant_models row."""
    pool = get_pool(request)
    async with pool.acquire() as conn:
        worker_row = await conn.fetchrow(
            "SELECT name FROM workers WHERE id = $1 AND tenant_id = $2",
            worker_id,
            auth.tenant_id,
        )
        if not worker_row:
            raise HTTPException(status_code=404, detail="Worker not found")

        async with conn.transaction():
            await conn.execute(_sql.query("deactivate_worker"), worker_id, auth.tenant_id)
            # Multi-capability workers register one tenant_models row per
            # capability (suffixed name). Drop them all by worker_id.
            await conn.execute(
                _routing_sql.query("delete_worker_models_by_worker_id"),
                auth.tenant_id,
                str(worker_id),
            )

    await _invalidate_models_cache(request, auth.tenant_id)

    logger.info("worker_deregistered", worker_id=str(worker_id), tenant_id=str(auth.tenant_id))
