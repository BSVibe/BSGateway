"""Pin the ``require_scope`` matrix for CLI/PAT-only admin routers.

Phase 2b — frontend-hit routes (intent/rule/preset/audit/tenant CRUD)
were swapped off pure ``require_scope`` to ``require_permission`` /
``require_admin`` (see ``test_authz_route_matrix.py``). The session JWT
the frontend carries has ``scope=[]`` so any pure ``require_scope`` gate
403s every browser request.

What stays on ``require_scope`` is the **org-level model registry** —
``/api/v1/admin/models/*`` — hit by the ``bsgateway`` CLI with a
real-scope PAT, never by the browser. The scope grammar is also
re-prefixed ``gateway:`` → ``bsgateway:`` to match the bsXXX audience
flip (bsvibe-authz 1.2.0 ``SERVICE_AUDIENCES``).

The matrix below mirrors ``docs/scopes.md``. New CLI/PAT-only admin
endpoints must extend both — adding a route to the matrix keeps the gate
in place after future refactors.
"""

from __future__ import annotations

from typing import ClassVar
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
        dep = require_scope("bsgateway:models:read")
        assert callable(dep)

    def test_dep_carries_scope_attr(self) -> None:
        dep = require_scope("bsgateway:models:write")
        assert getattr(dep, "_bsvibe_scope", None) == "bsgateway:models:write"


class TestScopeMatrix:
    """Pin the ``bsgateway:<resource>:<action>`` scope per CLI/PAT-only route.

    Only the org-level model registry stays on ``require_scope`` — every
    other former ``require_scope`` route is now ``require_permission`` or
    ``require_admin`` (see ``test_authz_route_matrix.py``).
    """

    MATRIX: ClassVar[list[tuple[str, str, str]]] = [
        # Org-level effective-model registry — hit by the `bsgateway` CLI
        # with a real-scope PAT, never by the browser session JWT.
        ("/api/v1/admin/models", "GET", "bsgateway:models:read"),
        ("/api/v1/admin/models", "POST", "bsgateway:models:write"),
        ("/api/v1/admin/models/{model_id}", "PATCH", "bsgateway:models:write"),
        ("/api/v1/admin/models/{model_id}", "DELETE", "bsgateway:models:write"),
    ]

    @pytest.mark.parametrize("path,method,scope", MATRIX)
    def test_route_carries_required_scope(self, app, path, method, scope) -> None:
        route = _find_route(app, path, method)
        assert _has_require_scope(route, scope), (
            f"{method} {path} must depend on require_scope({scope!r})"
        )


class TestFrontendRoutesNoLongerRequireScope:
    """Routes the browser session JWT (scope=[]) hits must NOT carry a
    pure ``require_scope`` gate — otherwise every dashboard request 403s."""

    FRONTEND_ROUTES: ClassVar[list[tuple[str, str]]] = [
        ("/api/v1/tenants", "GET"),
        ("/api/v1/tenants/{tenant_id}", "GET"),
        ("/api/v1/tenants/{tenant_id}/rules", "GET"),
        ("/api/v1/tenants/{tenant_id}/rules", "POST"),
        ("/api/v1/tenants/{tenant_id}/intents", "GET"),
        ("/api/v1/tenants/{tenant_id}/intents", "POST"),
        ("/api/v1/tenants/{tenant_id}/audit", "GET"),
        ("/api/v1/presets", "GET"),
        ("/api/v1/tenants/{tenant_id}/presets/apply", "POST"),
    ]

    @pytest.mark.parametrize("path,method", FRONTEND_ROUTES)
    def test_no_bare_require_scope_on_frontend_route(self, app, path, method) -> None:
        route = _find_route(app, path, method)
        for dep in _route_dependencies(route):
            assert getattr(dep, "_bsvibe_scope", None) is None, (
                f"{method} {path} still carries require_scope — frontend "
                f"session JWTs (scope=[]) would 403"
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


class TestScopeEnforcementAdminModels:
    """Narrow scope on the wrong action 403s; in-scope reads 200.

    Exercised against ``/api/v1/admin/models`` — the surviving
    ``require_scope`` route after the Phase 2b swap.
    """

    def test_narrow_read_scope_blocks_post_admin_models(self, client_with_scope) -> None:
        client, _ = client_with_scope(["bsgateway:models:read"])
        resp = client.post(
            "/api/v1/admin/models",
            json={"model_name": "m", "litellm_model": "openai/gpt-4"},
            headers={"Authorization": "Bearer bsv_sk_x"},
        )
        assert resp.status_code == 403, resp.text
        assert "bsgateway:models:write" in resp.text

    def test_in_scope_read_allows_get_admin_models(self, client_with_scope) -> None:
        client, _ = client_with_scope(["bsgateway:models:read"])
        # The mock app has no model_registry attached, so the route
        # returns an empty effective list — the point here is the scope
        # gate passes (200, not 403).
        resp = client.get(
            "/api/v1/admin/models",
            headers={"Authorization": "Bearer bsv_sk_x"},
        )
        assert resp.status_code == 200, resp.text

    def test_no_scope_blocks_get_admin_models(self, client_with_scope) -> None:
        client, _ = client_with_scope([])
        resp = client.get(
            "/api/v1/admin/models",
            headers={"Authorization": "Bearer bsv_sk_x"},
        )
        assert resp.status_code == 403, resp.text
