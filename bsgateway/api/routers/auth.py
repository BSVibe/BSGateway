"""Authentication endpoints for the dashboard."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from bsgateway.core.security import create_jwt, hash_api_key
from bsgateway.tenant.repository import TenantRepository

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Simple in-memory rate limiter for auth endpoint (per IP, 10 req/min)
_AUTH_RATE_LIMIT = 10
_auth_attempts: dict[str, list[float]] = defaultdict(list)


def _check_auth_rate_limit(client_ip: str) -> None:
    """Raise 429 if the IP exceeds auth rate limit."""
    now = time.monotonic()
    window = [t for t in _auth_attempts[client_ip] if now - t < 60]
    _auth_attempts[client_ip] = window
    if len(window) >= _AUTH_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Try again later.",
        )
    window.append(now)


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
