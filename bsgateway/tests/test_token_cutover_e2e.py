"""Token-dispatch end-to-end auth smoke.

Drives the dispatch branches end-to-end through real
``bsvibe_authz.get_current_user`` + BSGateway ``get_auth_context`` instead
of dependency_overrides shortcuts:

- (a) ``Bearer bsv_sk_*`` — opaque token, introspection returns
  ``active=true scope=['gateway:models:read']``. ``GET .../models``
  → 200. ``POST .../models`` → 403 (scope mismatch).
- (b) ``Bearer bsv_sk_*`` with ``active=false`` — 401.
- (c) ``Bearer <jwt>`` — BSVibe JWT path through ``bsvibe_authz``. Stays green.

Coverage gate (>=80%) is enforced by the suite-level pytest run, not by
this module.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from bsvibe_authz import IntrospectionClient
from bsvibe_authz import Settings as AuthzSettings
from bsvibe_authz.deps import (
    get_current_user as authz_get_current_user,
)
from bsvibe_authz.deps import (
    get_introspection_client as authz_get_introspection_client,
)
from bsvibe_authz.deps import (
    get_settings_dep as authz_get_settings_dep,
)
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.tests.conftest import make_mock_pool

ENCRYPTION_KEY_HEX = os.urandom(32).hex()


def _tenant_row(tenant_id, is_active: bool = True):
    now = datetime.now(UTC)
    return {
        "id": tenant_id,
        "name": "T",
        "slug": "t",
        "is_active": is_active,
        "settings": "{}",
        "created_at": now,
        "updated_at": now,
    }


class _CountingTransport(httpx.MockTransport):
    """``httpx.MockTransport`` that records call_count for assertions."""

    def __init__(self, handler) -> None:
        self.calls: list[httpx.Request] = []

        def _wrapped(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return handler(request)

        super().__init__(_wrapped)

    @property
    def call_count(self) -> int:
        return len(self.calls)


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Drop both BSGateway and bsvibe_authz singletons between tests."""
    from bsvibe_authz import deps as authz_deps

    from bsgateway.api import deps as gw_deps

    gw_deps._reset_dispatch_singletons()
    authz_deps._fga_client_singleton = None
    authz_deps._introspection_client_singleton = None
    authz_deps._introspection_cache_singleton = None
    yield
    gw_deps._reset_dispatch_singletons()
    authz_deps._fga_client_singleton = None
    authz_deps._introspection_client_singleton = None
    authz_deps._introspection_cache_singleton = None


def _build_app(
    *,
    introspection_handler,
    introspection_url: str = "https://auth.example/oauth/introspect",
):
    """Construct an app wired to a shared MockTransport-backed
    ``IntrospectionClient`` for both BSGateway dispatch and bsvibe-authz
    ``require_scope``. Returns ``(app, transport)``."""

    transport = _CountingTransport(introspection_handler)
    http = httpx.AsyncClient(transport=transport)
    intro_client = IntrospectionClient(
        introspection_url=introspection_url,
        client_id="bsgateway",
        client_secret="shh",
        http=http,
    )

    app = create_app()
    pool, _ = make_mock_pool()
    app.state.db_pool = pool
    app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    app.state.auth_provider = MagicMock()
    app.state.redis = None

    # Drop the autouse fake bsvibe-authz user so the real dispatch
    # (header → introspect / JWT) drives ``require_scope``.
    app.dependency_overrides.pop(authz_get_current_user, None)

    # bsvibe-authz Settings + introspection client overrides — these
    # feed ``bsvibe_authz.deps.get_current_user`` exactly the same
    # introspection_url the BSGateway dispatch sees.
    authz_settings = AuthzSettings.model_construct(
        bsvibe_auth_url="https://auth.example",
        openfga_api_url="https://fga.example",
        openfga_store_id="store",
        openfga_auth_model_id="model",
        openfga_auth_token=None,
        service_token_signing_secret="x",
        introspection_url=introspection_url,
        introspection_client_id="bsgateway",
        introspection_client_secret="shh",
    )
    app.dependency_overrides[authz_get_settings_dep] = lambda: authz_settings
    app.dependency_overrides[authz_get_introspection_client] = lambda: intro_client

    # BSGateway dispatch reads ``gateway_settings`` directly. Patch the
    # singleton's relevant fields and pin the introspection client so
    # call counts coalesce on a single transport.
    from bsgateway.api import deps as gw_deps

    gw_deps.gateway_settings.introspection_url = introspection_url
    gw_deps.gateway_settings.introspection_client_id = "bsgateway"
    gw_deps.gateway_settings.introspection_client_secret = "shh"
    gw_deps._introspection_client_singleton = intro_client

    return app, transport


# ---------------------------------------------------------------------------
# (a) opaque token — scope enforcement via real introspection
# ---------------------------------------------------------------------------


def _opaque_active_handler(tenant_id: str, scope: list[str]):
    payload = {
        "active": True,
        "sub": "user-123",
        "tenant": tenant_id,
        "scope": scope,
    }

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(payload).encode())

    return _handler


def test_opaque_read_scope_allows_get_models_and_blocks_post() -> None:
    tid = uuid4()
    handler = _opaque_active_handler(str(tid), ["gateway:models:read"])
    app, _ = _build_app(introspection_handler=handler)
    client = TestClient(app, raise_server_exceptions=False)

    with (
        patch(
            "bsgateway.tenant.repository.TenantRepository.get_tenant",
            new_callable=AsyncMock,
            return_value=_tenant_row(tid),
        ),
        patch("bsgateway.api.routers.tenants.get_tenant_service") as svc_factory,
    ):
        svc_factory.return_value.list_models = AsyncMock(return_value=[])
        get_resp = client.get(
            f"/api/v1/tenants/{tid}/models",
            headers={"Authorization": "Bearer bsv_sk_readonly"},
        )

    assert get_resp.status_code == 200, get_resp.text

    with patch(
        "bsgateway.tenant.repository.TenantRepository.get_tenant",
        new_callable=AsyncMock,
        return_value=_tenant_row(tid),
    ):
        post_resp = client.post(
            f"/api/v1/tenants/{tid}/models",
            json={
                "model_name": "gpt-foo",
                "litellm_model": "openai/gpt-foo",
                "is_active": True,
            },
            headers={"Authorization": "Bearer bsv_sk_readonly"},
        )

    assert post_resp.status_code == 403, post_resp.text
    assert "gateway:models:write" in post_resp.text


# ---------------------------------------------------------------------------
# (b) opaque token — inactive
# ---------------------------------------------------------------------------


def test_opaque_inactive_token_returns_401() -> None:
    def _inactive(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"active": False}).encode())

    app, _ = _build_app(introspection_handler=_inactive)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get(
        "/api/v1/tenants",
        headers={"Authorization": "Bearer bsv_sk_revoked"},
    )

    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# (c) JWT path preserved
# ---------------------------------------------------------------------------


def test_jwt_path_unchanged() -> None:
    """Non-prefixed bearer tokens flow through bsvibe-authz's user-JWT path.

    Post-PR-22 the lib supports JWKS-based verification, so the dispatch
    is fully delegated. We stub ``_authz_get_current_user`` to return a
    user (rather than wiring up a real signing key + token) and assert
    the introspection path is *not* taken — JWTs must verify locally.
    """
    from bsgateway.tests.conftest import _fake_authz_user, make_authz_user

    tid = uuid4()
    user = make_authz_user(tenant_id=tid, role="admin")

    def _never(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("introspection must not be called for JWT")

    app, transport = _build_app(introspection_handler=_never)
    # Re-install the conftest fake authz user for the require_scope chain
    # (the autouse override is popped in _build_app).
    app.dependency_overrides[authz_get_current_user] = _fake_authz_user

    with (
        patch(
            "bsgateway.api.deps._authz_get_current_user",
            new=AsyncMock(return_value=user),
        ) as mock_authz,
        patch(
            "bsgateway.tenant.repository.TenantRepository.get_tenant",
            new_callable=AsyncMock,
            return_value=_tenant_row(tid),
        ),
        patch(
            "bsgateway.tenant.repository.TenantRepository.list_tenants",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/v1/tenants",
            headers={"Authorization": "Bearer eyJhbGciOiJFUzI1NiJ9.fake.jwt"},
        )

    assert resp.status_code == 200, resp.text
    mock_authz.assert_called_once()
    assert transport.call_count == 0
