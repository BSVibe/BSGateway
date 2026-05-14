"""Tests for BSVibe-Auth integration in get_auth_context.

The dispatch is fully delegated to ``bsvibe_authz.deps.get_current_user``
since BSGateway #46 + bsvibe-python #22. Tests stub
``bsgateway.api.deps._authz_get_current_user`` (the local alias) to
control the user the lib returns; ``get_auth_context`` then runs its
translation + tenant active-check + auto-provision logic on top.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from bsvibe_authz import User as AuthzUser
from bsvibe_authz.deps import get_current_user as authz_get_current_user
from fastapi import HTTPException
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.api.deps import get_auth_context
from bsgateway.tests.conftest import make_authz_user, make_gateway_auth_context, make_mock_pool


def _scopeless_authz_user() -> AuthzUser:
    return AuthzUser(
        id="00000000-0000-0000-0000-000000000003",
        email="member@test.com",
        active_tenant_id=str(TENANT_ID),
        tenants=[],
        is_service=False,
        scope=[],
    )


ENCRYPTION_KEY_HEX = os.urandom(32).hex()
TENANT_ID = uuid4()


def _make_app():
    app = create_app()
    pool, _conn = make_mock_pool()
    app.state.db_pool = pool
    app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    app.state.auth_provider = MagicMock()
    app.state.redis = None
    return app


def _tenant_row(tenant_id=None, is_active=True):
    now = datetime.now(UTC)
    return {
        "id": tenant_id or TENANT_ID,
        "name": "Test Tenant",
        "slug": "test-tenant",
        "is_active": is_active,
        "settings": "{}",
        "created_at": now,
        "updated_at": now,
    }


def _patch_authz_user(user):
    return patch(
        "bsgateway.api.deps._authz_get_current_user",
        new=AsyncMock(return_value=user),
    )


def _patch_authz_raises(exc):
    return patch(
        "bsgateway.api.deps._authz_get_current_user",
        new=AsyncMock(side_effect=exc),
    )


class TestBSVibeAuth:
    def test_valid_token_returns_context(self):
        app = _make_app()
        user = make_authz_user(tenant_id=TENANT_ID, role="admin")

        with (
            _patch_authz_user(user),
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_tenant",
                new_callable=AsyncMock,
                return_value=_tenant_row(TENANT_ID),
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_missing_auth_header_returns_401(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "bsgateway.tenant.repository.TenantRepository.list_tenants",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/v1/tenants")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self):
        app = _make_app()
        with _patch_authz_raises(HTTPException(status_code=401, detail="bad token")):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer bad-token"},
            )
        assert resp.status_code == 401

    def test_expired_token_returns_401(self):
        app = _make_app()
        with _patch_authz_raises(HTTPException(status_code=401, detail="expired token")):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer expired-token"},
            )
        assert resp.status_code == 401

    def test_no_tenant_id_admin_still_works(self):
        """User with no tenant claim (e.g. tenant-less admin) → context with
        zero-UUID tenant_id, admin flag derives from app_metadata.role.

        The legacy "no tenant_id → 401" behavior was a forced check; the
        delegate model lets cross-tenant admins pass through.
        """
        app = _make_app()
        user = AuthzUser(
            id=str(uuid4()),
            email="admin@test.com",
            active_tenant_id=None,
            tenants=[],
            is_service=False,
            scope=[],
            app_metadata={"role": "admin"},
        )

        with (
            _patch_authz_user(user),
            patch(
                "bsgateway.tenant.repository.TenantRepository.list_tenants",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert resp.status_code == 200

    def test_inactive_tenant_returns_403(self):
        app = _make_app()
        user = make_authz_user(tenant_id=TENANT_ID, role="admin")

        with (
            _patch_authz_user(user),
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_tenant",
                new_callable=AsyncMock,
                return_value=_tenant_row(TENANT_ID, is_active=False),
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert resp.status_code == 403

    def test_admin_role_detected(self):
        app = _make_app()
        user = make_authz_user(tenant_id=TENANT_ID, role="admin")

        with (
            _patch_authz_user(user),
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_tenant",
                new_callable=AsyncMock,
                return_value=_tenant_row(TENANT_ID),
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
                headers={"Authorization": "Bearer valid-token"},
            )
        assert resp.status_code == 200

    def test_non_admin_cannot_list_tenants(self):
        """Phase 1 cutover: scopeless principal → 403 from ``require_scope``.

        The legacy "member-role JWT can't list tenants" gate was role-based
        (``require_admin``). Post-cutover the gate is scope-based; the
        member's JWT carries no ``gateway:tenants:read`` so the
        ``bsvibe_authz.require_scope`` chain rejects.
        """
        app = _make_app()
        user = make_authz_user(tenant_id=TENANT_ID, role="member")
        app.dependency_overrides[authz_get_current_user] = _scopeless_authz_user

        with (
            _patch_authz_user(user),
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_tenant",
                new_callable=AsyncMock,
                return_value=_tenant_row(TENANT_ID),
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert resp.status_code == 403
        assert "gateway:tenants:read" in resp.json()["detail"]

    def test_tenant_access_own_data(self):
        app = _make_app()
        user = make_authz_user(tenant_id=TENANT_ID, role="member")

        with (
            _patch_authz_user(user),
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_tenant",
                new_callable=AsyncMock,
                return_value=_tenant_row(TENANT_ID),
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                f"/api/v1/tenants/{TENANT_ID}",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert resp.status_code == 200

    def test_tenant_cannot_access_other_tenant(self):
        other_tid = uuid4()
        app = _make_app()
        user = make_authz_user(tenant_id=TENANT_ID, role="member")

        with (
            _patch_authz_user(user),
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_tenant",
                new_callable=AsyncMock,
                return_value=_tenant_row(TENANT_ID),
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                f"/api/v1/tenants/{other_tid}",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert resp.status_code == 403

    def test_admin_can_access_any_tenant(self):
        other_tid = uuid4()
        app = _make_app()
        user = make_authz_user(tenant_id=TENANT_ID, role="admin")

        with (
            _patch_authz_user(user),
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_tenant",
                new_callable=AsyncMock,
                return_value=_tenant_row(TENANT_ID),
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                f"/api/v1/tenants/{other_tid}",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert resp.status_code == 200


class TestDependencyOverridePattern:
    """Verify the dependency override pattern works for all test files."""

    def test_override_get_auth_context(self):
        app = _make_app()
        ctx = make_gateway_auth_context(tenant_id=TENANT_ID, is_admin=True)
        app.dependency_overrides[get_auth_context] = lambda: ctx

        with patch(
            "bsgateway.tenant.repository.TenantRepository.list_tenants",
            new_callable=AsyncMock,
            return_value=[],
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/tenants")
        assert resp.status_code == 200
