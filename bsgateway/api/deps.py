from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import asyncpg
import structlog
from bsvibe_authz import (
    AuthError as _AuthzAuthError,
)
from bsvibe_authz import (
    CurrentUser as _AuthzCurrentUser,
)
from bsvibe_authz import (
    IntrospectionCache,
    IntrospectionClient,
)
from bsvibe_authz import (
    ServiceKey as _AuthzServiceKey,
)
from bsvibe_authz import (
    ServiceKeyAuth as _AuthzServiceKeyAuth,
)
from bsvibe_authz import (
    Settings as _AuthzSettings,
)
from bsvibe_authz import (
    User as _AuthzUser,
)
from bsvibe_authz import (
    get_active_tenant_id as _authz_get_active_tenant_id,
)
from bsvibe_authz import (
    get_current_user as _authz_get_current_user,
)
from bsvibe_authz import (
    require_permission as _authz_require_permission,
)
from bsvibe_authz import (
    require_scope as _authz_require_scope,
)
from bsvibe_authz import (
    verify_bootstrap_token as _verify_bootstrap_token,
)
from bsvibe_authz import (
    verify_opaque_token as _verify_opaque_token,
)
from fastapi import Depends, HTTPException, Request, status

from bsgateway.core.cache import CacheManager
from bsgateway.core.config import settings as gateway_settings

BOOTSTRAP_TOKEN_PREFIX = "bsv_admin_"
OPAQUE_TOKEN_PREFIX = "bsv_sk_"
_INTROSPECTION_CACHE_TTL_S = 60

# Re-exports so route modules import bsvibe-authz primitives from a
# single place (Phase 0 P0.5 — see Lockin §3 #7).
CurrentUser = _AuthzCurrentUser
ServiceKey = _AuthzServiceKey
ServiceKeyAuth = _AuthzServiceKeyAuth
get_current_user = _authz_get_current_user
get_active_tenant_id = _authz_get_active_tenant_id


def require_permission(
    permission: str,
    *,
    resource_type: str | None = None,
    resource_id_param: str | None = None,
) -> Callable[..., Awaitable[None]]:
    """Wrap ``bsvibe_authz.require_permission`` and tag the closure.

    The tag (``_bsvibe_permission``) lets the BSGateway authz route-matrix
    test (`test_authz_route_matrix.py`) introspect which permission a
    route enforces without depending on closure internals.
    """
    dep = _authz_require_permission(
        permission,
        resource_type=resource_type,
        resource_id_param=resource_id_param,
    )
    dep._bsvibe_permission = permission  # type: ignore[attr-defined]
    return dep


def require_scope(scope: str) -> Callable[..., Awaitable[None]]:
    """Wrap ``bsvibe_authz.require_scope`` and tag the closure.

    Phase 1 token cutover gates admin routes on scope strings carried by
    bootstrap / opaque service-key tokens (``"*"`` for bootstrap, narrow
    ``gateway:<resource>:<action>`` for service keys). The tag
    (``_bsvibe_scope``) lets ``test_authz_scope_matrix.py`` pin the
    catalog so future refactors cannot silently downgrade a gate.

    See ``docs/scopes.md`` for the active catalog.
    """
    dep = _authz_require_scope(scope)
    dep._bsvibe_scope = scope  # type: ignore[attr-defined]
    return dep


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
    """Authenticated principal — either a BSVibe user or an API key."""

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
    """Authenticate via the bsvibe-authz 3-way dispatch.

    1. ``bsv_admin_*`` → bootstrap path (constant-time hash compare).
    2. ``bsv_sk_*`` → RFC 7662 introspection (cached) when
       ``introspection_url`` is configured; otherwise rejected.
    3. else → existing BSVibe JWT path (via ``app.state.auth_provider``).
    4. Verify tenant is active (and auto-provision for JWT users).
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header[7:]

    if token.startswith(BOOTSTRAP_TOKEN_PREFIX):
        return await _auth_via_bootstrap(token)

    if token.startswith(OPAQUE_TOKEN_PREFIX):
        return await _auth_via_introspection(request, token)

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


# ---------------------------------------------------------------------------
# bsvibe-authz dispatch helpers (Phase 1 token cutover).
#
# Two singletons feed the opaque-token branch — the IntrospectionClient
# is constructed lazily because the introspection_url may be intentionally
# left empty (air-gapped self-host). The IntrospectionCache TTL is fixed
# at 60s here to bound the post-revoke window for opaque tokens.
# ---------------------------------------------------------------------------
_introspection_client_singleton: IntrospectionClient | None = None
_introspection_cache_singleton: IntrospectionCache | None = None


def _reset_dispatch_singletons() -> None:
    """Used by tests to drop cached introspection client/cache state."""
    global _introspection_client_singleton, _introspection_cache_singleton
    _introspection_client_singleton = None
    _introspection_cache_singleton = None


def _get_introspection_client() -> IntrospectionClient | None:
    global _introspection_client_singleton
    if _introspection_client_singleton is not None:
        return _introspection_client_singleton
    if not gateway_settings.introspection_url:
        return None
    _introspection_client_singleton = IntrospectionClient(
        introspection_url=gateway_settings.introspection_url,
        client_id=gateway_settings.introspection_client_id,
        client_secret=gateway_settings.introspection_client_secret,
    )
    return _introspection_client_singleton


def _get_introspection_cache() -> IntrospectionCache:
    global _introspection_cache_singleton
    if _introspection_cache_singleton is None:
        _introspection_cache_singleton = IntrospectionCache(ttl_s=_INTROSPECTION_CACHE_TTL_S)
    return _introspection_cache_singleton


def _bootstrap_audit_hash(token: str) -> str:
    """Short SHA-256 prefix for audit logs — never log the raw token."""
    return hashlib.sha256(token.encode()).hexdigest()[:12]


async def _auth_via_bootstrap(token: str) -> GatewayAuthContext:
    """Verify a ``bsv_admin_*`` bootstrap token via bsvibe-authz."""
    if not gateway_settings.bootstrap_token_hash:
        # Path is intentionally disabled — never accept any bsv_admin_ token.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="bootstrap token path is not configured",
        )
    # `verify_bootstrap_token` only reads `settings.bootstrap_token_hash`,
    # so we hand it a stub that skips bsvibe_authz Settings' required
    # fields (auth_url, openfga_*, …) which are irrelevant here.
    authz_settings_stub = _AuthzSettings.model_construct(
        bootstrap_token_hash=gateway_settings.bootstrap_token_hash,
    )
    try:
        user = _verify_bootstrap_token(token, authz_settings_stub)
    except _AuthzAuthError as exc:
        logger.warning("auth_bootstrap_rejected", token_sha12=_bootstrap_audit_hash(token))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    logger.info("auth_bootstrap_accepted")
    return _context_from_user(user, kind="bootstrap")


async def _auth_via_introspection(request: Request, token: str) -> GatewayAuthContext:
    """Verify an opaque ``bsv_sk_*`` token via RFC 7662 introspection."""
    client = _get_introspection_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="opaque token introspection is not configured",
        )
    cache = _get_introspection_cache()
    try:
        user = await _verify_opaque_token(token, client, cache)
    except _AuthzAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    # Opaque tokens carry tenant scope inside the introspection payload —
    # if the token names a tenant, verify it's active. Tokens with no
    # tenant claim are treated as cross-tenant admin/service tokens.
    if user.active_tenant_id:
        try:
            tenant_uuid = UUID(user.active_tenant_id)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid tenant_id in opaque token",
            ) from err
        from bsgateway.tenant.repository import TenantRepository

        pool: asyncpg.Pool = request.app.state.db_pool
        cache_mgr = getattr(request.app.state, "cache", None)
        repo = TenantRepository(pool, cache=cache_mgr)
        await _verify_tenant_active(repo, tenant_uuid)

    logger.info("auth_opaque_accepted", sub=user.id)
    return _context_from_user(user, kind="opaque")


def _context_from_user(user: _AuthzUser, *, kind: str) -> GatewayAuthContext:
    """Translate a bsvibe-authz :class:`User` into a BSGateway context.

    Bootstrap users have no tenant — we use the all-zeros UUID so callers
    that read ``ctx.tenant_id`` don't blow up. ``is_admin`` is true when
    the user holds the ``"*"`` super-scope (only bootstrap by design).
    """
    is_admin = "*" in user.scope
    if user.active_tenant_id:
        try:
            tenant_id = UUID(user.active_tenant_id)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid tenant_id in token",
            ) from err
    else:
        tenant_id = UUID(int=0)
    return GatewayAuthContext(
        identity=AuthIdentity(
            kind="apikey" if kind != "user" else "user",
            id=user.id,
            email=user.email,
            scopes=list(user.scope),
        ),
        tenant_id=tenant_id,
        is_admin=is_admin,
    )


async def _auth_via_jwt(request: Request, token: str) -> GatewayAuthContext:
    """Authenticate using BSVibe JWT."""
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
        # Auto-provision: BSVibe auth is source of truth
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


def get_model_registry(request: Request):
    """Extract the process-wide :class:`ModelRegistryService` from app state.

    Lifespan attaches the registry after the DB pool is up. Routes that
    mutate the ``models`` table (TASK-005 admin router) call
    ``registry.invalidate(tenant_id)`` so the next routing decision sees
    the new catalog without a restart.

    Returns ``None`` when registry attachment failed at boot — callers
    should treat that as "skip cache invalidation" rather than 500ing.
    """
    return getattr(request.app.state, "model_registry", None)


def get_audit_service(request: Request) -> AuditService:
    """Create an AuditService instance from the request."""
    from bsgateway.audit.repository import AuditRepository
    from bsgateway.audit.service import AuditService

    pool = request.app.state.db_pool
    return AuditService(AuditRepository(pool))
