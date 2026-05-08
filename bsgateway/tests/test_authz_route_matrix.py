"""Phase 0 P0.5 — BSGateway adopts ``bsvibe-authz``.

Per Lockin §3 decision #7 the route → permission map is derived from the
routes themselves. This test pins the matrix so future PRs cannot silently
unprotect a route.

Each protected route MUST have:
- a ``bsvibe_authz.require_permission(...)`` dependency, OR
- a ``bsvibe_authz.ServiceKeyAuth(audience="bsgateway")`` dependency.

(Plus the legacy ``GatewayAuthContext`` plumbing for tenant resolution —
that stays for Phase 0 because BSGateway-issued ``bsg_live_*`` API keys are
still in active use until Phase A. The new bsvibe-authz layer wraps it.)
"""

from __future__ import annotations

import inspect
from typing import ClassVar

import pytest

from bsgateway.api.deps import (
    ServiceKeyAuth,
    get_active_tenant_id,
    require_permission,
)


def _route_dependencies(route) -> list:
    """Return the unique callables an APIRoute will resolve via Depends.

    FastAPI stores them on ``route.dependant`` after app-mount, so we walk
    that recursively and collect ``Depends.dependency`` references.
    """
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


def _has_require_permission(route, permission: str) -> bool:
    """Return True iff one of the route's deps was created by ``require_permission``."""
    for dep in _route_dependencies(route):
        # require_permission tags its closure with ``_bsvibe_permission``
        # so we can introspect the matrix without binding to closure cell
        # internals.
        perm = getattr(dep, "_bsvibe_permission", None)
        if perm == permission:
            return True
    return False


def _has_service_key_auth(route, audience: str) -> bool:
    for dep in _route_dependencies(route):
        if isinstance(dep, ServiceKeyAuth) and dep.audience == audience:
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


class TestPublicAPI:
    """``bsvibe_authz`` primitives must be re-exported from
    ``bsgateway.api.deps`` so route modules can import from a single place."""

    def test_current_user_alias_exposed(self) -> None:
        from bsgateway.api import deps

        assert hasattr(deps, "CurrentUser")

    def test_require_permission_callable(self) -> None:
        # Should accept the BSGateway namespace.
        dep = require_permission("bsgateway.api-keys.read")
        assert callable(dep)

    def test_service_key_auth_initialisable_for_bsgateway(self) -> None:
        auth = ServiceKeyAuth(audience="bsgateway")
        assert auth.audience == "bsgateway"

    def test_get_active_tenant_id_imported(self) -> None:
        assert callable(get_active_tenant_id)


class TestRouteMatrix:
    """Pin the bsgateway.<resource>.<action> permission per critical route.

    The matrix below mirrors the route table in BSGateway docs/TODO.md and
    encodes Lockin decision #7. New routes should extend this list.
    """

    MATRIX: ClassVar[list[tuple[str, str, str]]] = [
        # API keys routes were removed in the Phase 1 token cutover —
        # bsvibe-authz introspection + bootstrap tokens replace the
        # self-hosted ``api_keys`` table and its CRUD router.
        # Routing rules
        ("/api/v1/tenants/{tenant_id}/rules", "GET", "bsgateway.routes.read"),
        ("/api/v1/tenants/{tenant_id}/rules", "POST", "bsgateway.routes.create"),
        # Tenants admin
        ("/api/v1/tenants", "POST", "bsgateway.tenants.create"),
        ("/api/v1/tenants", "GET", "bsgateway.tenants.read"),
    ]

    @pytest.mark.parametrize("path,method,permission", MATRIX)
    def test_route_carries_required_permission(self, app, path, method, permission) -> None:
        route = _find_route(app, path, method)
        assert _has_require_permission(route, permission), (
            f"{method} {path} must depend on require_permission({permission!r})"
        )


class TestServiceOnlyEndpoints:
    """Service-only endpoints — only callable with a ``bsgateway``-audience JWT.

    Currently BSGateway has no internal-only routes; the test reserves the
    contract so when one is added it MUST adopt ServiceKeyAuth("bsgateway").
    """

    def test_service_key_auth_class_imported_from_deps(self) -> None:
        # smoke check that we re-expose the class for future internal routes.
        from bsgateway.api import deps

        assert deps.ServiceKeyAuth is ServiceKeyAuth


class TestRequirePermissionIntrospection:
    """``require_permission`` must tag its closure with ``_bsvibe_permission``
    so the matrix above can verify which permission a route enforces."""

    def test_dep_carries_permission_attr(self) -> None:
        dep = require_permission("bsgateway.api-keys.read")
        assert getattr(dep, "_bsvibe_permission", None) == "bsgateway.api-keys.read"

    def test_dep_signature_compatible_with_fastapi(self) -> None:
        dep = require_permission("bsgateway.api-keys.read")
        sig = inspect.signature(dep)
        # FastAPI introspects Depends() params — at minimum we expect a
        # request param so the dependant graph can be built.
        assert "request" in sig.parameters
