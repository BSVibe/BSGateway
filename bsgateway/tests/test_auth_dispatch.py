"""Phase 1 token-cutover — bsvibe-authz 3-way dispatch in get_auth_context.

Verifies the new contract:

- ``bsv_admin_*`` → bootstrap path (constant-time hash compare via
  ``bsvibe_authz.verify_bootstrap_token``). Match → admin
  :class:`GatewayAuthContext` with scope ``["*"]``. Mismatch / unconfigured
  → 401.
- ``bsv_sk_*`` → RFC 7662 opaque-token introspection (cached). Active
  response → context with scope from the introspection payload. Inactive
  / unconfigured ``introspection_url`` → 401.
- everything else → existing JWT path via ``app.state.auth_provider``.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from bsvibe_authz import IntrospectionResponse
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.tests.conftest import make_mock_pool

ENCRYPTION_KEY_HEX = os.urandom(32).hex()


def _tenant_row(tenant_id, is_active: bool = True):
    now = datetime.now(UTC)
    return {
        "id": tenant_id,
        "name": "Test",
        "slug": "test",
        "is_active": is_active,
        "settings": "{}",
        "created_at": now,
        "updated_at": now,
    }


@pytest.fixture
def app():
    app = create_app()
    pool, _conn = make_mock_pool()
    app.state.db_pool = pool
    app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    app.state.auth_provider = MagicMock()
    app.state.redis = None
    return app


@pytest.fixture(autouse=True)
def _reset_dispatch_singletons():
    """Each test gets fresh introspection client + cache singletons."""
    from bsgateway.api import deps

    deps._reset_dispatch_singletons()
    yield
    deps._reset_dispatch_singletons()


@pytest.fixture
def patch_settings(monkeypatch):
    """Helper: monkeypatch fields on the live BSGateway settings singleton."""

    from bsgateway.api import deps as _deps

    def _apply(**fields):
        for key, value in fields.items():
            monkeypatch.setattr(_deps.gateway_settings, key, value)

    return _apply


class TestBootstrapDispatch:
    def test_bootstrap_token_match_grants_admin_context(self, app, patch_settings):
        token = "bsv_admin_" + "x" * 32
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        patch_settings(bootstrap_token_hash=token_hash)

        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "bsgateway.tenant.repository.TenantRepository.list_tenants",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200, resp.text

    def test_bootstrap_token_mismatch_returns_401(self, app, patch_settings):
        # Hash is set, but the supplied token doesn't match.
        patch_settings(
            bootstrap_token_hash=hashlib.sha256(b"different").hexdigest(),
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            "/api/v1/tenants",
            headers={"Authorization": "Bearer bsv_admin_" + "y" * 32},
        )

        assert resp.status_code == 401

    def test_bootstrap_path_disabled_when_hash_unset(self, app, patch_settings):
        patch_settings(bootstrap_token_hash="")
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            "/api/v1/tenants",
            headers={"Authorization": "Bearer bsv_admin_anything"},
        )

        assert resp.status_code == 401


class TestOpaqueDispatch:
    def test_opaque_token_active_grants_context(self, app, patch_settings):
        tid = uuid4()
        patch_settings(
            introspection_url="https://auth.example/introspect",
            introspection_client_id="bsgateway",
            introspection_client_secret="shh",
        )
        client = TestClient(app, raise_server_exceptions=False)

        active_response = IntrospectionResponse(
            active=True,
            sub="user-123",
            tenant=str(tid),
            scope=["gateway:tenants:read"],
        )

        with (
            patch(
                "bsvibe_authz.IntrospectionClient.introspect",
                new_callable=AsyncMock,
                return_value=active_response,
            ),
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_tenant",
                new_callable=AsyncMock,
                return_value=_tenant_row(tid),
            ),
        ):
            resp = client.get(
                f"/api/v1/tenants/{tid}",
                headers={"Authorization": "Bearer bsv_sk_abcdef"},
            )

        assert resp.status_code == 200, resp.text

    def test_opaque_token_inactive_returns_401(self, app, patch_settings):
        patch_settings(
            introspection_url="https://auth.example/introspect",
            introspection_client_id="bsgateway",
            introspection_client_secret="shh",
        )
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "bsvibe_authz.IntrospectionClient.introspect",
            new_callable=AsyncMock,
            return_value=IntrospectionResponse(active=False),
        ):
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer bsv_sk_revoked"},
            )

        assert resp.status_code == 401

    def test_opaque_path_disabled_when_url_unset(self, app, patch_settings):
        patch_settings(introspection_url="")
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            "/api/v1/tenants",
            headers={"Authorization": "Bearer bsv_sk_anything"},
        )

        assert resp.status_code == 401


class TestJwtPathPreserved:
    def test_jwt_path_unchanged(self, app):
        """Non-prefixed bearer tokens flow through bsvibe-authz's user-JWT
        path (now JWKS-based — see bsvibe-python #22). The legacy
        ``app.state.auth_provider`` was removed in BSGateway #46-followup;
        the dispatch is fully delegated to ``get_current_user``.
        """
        from bsgateway.tests.conftest import make_authz_user

        tid = uuid4()
        user = make_authz_user(tenant_id=tid, role="admin")

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

        assert resp.status_code == 200
        mock_authz.assert_called_once()
