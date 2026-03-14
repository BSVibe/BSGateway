from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import asyncpg
import structlog
from fastapi import Depends, HTTPException, Request, status

from bsgateway.core.security import hash_api_key

logger = structlog.get_logger(__name__)


def get_pool(request: Request) -> asyncpg.Pool:
    """Extract the shared DB pool from app state."""
    return request.app.state.db_pool


def get_encryption_key(request: Request) -> bytes:
    """Extract the encryption key from app state."""
    return request.app.state.encryption_key


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

    # Check superadmin key first (compare hashes, never plaintext)
    superadmin_hash = getattr(request.app.state, "superadmin_key_hash", "")
    if superadmin_hash and hash_api_key(token) == superadmin_hash:
        return AuthContext(
            tenant_id=UUID("00000000-0000-0000-0000-000000000000"),
            scopes=["admin"],
            key_hash="",
        )

    # Resolve tenant via API key
    key_hash = hash_api_key(token)

    from bsgateway.tenant.repository import TenantRepository

    repo = TenantRepository(pool)
    row = await repo.get_api_key_by_hash(key_hash)

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    if not row["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key has been revoked",
        )

    if not row["tenant_is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant is deactivated",
        )

    # Touch last_used_at (fire-and-forget)
    try:
        await repo.touch_api_key(key_hash)
    except Exception:
        logger.warning("touch_api_key_failed", exc_info=True)

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


def require_tenant_access(
    tenant_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """Verify the authenticated tenant matches the requested tenant_id."""
    if "admin" in auth.scopes:
        return auth
    if auth.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this tenant",
        )
    return auth
