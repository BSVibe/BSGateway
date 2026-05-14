"""Shared test fixtures and helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from bsvibe_authz import User as AuthzUser
from bsvibe_authz.cache import PermissionCache
from bsvibe_authz.deps import (
    get_current_user as authz_get_current_user,
)
from bsvibe_authz.deps import (
    get_openfga_client as authz_get_openfga_client,
)
from bsvibe_authz.deps import (
    get_permission_cache as authz_get_permission_cache,
)

from bsgateway.api.deps import AuthIdentity, GatewayAuthContext


class MockAcquire:
    """Proper async context manager for mocking pool.acquire()."""

    def __init__(self, conn: AsyncMock) -> None:
        self.conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self.conn

    async def __aexit__(self, *args: object) -> None:
        pass


class MockTransaction:
    """Proper async context manager for mocking conn.transaction()."""

    async def __aenter__(self) -> MockTransaction:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


def make_mock_pool() -> tuple[MagicMock, AsyncMock]:
    """Create a properly mocked asyncpg pool that doesn't trigger RuntimeWarnings.

    Returns:
        Tuple of (pool, conn) where pool is MagicMock and conn is AsyncMock.
    """
    pool = MagicMock()
    pool._closed = False
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=MockTransaction())
    pool.acquire.return_value = MockAcquire(conn)
    return pool, conn


def make_authz_user(
    tenant_id: UUID | None = None,
    role: str = "member",
    email: str = "test@test.com",
    user_id: str | None = None,
) -> AuthzUser:
    """Build a fake :class:`bsvibe_authz.User` for testing.

    Mirrors what ``bsvibe_authz.deps.get_current_user`` returns for a
    verified Supabase user JWT — ``app_metadata`` carries role +
    tenant_id (lifted off the JWT payload by ``parse_user_token``).
    """
    tid = str(tenant_id or uuid4())
    return AuthzUser(
        id=user_id or str(uuid4()),
        email=email,
        active_tenant_id=tid,
        scope=[],
        is_service=False,
        app_metadata={"tenant_id": tid, "role": role},
    )


def make_gateway_auth_context(
    tenant_id: UUID | None = None,
    is_admin: bool = False,
    email: str = "test@test.com",
    user_id: str | None = None,
) -> GatewayAuthContext:
    """Build a fake GatewayAuthContext for testing via dependency_overrides."""
    tid = tenant_id or uuid4()
    return GatewayAuthContext(
        identity=AuthIdentity(
            kind="user",
            id=user_id or str(uuid4()),
            email=email,
        ),
        tenant_id=tid,
        is_admin=is_admin,
    )


# ---------------------------------------------------------------------------
# Phase 0 P0.5 test plumbing — bsvibe-authz dependency overrides.
#
# `bsvibe-authz` `require_permission` chains through `get_current_user` (JWT
# verification) and `get_openfga_client` (network call). Tests across this
# suite rely on `app.dependency_overrides[get_auth_context]` to bypass the
# legacy auth path; we mirror that intent for the new authz deps so existing
# tests that don't care about authz keep passing without modification.
#
# Tests that DO want to exercise the authz path (test_authz_route_matrix,
# new precheck tests, etc.) should set their own overrides and clear when
# done.
# ---------------------------------------------------------------------------


class _AlwaysAllowFGA:
    """Tiny in-memory fake matching bsvibe-authz's FGAClientProtocol."""

    async def check(self, user: str, relation: str, object_: str) -> bool:
        return True

    async def list_objects(self, user: str, relation: str, type_: str) -> list[str]:
        return []


def _fake_authz_user() -> AuthzUser:
    # ``scope=["gateway:*"]`` grants any narrow gateway scope via the
    # bsvibe-authz prefix-wildcard rule. Tests that explicitly exercise
    # scope enforcement (or other audiences) override
    # ``authz_get_current_user`` themselves.
    return AuthzUser(
        id="00000000-0000-0000-0000-000000000001",
        email="test@test.com",
        active_tenant_id="00000000-0000-0000-0000-0000000000aa",
        tenants=[],
        is_service=False,
        scope=["gateway:*"],
    )


def install_authz_test_overrides(app, *, allow: bool = True) -> None:
    """Install no-op bsvibe-authz overrides on a FastAPI ``app`` instance.

    Most BSGateway tests already override ``get_auth_context`` via
    ``app.dependency_overrides``. P0.5 adds a parallel auth chain
    (``bsvibe-authz`` ``require_permission`` → JWT verification → OpenFGA).
    Tests that don't care about the new chain just want it to no-op.

    This helper installs overrides for the new bsvibe-authz deps that
    return a synthetic user and an always-allow OpenFGA client. Tests
    that exercise the new chain explicitly (route-matrix, precheck) set
    their own overrides.
    """

    class _FGAStub:
        async def check(self, *args, **kwargs):
            return allow

        async def list_objects(self, *args, **kwargs):
            return []

    fga = _FGAStub()
    cache = PermissionCache(ttl_s=0)
    app.dependency_overrides[authz_get_current_user] = _fake_authz_user
    app.dependency_overrides[authz_get_openfga_client] = lambda: fga
    app.dependency_overrides[authz_get_permission_cache] = lambda: cache


@pytest.fixture(autouse=True)
def _autoinstall_authz_overrides(monkeypatch):
    """Wrap ``FastAPI.__init__`` so every app constructed inside a test
    automatically gets bsvibe-authz dependency_overrides pre-installed.

    We can't simply wrap ``create_app`` because most BSGateway test
    modules do ``from bsgateway.api.app import create_app`` at import
    time, capturing the unwrapped reference. Patching ``FastAPI.__init__``
    catches every app instance regardless of how it was constructed.

    Tests that want the real authz chain can clear the overrides:
        ``app.dependency_overrides.pop(authz_get_current_user, None)``.
    """
    from fastapi import FastAPI

    real_init = FastAPI.__init__

    def _patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        real_init(self, *args, **kwargs)
        install_authz_test_overrides(self)

    monkeypatch.setattr(FastAPI, "__init__", _patched_init)
    yield
