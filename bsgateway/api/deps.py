from __future__ import annotations

import asyncio
import hmac
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg
import jwt as pyjwt
import structlog
from fastapi import Depends, HTTPException, Request, status

from bsgateway.core.cache import CacheManager
from bsgateway.core.security import decode_jwt, hash_api_key

if TYPE_CHECKING:
    from bsgateway.audit.service import AuditService

logger = structlog.get_logger(__name__)

SUPERADMIN_UUID = UUID("00000000-0000-0000-0000-000000000000")


def get_pool(request: Request) -> asyncpg.Pool:
    """Extract the shared DB pool from app state."""
    return request.app.state.db_pool


def get_encryption_key(request: Request) -> bytes:
    """Extract the encryption key from app state."""
    return request.app.state.encryption_key


def get_cache(request: Request) -> CacheManager | None:
    """Extract the cache manager from app state (optional)."""
    return getattr(request.app.state, "cache", None)


@dataclass
class AuthContext:
    """Authenticated request context."""

    tenant_id: UUID
    scopes: list[str]
    key_hash: str


async def get_auth_context(request: Request) -> AuthContext:
    """Authenticate a request via API key (Bearer token).

    Resolves the tenant from the API key and validates that
    both the key and the tenant are active.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header[7:]
    pool: asyncpg.Pool = request.app.state.db_pool

    # Try JWT first (issued by /auth/token for dashboard sessions)
    jwt_secret = getattr(request.app.state, "jwt_secret", "")
    if jwt_secret:
        try:
            payload = decode_jwt(token, jwt_secret)
            logger.debug("auth_jwt_success", tenant_id=payload.tenant_id)
            return AuthContext(
                tenant_id=UUID(payload.tenant_id),
                scopes=payload.scopes,
                key_hash="",
            )
        except pyjwt.InvalidTokenError:
            logger.debug("jwt_decode_failed", exc_info=True)

    # Compute hash once (used for both superadmin check and DB lookup)
    key_hash = hash_api_key(token)

    # Check superadmin key (compare hashes, never plaintext)
    superadmin_hash = getattr(request.app.state, "superadmin_key_hash", "")
    if superadmin_hash and hmac.compare_digest(key_hash, superadmin_hash):
        return AuthContext(
            tenant_id=SUPERADMIN_UUID,
            scopes=["admin"],
            key_hash="",
        )

    from bsgateway.tenant.repository import TenantRepository

    # Note: Don't use cache in get_auth_context since we need fresh auth check
    repo = TenantRepository(pool)
    row = await repo.get_api_key_by_hash(key_hash)

    if (
        not row
        or not row["is_active"]
        or (row["expires_at"] and row["expires_at"] < datetime.now(UTC))
    ):
        logger.warning("auth_failed", reason="invalid_or_expired_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )

    if not row["tenant_is_active"]:
        logger.warning("auth_failed", reason="tenant_deactivated")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Touch last_used_at (throttled, fire-and-forget — at most once per 60s per key)
    if not hasattr(request.app.state, "_touch_last"):
        request.app.state._touch_last = {}
    _touch_last: dict[str, float] = request.app.state._touch_last
    now = time.monotonic()
    if now - _touch_last.get(key_hash, 0) >= 60:
        _touch_last[key_hash] = now
        if not hasattr(request.app.state, "background_tasks"):
            request.app.state.background_tasks = set()
        bg_tasks: set = request.app.state.background_tasks

        def _on_touch_done(t: asyncio.Task) -> None:
            bg_tasks.discard(t)
            if not t.cancelled():
                exc = t.exception()
                if exc:
                    exc_tuple = (type(exc), exc, exc.__traceback__)
                    logger.warning("touch_api_key_failed", error=str(exc), exc_info=exc_tuple)

        task = asyncio.create_task(asyncio.wait_for(repo.touch_api_key(key_hash), timeout=10.0))
        bg_tasks.add(task)
        task.add_done_callback(_on_touch_done)

    logger.info(
        "auth_success",
        tenant_id=str(row["tenant_id"]),
        key_prefix=row["key_prefix"],
    )

    return AuthContext(
        tenant_id=row["tenant_id"],
        scopes=list(row["scopes"]),
        key_hash=key_hash,
    )


def require_admin(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """Dependency that requires admin scope."""
    if "admin" not in auth.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin scope required",
        )
    return auth


def get_audit_service(request: Request) -> AuditService:
    """Create an AuditService instance from the request."""
    from bsgateway.audit.repository import AuditRepository
    from bsgateway.audit.service import AuditService

    pool = request.app.state.db_pool
    return AuditService(AuditRepository(pool))


def require_tenant_access(
    tenant_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """Verify the authenticated tenant matches the requested tenant_id.

    Superadmin (UUID 00000000-...) may access any tenant.
    All other callers must own the requested tenant_id.
    """
    # Superadmin access: check scopes (not just UUID) for defense-in-depth
    if "admin" in auth.scopes and auth.tenant_id == SUPERADMIN_UUID:
        return auth
    if auth.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this tenant",
        )
    return auth
