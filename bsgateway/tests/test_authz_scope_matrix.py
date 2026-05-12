"""TASK-006 — pin the ``require_scope`` matrix for admin routers.

Role-based gating (``require_admin`` and ad-hoc role checks) was replaced
with ``bsvibe_authz.require_scope`` so opaque service keys can be issued
with narrow scopes (``gateway:models:read``, ``gateway:routing:write``, …).

The matrix below mirrors ``docs/scopes.md``. New admin endpoints must
extend both — adding a route to the matrix keeps the gate in place after
future refactors.
"""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from bsvibe_authz import User as AuthzUser
from bsvibe_authz.deps import get_current_user as authz_get_current_user
from fastapi.testclient import TestClient

from bsgateway.api.deps import get_auth_context, require_scope
from bsgateway.tests.conftest import make_gateway_auth_context, make_mock_pool


def _route_dependencies(route) -> list:
    """Walk the FastAPI dependant graph and collect the unique callables."""
    out: list = []
    seen: set[int] = set()

    def _walk(d) -> None:
        for sub in d.dependencies:
            f = sub.call
            if f is None:
                continue
            if id(f) in seen:
                continue
            seen.add(id(f))
            out.append(f)
            _walk(sub)

    _walk(route.dependant)
    return out


def _has_require_scope(route, scope: str) -> bool:
    for dep in _route_dependencies(route):
        if getattr(dep, "_bsvibe_scope", None) == scope:
            return True
    return False


@pytest.fixture(scope="module")
def app():
    from bsgateway.api.app import create_app

    return create_app()


def _find_route(app, path: str, method: str):
    for r in app.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return r
    raise AssertionError(f"route {method} {path} not found")


class TestRequireScopeReExport:
    """``require_scope`` must be importable from ``bsgateway.api.deps`` and
    tagged so the matrix introspection below can verify which scope a
    route enforces without binding to closure cell internals."""

    def test_dep_callable(self) -> None:
        dep = require_scope("gateway:tenants:read")
        assert callable(dep)

    def test_dep_carries_scope_attr(self) -> None:
        dep = require_scope("gateway:tenants:write")
        assert getattr(dep, "_bsvibe_scope", None) == "gateway:tenants:write"


class TestScopeMatrix:
    """Pin the ``gateway:<resource>:<action>`` scope per admin route."""

    MATRIX: ClassVar[list[tuple[str, str, str]]] = [
        # Tenants
        ("/api/v1/tenants", "POST", "gateway:tenants:write"),
        ("/api/v1/tenants", "GET", "gateway:tenants:read"),
        ("/api/v1/tenants/{tenant_id}", "GET", "gateway:tenants:read"),
        ("/api/v1/tenants/{tenant_id}", "PATCH", "gateway:tenants:write"),
        ("/api/v1/tenants/{tenant_id}", "DELETE", "gateway:tenants:write"),
        # Models (under /tenants/{tenant_id}/models)
        ("/api/v1/tenants/{tenant_id}/models", "POST", "gateway:models:write"),
        ("/api/v1/tenants/{tenant_id}/models", "GET", "gateway:models:read"),
        (
            "/api/v1/tenants/{tenant_id}/models/{model_id}",
            "GET",
            "gateway:models:read",
        ),
        (
            "/api/v1/tenants/{tenant_id}/models/{model_id}",
            "PATCH",
            "gateway:models:write",
        ),
        (
            "/api/v1/tenants/{tenant_id}/models/{model_id}",
            "DELETE",
            "gateway:models:write",
        ),
        # Routing — rules
        ("/api/v1/tenants/{tenant_id}/rules", "GET", "gateway:routing:read"),
        ("/api/v1/tenants/{tenant_id}/rules", "POST", "gateway:routing:write"),
        ("/api/v1/tenants/{tenant_id}/rules/{rule_id}", "GET", "gateway:routing:read"),
        (
            "/api/v1/tenants/{tenant_id}/rules/{rule_id}",
            "PATCH",
            "gateway:routing:write",
        ),
        (
            "/api/v1/tenants/{tenant_id}/rules/{rule_id}",
            "DELETE",
            "gateway:routing:write",
        ),
        # Routing — intents
        ("/api/v1/tenants/{tenant_id}/intents", "GET", "gateway:routing:read"),
        ("/api/v1/tenants/{tenant_id}/intents", "POST", "gateway:routing:write"),
        # Routing — presets
        ("/api/v1/presets", "GET", "gateway:routing:read"),
        (
            "/api/v1/tenants/{tenant_id}/presets/apply",
            "POST",
            "gateway:routing:write",
        ),
        # Audit (read-only)
        ("/api/v1/tenants/{tenant_id}/audit", "GET", "gateway:audit:read"),
    ]

    @pytest.mark.parametrize("path,method,scope", MATRIX)
    def test_route_carries_required_scope(self, app, path, method, scope) -> None:
        route = _find_route(app, path, method)
        assert _has_require_scope(route, scope), (
            f"{method} {path} must depend on require_scope({scope!r})"
        )


# ---------------------------------------------------------------------------
# Functional dispatch tests — narrow scope=403 / in-scope=200
# ---------------------------------------------------------------------------


def _user_with_scope(scope: list[str], tenant_id: UUID | None = None) -> AuthzUser:
    return AuthzUser(
        id=str(uuid4()),
        email="scoped@test.com",
        active_tenant_id=str(tenant_id) if tenant_id else None,
        tenants=[],
        is_service=False,
        scope=scope,
    )


@pytest.fixture
def client_with_scope(monkeypatch):
    """Build a TestClient where the bsvibe-authz current-user override
    yields a configurable scope set, the legacy ``get_auth_context`` is
    bypassed, and DB access is mocked at the repository level."""

    def _factory(scope: list[str], tenant_id: UUID | None = None):
        from bsgateway.api.app import create_app

        tid = tenant_id or uuid4()
        app = create_app()
        pool, _ = make_mock_pool()
        app.state.db_pool = pool

        # Legacy chain — is_admin derived from Supabase app_metadata role.
        app.dependency_overrides[get_auth_context] = lambda: make_gateway_auth_context(
            tenant_id=tid,
            is_admin=False,
        )
        # bsvibe-authz scope chain.
        app.dependency_overrides[authz_get_current_user] = lambda: _user_with_scope(scope, tid)
        return TestClient(app), tid

    return _factory


class TestScopeEnforcementGetTenants:
    """Narrow scope on the wrong action 403s; in-scope reads 200."""

    def test_narrow_read_scope_blocks_post_tenants(self, client_with_scope) -> None:
        client, _ = client_with_scope(["gateway:tenants:read"])
        resp = client.post(
            "/api/v1/tenants",
            json={"name": "t", "slug": "t"},
            headers={"Authorization": "Bearer bsv_sk_x"},
        )
        assert resp.status_code == 403, resp.text
        assert "gateway:tenants:write" in resp.text

    def test_in_scope_read_allows_get_tenants(self, client_with_scope) -> None:
        client, _ = client_with_scope(["gateway:tenants:read"])
        with patch("bsgateway.api.routers.tenants.get_tenant_service") as svc_factory:
            svc_factory.return_value.list_tenants = pytest.importorskip("unittest.mock").AsyncMock(
                return_value=[]
            )
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer bsv_sk_x"},
            )
        assert resp.status_code == 200, resp.text

    def test_no_scope_blocks_get_tenants(self, client_with_scope) -> None:
        client, _ = client_with_scope([])
        resp = client.get(
            "/api/v1/tenants",
            headers={"Authorization": "Bearer bsv_sk_x"},
        )
        assert resp.status_code == 403, resp.text
