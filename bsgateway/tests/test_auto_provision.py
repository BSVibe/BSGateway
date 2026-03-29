"""Tests for tenant auto-provisioning on first JWT access."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.tests.conftest import make_bsvibe_user, make_mock_pool

ENCRYPTION_KEY_HEX = os.urandom(32).hex()


@pytest.fixture
def mock_pool():
    pool, _conn = make_mock_pool()
    return pool


def _make_tenant_row(
    tenant_id=None,
    name="Auto Tenant",
    slug="auto-tenant",
    is_active=True,
):
    now = datetime.now(UTC)
    return {
        "id": tenant_id or uuid4(),
        "name": name,
        "slug": slug,
        "is_active": is_active,
        "settings": "{}",
        "created_at": now,
        "updated_at": now,
    }


class TestAutoProvision:
    """Tenant should be auto-created on first JWT access."""

    def test_new_tenant_auto_created(self, mock_pool):
        """JWT with unknown tenant_id auto-creates the tenant."""
        tid = uuid4()
        user = make_bsvibe_user(tenant_id=tid, role="admin")
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        app.state.auth_provider = AsyncMock()
        app.state.auth_provider.verify_token = AsyncMock(return_value=user)
        client = TestClient(app, raise_server_exceptions=False)

        # get_tenant returns None (new tenant)
        # create_tenant returns a new row
        # second get_tenant (for the endpoint) returns the row
        created_row = _make_tenant_row(tenant_id=tid, name=str(tid)[:8], slug=str(tid)[:8])

        with (
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_tenant",
                new_callable=AsyncMock,
                side_effect=[None, created_row],
            ),
            patch(
                "bsgateway.tenant.repository.TenantRepository.provision_tenant",
                new_callable=AsyncMock,
                return_value=created_row,
            ) as mock_create,
        ):
            resp = client.get(
                f"/api/v1/tenants/{tid}",
                headers={"Authorization": "Bearer eyJfake.jwt.token"},
            )

        # Should succeed, not 403
        assert resp.status_code == 200
        mock_create.assert_called_once()

    def test_deactivated_tenant_still_blocked(self, mock_pool):
        """Explicitly deactivated tenant still gets 403."""
        tid = uuid4()
        user = make_bsvibe_user(tenant_id=tid, role="admin")
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        app.state.auth_provider = AsyncMock()
        app.state.auth_provider.verify_token = AsyncMock(return_value=user)
        client = TestClient(app, raise_server_exceptions=False)

        deactivated_row = _make_tenant_row(tenant_id=tid, is_active=False)

        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_tenant",
            new_callable=AsyncMock,
            return_value=deactivated_row,
        ):
            resp = client.get(
                f"/api/v1/tenants/{tid}",
                headers={"Authorization": "Bearer eyJfake.jwt.token"},
            )

        assert resp.status_code == 403
        assert "deactivated" in resp.json()["detail"].lower()

    def test_existing_active_tenant_no_create(self, mock_pool):
        """Existing active tenant does not trigger create."""
        tid = uuid4()
        user = make_bsvibe_user(tenant_id=tid, role="admin")
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        app.state.auth_provider = AsyncMock()
        app.state.auth_provider.verify_token = AsyncMock(return_value=user)
        client = TestClient(app, raise_server_exceptions=False)

        existing_row = _make_tenant_row(tenant_id=tid)

        with (
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_tenant",
                new_callable=AsyncMock,
                return_value=existing_row,
            ),
            patch(
                "bsgateway.tenant.repository.TenantRepository.provision_tenant",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            resp = client.get(
                f"/api/v1/tenants/{tid}",
                headers={"Authorization": "Bearer eyJfake.jwt.token"},
            )

        assert resp.status_code == 200
        mock_create.assert_not_called()

    def test_apikey_auth_does_not_auto_provision(self, mock_pool):
        """API key auth for non-existent tenant returns 401 (no auto-create)."""
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        app.state.auth_provider = AsyncMock()
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "bsgateway.apikey.service.ApiKeyService.validate_key",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(
                f"/api/v1/tenants/{uuid4()}/api-keys",
                headers={"Authorization": "Bearer bsg_live_" + "a" * 64},
            )

        assert resp.status_code == 401
