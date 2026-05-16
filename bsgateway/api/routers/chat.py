from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

import asyncpg
import structlog
from bsvibe_audit.events.base import AuditActor, AuditEventBase
from bsvibe_audit.events.gateway import RateLimitViolated
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from bsgateway.api.deps import (
    GatewayAuthContext,
    get_auth_context,
    get_cache,
    get_encryption_key,
    get_pool,
)
from bsgateway.audit_publisher import emit_event
from bsgateway.chat.ratelimit import RateLimiter, RateLimitResult
from bsgateway.chat.service import ChatError, ChatService
from bsgateway.core.utils import safe_json_loads
from bsgateway.tenant.repository import TenantRepository

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["chat"])


class ChatMessage(BaseModel):
    """Validates individual chat message structure."""

    role: str = Field(..., min_length=1, max_length=50)
    content: str | list | None = None


def _get_redis(request: Request) -> Redis | None:
    """Extract optional Redis client from app state."""
    return getattr(request.app.state, "redis", None)


def _error_response(
    status_code: int,
    message: str,
    error_type: str,
    code: str | None = None,
) -> JSONResponse:
    """Return an OpenAI-compatible error response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": None,
                "code": code,
            }
        },
    )


async def _maybe_emit_rate_limit_violation(
    app_state: object,
    *,
    tenant_id: UUID,
    actor_id: str,
    actor_email: str | None,
    result: RateLimitResult,
    emit_fn: Callable[[object, AuditEventBase], Awaitable[None]] = emit_event,
) -> None:
    """Emit ``gateway.rate_limit.violated`` only on Sprint 1 H1 fail-closed.

    Normal quota exhaustion (Redis up, count > rpm) is high-volume and
    expected behaviour — emitting on every 429 would drown the audit
    pipeline. Fail-closed is the rare-and-actionable case the audit
    timeline exists to capture: Redis outage caused requests to be
    denied that would otherwise have been allowed.

    ``emit_fn`` is parameterised so unit tests can verify the
    fail-closed-only contract without spinning up the full emitter.
    """
    if not result.degraded:
        return
    await emit_fn(
        app_state,
        RateLimitViolated(
            actor=AuditActor(type="user", id=actor_id, email=actor_email),
            tenant_id=str(tenant_id),
            data={
                "limit": result.limit,
                "remaining": result.remaining,
                "reset_at": result.reset_at,
                "degraded": True,
                "reason": "redis_unavailable_fail_closed",
            },
        ),
    )


async def _check_rate_limit(
    request: Request,
    auth: GatewayAuthContext,
    pool: asyncpg.Pool,
    redis: Redis | None,
) -> JSONResponse | None:
    """Check per-tenant rate limit. Returns 429 response or None if allowed."""
    if not redis:
        return None

    cache = get_cache(request)
    tenant_repo = TenantRepository(pool, cache=cache)
    tenant_row = await tenant_repo.get_tenant(auth.tenant_id)
    if not tenant_row:
        return None

    tenant_settings = safe_json_loads(tenant_row["settings"])
    rate_limit = tenant_settings.get("rate_limit", {})
    try:
        rpm = int(rate_limit.get("requests_per_minute", 0))
    except (TypeError, ValueError):
        rpm = 0
    if not (0 <= rpm <= 100_000):
        rpm = 0
    if rpm <= 0:
        return None

    limiter = RateLimiter(redis)
    result = await limiter.check(str(auth.tenant_id), rpm)
    if result.allowed:
        return None

    # Phase Audit Batch 2 — emit gateway.rate_limit.violated only on
    # fail-closed (Sprint 1 H1) so audit timeline captures Redis-outage-
    # induced denials but not normal quota exhaustion.
    await _maybe_emit_rate_limit_violation(
        request.app.state,
        tenant_id=auth.tenant_id,
        actor_id=str(auth.identity.id),
        actor_email=auth.identity.email,
        result=result,
    )

    # Distinguish actual quota exhaustion from fail-closed (Redis outage).
    # Both surface as 429 to keep clients on the existing retry/back-off
    # path, but operators get a separate code for alerting.
    code = "rate_limit_unavailable" if result.degraded else "rate_limit_exceeded"
    message = "Rate limiter temporarily unavailable" if result.degraded else "Rate limit exceeded"
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "message": message,
                "type": "rate_limit_error",
                "param": None,
                "code": code,
            }
        },
        headers={
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": str(result.remaining),
            "X-RateLimit-Reset": str(result.reset_at),
        },
    )


@router.post(
    "/chat/completions",
    summary="Chat completions",
    responses={
        401: {"description": "Invalid or expired API key"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "Upstream provider error"},
    },
)
async def chat_completions(
    request: Request,
    auth: GatewayAuthContext = Depends(get_auth_context),
) -> Any:
    """OpenAI-compatible chat completions with tenant-based routing.

    DATA-PLANE: this is the gateway's core function. Deliberately gated
    only by tenant-scoped authentication (``get_auth_context``) — NOT by
    a per-resource ``require_permission`` check. Any authenticated tenant
    member may send completions; per-resource gating belongs on the
    control-plane (model registry, routing rules), not the dispatch path.
    """
    try:
        body = await request.json()
    except Exception:
        return _error_response(
            400, "Invalid JSON in request body", "invalid_request_error", "invalid_json"
        )

    # Validate messages
    if "messages" not in body or not body["messages"]:
        return _error_response(
            400,
            "messages is required and must be non-empty",
            "invalid_request_error",
            "invalid_messages",
        )

    # Validate each message has required 'role' field
    for i, msg in enumerate(body["messages"]):
        if not isinstance(msg, dict) or "role" not in msg:
            return _error_response(
                400,
                f"messages[{i}] must be an object with a 'role' field",
                "invalid_request_error",
                "invalid_messages",
            )

    pool = get_pool(request)
    encryption_key = get_encryption_key(request)
    redis = _get_redis(request)

    # Rate limiting
    rate_limit_resp = await _check_rate_limit(request, auth, pool, redis)
    if rate_limit_resp is not None:
        return rate_limit_resp

    bg_tasks: set = getattr(request.app.state, "background_tasks", set())
    svc = ChatService(
        pool,
        encryption_key,
        redis,
        background_tasks=bg_tasks,
        supervisor=getattr(request.app.state, "bsupervisor_client", None),
    )

    try:
        response = await svc.complete(auth.tenant_id, body)
    except ChatError as e:
        return _error_response(e.status_code, str(e), "invalid_request_error", e.code)
    except Exception as e:
        logger.error("chat_completion_failed", error=str(e), exc_info=True)
        return _error_response(502, "Upstream provider error", "upstream_error")

    # Streaming response
    if body.get("stream"):

        async def event_stream() -> AsyncGenerator[str, None]:
            try:
                async for chunk in response:
                    data = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
                    yield f"data: {json.dumps(data)}\n\n"
            except Exception as exc:
                logger.error("stream_error", error=str(exc), exc_info=True)
                # Send error as final event before closing the stream.
                # Clients should treat any error event before [DONE] as terminal.
                error_data = {
                    "error": {
                        "message": "Stream interrupted",
                        "type": "upstream_error",
                        "param": None,
                        "code": "stream_error",
                    }
                }
                yield f"data: {json.dumps(error_data)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming response
    if hasattr(response, "model_dump"):
        return response.model_dump()
    return response
