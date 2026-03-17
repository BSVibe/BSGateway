from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import structlog
from fastapi import Depends, HTTPException, Request, status

from bsgateway.core.security import decode_jwt, hash_api_key

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

    # Try JWT first (issued by /auth/token for dashboard sessions)
    jwt_secret = getattr(request.app.state, "jwt_secret", "")
    if jwt_secret:
        try:
            payload = decode_jwt(token, jwt_secret)
            logger.info("auth_jwt_success", tenant_id=payload.tenant_id)
            return AuthContext(
                tenant_id=UUID(payload.tenant_id),
                scopes=payload.scopes,
                key_hash="",
            )
        except Exception:
            pass  # Not a valid JWT — fall through to API key auth

    # Check superadmin key (compare hashes, never plaintext)
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

    # Touch last_used_at (fire-and-forget)
    try:
        await repo.touch_api_key(key_hash)
    except Exception:
        logger.warning("touch_api_key_failed", exc_info=True)

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


def get_audit_service(request: Request):
    """Create an AuditService instance from the request."""
    from bsgateway.audit.repository import AuditRepository
    from bsgateway.audit.service import AuditService

    pool = request.app.state.db_pool
    return AuditService(AuditRepository(pool))


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
