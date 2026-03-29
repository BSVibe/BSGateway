from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import asyncpg
import structlog
from fastapi import Depends, HTTPException, Request, status

from bsgateway.apikey.service import API_KEY_PREFIX
from bsgateway.core.cache import CacheManager

if TYPE_CHECKING:
    from bsgateway.audit.service import AuditService
    from bsgateway.tenant.repository import TenantRepository

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
class AuthIdentity:
    """Authenticated principal — either a Supabase user or an API key."""

    kind: Literal["user", "apikey"]
    id: str
    email: str | None = None
    scopes: list[str] = field(default_factory=lambda: ["chat"])


@dataclass
class GatewayAuthContext:
    """Authenticated request context."""

    identity: AuthIdentity
    tenant_id: UUID
    is_admin: bool


async def get_auth_context(request: Request) -> GatewayAuthContext:
    """Authenticate via API key (bsg_live_*) or Supabase JWT.

    1. Check Authorization header
    2. If token starts with "bsg_live_" → API key auth path
    3. Otherwise → JWT auth path (existing)
    4. Verify tenant is active
    5. Return GatewayAuthContext
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header[7:]

    # --- API Key auth path ---
    if token.startswith(API_KEY_PREFIX):
        return await _auth_via_apikey(request, token)

    # --- JWT auth path ---
    return await _auth_via_jwt(request, token)


async def _verify_tenant_active(
    repo: TenantRepository,
    tenant_id: UUID,
) -> None:
    """Verify that a tenant exists and is active. Raises HTTPException if not."""
    tenant_row = await repo.get_tenant(tenant_id)
    if not tenant_row or not tenant_row["is_active"]:
        logger.warning("auth_failed", reason="tenant_inactive", tenant_id=str(tenant_id))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant is deactivated",
        )


async def _auth_via_apikey(request: Request, raw_key: str) -> GatewayAuthContext:
    """Authenticate using a tenant API key."""
    from bsgateway.apikey.service import ApiKeyService

    pool: asyncpg.Pool = request.app.state.db_pool
    cache = getattr(request.app.state, "cache", None)
    bg_tasks: set = getattr(request.app.state, "background_tasks", set())
    svc = ApiKeyService(pool)
    result = await svc.validate_key(raw_key, background_tasks=bg_tasks)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )

    # Verify tenant is active
    from bsgateway.tenant.repository import TenantRepository

    repo = TenantRepository(pool, cache=cache)
    await _verify_tenant_active(repo, result.tenant_id)

    logger.info("auth_success_apikey", tenant_id=str(result.tenant_id), key_id=str(result.key_id))

    return GatewayAuthContext(
        identity=AuthIdentity(
            kind="apikey",
            id=str(result.key_id),
            scopes=result.scopes,
        ),
        tenant_id=result.tenant_id,
        is_admin=False,
    )


async def _auth_via_jwt(request: Request, token: str) -> GatewayAuthContext:
    """Authenticate using Supabase JWT (existing path)."""
    from bsvibe_auth import AuthError

    auth_provider = request.app.state.auth_provider

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

    # Verify tenant exists — auto-provision on first access
    from bsgateway.tenant.repository import TenantRepository

    pool: asyncpg.Pool = request.app.state.db_pool
    cache = getattr(request.app.state, "cache", None)
    repo = TenantRepository(pool, cache=cache)
    tenant_row = await repo.get_tenant(tenant_id)

    if tenant_row and not tenant_row["is_active"]:
        logger.warning("auth_failed", reason="tenant_inactive", tenant_id=str(tenant_id))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant is deactivated",
        )

    if not tenant_row:
        # Auto-provision: Supabase org is source of truth
        short_id = str(tenant_id)[:8]
        tenant_row = await repo.provision_tenant(
            tenant_id=tenant_id,
            name=short_id,
            slug=short_id,
        )
        logger.info("tenant_auto_provisioned", tenant_id=str(tenant_id))

    role = user.app_metadata.get("role", "member")
    is_admin = role == "admin"

    logger.info("auth_success", tenant_id=str(tenant_id), user_id=user.id, is_admin=is_admin)

    return GatewayAuthContext(
        identity=AuthIdentity(
            kind="user",
            id=user.id,
            email=user.email,
        ),
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
