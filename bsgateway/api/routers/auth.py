"""Authentication endpoints for the dashboard."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from bsgateway.core.security import create_jwt, hash_api_key
from bsgateway.tenant.repository import TenantRepository

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

_AUTH_RL_PREFIX = "auth_rl:"
_AUTH_RL_WINDOW = 60  # seconds
_AUTH_RL_LIMIT = 10

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory rate limiter fallback (single-process only).
# With multiple workers, effective limit = N workers x _AUTH_RL_LIMIT/min.
_AUTH_MAX_IPS = 10_000
_auth_attempts: dict[str, list[float]] = defaultdict(list)
_auth_call_count = 0


def _check_auth_rate_limit(client_ip: str) -> None:
    """Raise 429 if the IP exceeds auth rate limit."""
    global _auth_call_count
    _auth_call_count += 1
    now = time.monotonic()
    window = [t for t in _auth_attempts[client_ip] if now - t < _AUTH_RL_WINDOW]
    _auth_attempts[client_ip] = window
    if len(window) >= _AUTH_RL_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Try again later.",
        )
    window.append(now)
    # Full sweep every 200 calls to prune expired entries
    if _auth_call_count % 200 == 0:
        stale = [k for k, v in _auth_attempts.items() if not v or (now - v[-1]) > 60]
        for ip in stale:
            del _auth_attempts[ip]
    # Hard cap to prevent unbounded memory growth
    if len(_auth_attempts) > _AUTH_MAX_IPS:
        oldest = sorted(
            _auth_attempts, key=lambda k: _auth_attempts[k][-1] if _auth_attempts[k] else 0
        )
        for ip in oldest[: len(_auth_attempts) - _AUTH_MAX_IPS]:
            del _auth_attempts[ip]


async def _check_auth_rate_limit_redis(client_ip: str, redis_client: Redis) -> None:
    """Redis-backed rate limit check (fixed window).

    Raises HTTPException(429) if limit exceeded.
    """
    key = f"{_AUTH_RL_PREFIX}{client_ip}"
    current = await redis_client.incr(key)
    if current == 1:
        await redis_client.expire(key, _AUTH_RL_WINDOW)
    if current > _AUTH_RL_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Try again later.",
        )


class TokenRequest(BaseModel):
    """Exchange an API key for a JWT."""

    api_key: str = Field(
        ...,
        min_length=1,
        pattern=r"^bsg_[a-zA-Z0-9_-]+$",
        description="Tenant API key (bsg_...)",
    )


class TokenResponse(BaseModel):
    """JWT token with tenant context."""

    token: str
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    scopes: list[str]


@router.post("/token", response_model=TokenResponse)
async def create_token(body: TokenRequest, request: Request) -> TokenResponse:
    """Exchange an API key for a JWT token.

    The API key identifies the tenant — no need to provide tenant ID or slug separately.
    Returns a JWT token along with tenant metadata for the dashboard.
    """
    client_ip = request.client.host if request.client else "unknown"
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is not None:
        try:
            await _check_auth_rate_limit_redis(client_ip, redis_client)
        except HTTPException:
            raise
        except Exception:
            logger.error("redis_auth_rate_limit_failed", exc_info=True)
            _check_auth_rate_limit(client_ip)
    else:
        _check_auth_rate_limit(client_ip)

    pool = request.app.state.db_pool
    jwt_secret = request.app.state.jwt_secret

    if not jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT authentication is not configured (JWT_SECRET not set)",
        )

    key_hash = hash_api_key(body.api_key)
    repo = TenantRepository(pool)
    row = await repo.get_api_key_by_hash(key_hash)

    if (
        not row
        or not row["is_active"]
        or (row["expires_at"] and row["expires_at"] < datetime.now(UTC))
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )

    if not row["tenant_is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant is deactivated",
        )

    # Touch last_used_at
    try:
        await repo.touch_api_key(key_hash)
    except Exception:
        logger.warning("touch_api_key_failed", exc_info=True)

    tenant_id = str(row["tenant_id"])
    scopes = list(row["scopes"])
    token = create_jwt(tenant_id, jwt_secret, scopes)

    logger.info("token_issued", tenant_id=tenant_id, tenant_slug=row["tenant_slug"])

    return TokenResponse(
        token=token,
        tenant_id=tenant_id,
        tenant_slug=row["tenant_slug"],
        tenant_name=row["tenant_name"],
        scopes=scopes,
    )
