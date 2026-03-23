from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg
import structlog
from fastapi import Depends, HTTPException, Request, status

from bsgateway.core.cache import CacheManager

if TYPE_CHECKING:
    from bsvibe_auth import BSVibeUser

    from bsgateway.audit.service import AuditService

logger = structlog.get_logger(__name__)


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
class GatewayAuthContext:
    """Authenticated request context backed by BSVibe-Auth."""

    user: BSVibeUser
    tenant_id: UUID
    is_admin: bool


async def get_auth_context(request: Request) -> GatewayAuthContext:
    """Authenticate a request via Supabase JWT (BSVibe-Auth).

    1. Verify JWT → BSVibeUser
    2. Extract tenant_id from app_metadata
    3. Check tenant is active in DB
    4. Return GatewayAuthContext
    """
    from bsvibe_auth import AuthError

    auth_provider = request.app.state.auth_provider
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header[7:]

    try:
        user = await auth_provider.verify_token(token)
    except AuthError as e:
        logger.debug("auth_failed", error=e.message)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message,
        ) from e

    # Extract tenant_id from app_metadata
    tenant_id_str = user.app_metadata.get("tenant_id")
    if not tenant_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No tenant_id in user metadata",
        )

    try:
        tenant_id = UUID(tenant_id_str)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid tenant_id format",
        ) from err

    # Verify tenant is active
    from bsgateway.tenant.repository import TenantRepository

    pool: asyncpg.Pool = request.app.state.db_pool
    repo = TenantRepository(pool)
    tenant_row = await repo.get_tenant(tenant_id)

    if not tenant_row or not tenant_row["is_active"]:
        logger.warning("auth_failed", reason="tenant_inactive", tenant_id=str(tenant_id))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant is deactivated",
        )

    role = user.app_metadata.get("role", "member")
    is_admin = role == "admin"

    logger.info("auth_success", tenant_id=str(tenant_id), user_id=user.id, is_admin=is_admin)

    return GatewayAuthContext(
        user=user,
        tenant_id=tenant_id,
        is_admin=is_admin,
    )


def require_admin(
    auth: GatewayAuthContext = Depends(get_auth_context),
) -> GatewayAuthContext:
    """Dependency that requires admin role."""
    if not auth.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return auth


def require_tenant_access(
    tenant_id: UUID,
    auth: GatewayAuthContext = Depends(get_auth_context),
) -> GatewayAuthContext:
    """Verify the authenticated user belongs to the requested tenant.

    Admins may access any tenant.
    """
    if auth.is_admin:
        return auth
    if auth.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this tenant",
        )
    return auth


def get_audit_service(request: Request) -> AuditService:
    """Create an AuditService instance from the request."""
    from bsgateway.audit.repository import AuditRepository
    from bsgateway.audit.service import AuditService

    pool = request.app.state.db_pool
    return AuditService(AuditRepository(pool))
