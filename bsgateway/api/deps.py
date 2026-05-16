from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import asyncpg
import structlog
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
    get_openfga_client as _authz_get_openfga_client,
)
from bsvibe_authz import (
    require_admin as _authz_require_admin,
)
from bsvibe_authz import (
    require_permission as _authz_require_permission,
)
from fastapi import Depends, HTTPException, Request, status

from bsgateway.core.cache import CacheManager
from bsgateway.core.config import settings as gateway_settings

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


def require_admin() -> Callable[..., Awaitable[None]]:
    """Wrap ``bsvibe_authz.require_admin`` and tag the closure.

    Genuine tenant-administration routes (tenant create/update/delete,
    per-tenant model CRUD) gate on ``app_metadata.role in (owner, admin)``
    — a REAL enforced check in prod (demo + service principals also
    pass). Unlike ``require_permission`` this is *not* permissive when
    OpenFGA is unconfigured. The tag (``_bsvibe_admin``) lets the authz
    route-matrix test pin which routes are admin-only.
    """
    dep = _authz_require_admin()
    dep._bsvibe_admin = True  # type: ignore[attr-defined]
    return dep


if TYPE_CHECKING:
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
    """Authenticate the request and resolve a :class:`GatewayAuthContext`.

    Fully delegated to :func:`bsvibe_authz.deps.get_current_user` — same
    BSage pattern. The lib runs user-JWT (via JWKS) → PAT-JWT
    introspection fallback (1.3.0 retired the legacy ``bsv_sk_*``
    opaque branch), returning a :class:`User` with ``app_metadata``
    lifted off the verified JWT payload (bsvibe-authz PR #22).
    BSGateway's job is only to translate that User into a
    :class:`GatewayAuthContext` and run the tenant active-check +
    auto-provisioning.
    """
    return await _auth_via_authz(request)


# ---------------------------------------------------------------------------
# bsvibe-authz dispatch helpers.
#
# Two singletons feed the PAT-JWT introspection fallback — the
# IntrospectionClient is constructed lazily because the introspection_url
# may be intentionally left empty (air-gapped self-host). The
# IntrospectionCache TTL is fixed at 60s here to bound the post-revoke
# window for PAT JWTs. (The legacy ``bsv_sk_*`` opaque dispatch was
# retired in bsvibe-authz 1.3.0 — Tier 2 of the 2026-05 auth cleanup.)
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


async def _auth_via_authz(request: Request) -> GatewayAuthContext:
    """Delegate to :func:`bsvibe_authz.deps.get_current_user` + tenant ops.

    The lib runs the canonical 2-way dispatch
    (user-JWT-via-JWKS → PAT-JWT-introspection-fallback) and returns a
    :class:`User` with ``app_metadata`` / ``user_metadata`` lifted from
    the verified JWT payload (bsvibe-authz #22). We only:

    * translate it into a :class:`GatewayAuthContext`,
    * verify the tenant is active, and
    * auto-provision the tenant row on first access for user JWTs.

    Tier 3.2: ``get_current_user`` is a FastAPI dependency, but BSGateway
    re-wraps it here and calls it directly — so it must thread the
    ``X-Active-Tenant`` header (and the OpenFGA client the lib needs to
    membership-validate it) explicitly. The raw Supabase JWT carries no
    tenant claim; without this the active tenant never resolves for a
    browser session and every tenant-scoped route 403s.
    """
    auth_header = request.headers.get("Authorization") or ""
    authz_settings = _authz_settings()
    user = await _authz_get_current_user(
        authorization=auth_header,
        x_active_tenant=request.headers.get("X-Active-Tenant"),
        settings=authz_settings,
        introspection_client=_get_introspection_client(),
        introspection_cache=_get_introspection_cache(),
        fga=_authz_get_openfga_client(authz_settings),
    )

    # Bootstrap / "*"-scope tokens are tenant-less by design.
    if user.active_tenant_id:
        try:
            tenant_uuid = UUID(user.active_tenant_id)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid tenant_id in token",
            ) from err

        from bsgateway.tenant.repository import TenantRepository

        pool: asyncpg.Pool = request.app.state.db_pool
        cache_mgr = getattr(request.app.state, "cache", None)
        repo = TenantRepository(pool, cache=cache_mgr)
        tenant_row = await repo.get_tenant(tenant_uuid)

        if tenant_row and not tenant_row["is_active"]:
            logger.warning("auth_failed", reason="tenant_inactive", tenant_id=str(tenant_uuid))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant is deactivated",
            )

        # User-JWT path: auto-provision the tenant on first access.
        # Bootstrap / service-account PAT tokens never trigger this —
        # the tenant must already exist (provisioned out-of-band).
        if not tenant_row and not user.is_service:
            short_id = str(tenant_uuid)[:8]
            await repo.provision_tenant(
                tenant_id=tenant_uuid,
                name=short_id,
                slug=short_id,
            )
            logger.info("tenant_auto_provisioned", tenant_id=str(tenant_uuid))

    logger.info("auth_accepted", sub=user.id, scopes=list(user.scope))
    return _context_from_user(user)


def _authz_settings() -> _AuthzSettings:
    """Build a :class:`bsvibe_authz.Settings` from BSGateway config.

    Constructed per-call so test patches against ``gateway_settings`` take
    effect without a process restart. Tier 5: the OpenFGA coordinates are
    fed from config so per-resource ``require_permission`` gates enforce in
    prod; empty (local dev) keeps the permissive no-op posture.
    """
    return _AuthzSettings.model_construct(
        bsvibe_auth_url=gateway_settings.bsvibe_auth_url or "",
        openfga_api_url=gateway_settings.openfga_api_url,
        openfga_store_id=gateway_settings.openfga_store_id,
        openfga_auth_model_id=gateway_settings.openfga_auth_model_id,
        # Threaded explicitly — model_construct bypasses env loading, so an
        # unset token here means the OpenFGA client 401s on every check.
        openfga_auth_token=gateway_settings.openfga_auth_token or None,
        service_token_signing_secret="",
        introspection_url=gateway_settings.introspection_url,
        introspection_client_id=gateway_settings.introspection_client_id,
        introspection_client_secret=gateway_settings.introspection_client_secret,
        # User-JWT verification (Supabase / BSVibe-Auth). JWKS preferred;
        # falls back to static public_key, then symmetric secret.
        user_jwt_jwks_url=gateway_settings.user_jwt_jwks_url or None,
        user_jwt_public_key=gateway_settings.user_jwt_public_key or None,
        user_jwt_secret=gateway_settings.user_jwt_secret or None,
        user_jwt_algorithm=gateway_settings.user_jwt_algorithm,
        user_jwt_audience=gateway_settings.user_jwt_audience,
        user_jwt_issuer=gateway_settings.user_jwt_issuer or None,
    )


def _context_from_user(user: _AuthzUser) -> GatewayAuthContext:
    """Translate a bsvibe-authz :class:`User` into a BSGateway context.

    ``is_admin`` mirrors ``app_metadata.role == "admin"`` (Supabase
    admin claim — bsvibe-authz #22 lifts ``app_metadata`` off the
    verified JWT). Service-key tokens without a tenant claim get the
    all-zeros UUID so callers that read ``ctx.tenant_id`` don't blow up.

    ``identity.kind`` reflects the token shape: ``user`` for verified
    user JWTs (carry ``app_metadata``), ``apikey`` for PAT JWTs
    (introspection response).
    """
    is_admin = user.app_metadata.get("role") == "admin"
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

    # Distinguish a real user JWT (carries Supabase app_metadata) from
    # a service token (PAT JWT via introspection).
    kind = "user" if user.app_metadata and not user.is_service else "apikey"

    return GatewayAuthContext(
        identity=AuthIdentity(
            kind=kind,
            id=user.id,
            email=user.email,
            scopes=list(user.scope),
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
