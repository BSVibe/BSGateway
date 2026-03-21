from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from bsgateway.api.deps import (
    AuthContext,
    get_auth_context,
    get_cache,
    get_encryption_key,
    get_pool,
)
from bsgateway.chat.ratelimit import RateLimiter
from bsgateway.chat.service import ChatError, ChatService
from bsgateway.tenant.repository import TenantRepository

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["chat"])


def _get_redis(request: Request) -> Any:
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


async def _check_rate_limit(
    request: Request,
    auth: AuthContext,
    pool: Any,
    redis: Any,
) -> JSONResponse | None:
    """Check per-tenant rate limit. Returns 429 response or None if allowed."""
    if not redis:
        return None

    cache = get_cache(request)
    tenant_repo = TenantRepository(pool, cache=cache)
    tenant_row = await tenant_repo.get_tenant(auth.tenant_id)
    if not tenant_row:
        return None

    raw_settings = tenant_row["settings"]
    tenant_settings = (
        json.loads(raw_settings) if isinstance(raw_settings, str) else (raw_settings or {})
    )
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

    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "message": "Rate limit exceeded",
                "type": "rate_limit_error",
                "param": None,
                "code": "rate_limit_exceeded",
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
    auth: AuthContext = Depends(get_auth_context),
) -> Any:
    """OpenAI-compatible chat completions with tenant-based routing."""
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

    pool = get_pool(request)
    encryption_key = get_encryption_key(request)
    redis = _get_redis(request)

    # Rate limiting
    rate_limit_resp = await _check_rate_limit(request, auth, pool, redis)
    if rate_limit_resp is not None:
        return rate_limit_resp

    bg_tasks: set = getattr(request.app.state, "background_tasks", set())
    svc = ChatService(pool, encryption_key, redis, background_tasks=bg_tasks)

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
                yield "data: [DONE]\n\n"
            except Exception as exc:
                logger.error("stream_error", error=str(exc), exc_info=True)
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
