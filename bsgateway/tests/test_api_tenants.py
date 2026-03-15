"""Tests for the tenant API endpoints.

Uses FastAPI TestClient with mocked database pool.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.core.security import hash_api_key

SUPERADMIN_KEY = "test-superadmin-key"
ENCRYPTION_KEY_HEX = os.urandom(32).hex()


@pytest.fixture
def mock_pool() -> AsyncMock:
    """Create a mock asyncpg pool."""
    pool = AsyncMock()
    pool._closed = False
    # Mock connection context manager
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.fixture
def app(mock_pool: AsyncMock):
    """Create a FastAPI app with mocked dependencies."""
    app = create_app()
    app.state.db_pool = mock_pool
    app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    app.state.superadmin_key_hash = hash_api_key(SUPERADMIN_KEY)
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_headers() -> dict:
    return {"Authorization": f"Bearer {SUPERADMIN_KEY}"}


def _make_tenant_row(
    tenant_id: UUID | None = None,
    name: str = "Acme Corp",
    slug: str = "acme",
) -> dict:
    now = datetime.now(UTC)
    return {
        "id": tenant_id or uuid4(),
        "name": name,
        "slug": slug,
        "is_active": True,
        "settings": "{}",
        "created_at": now,
        "updated_at": now,
    }


class TestTenantAuth:
    def test_no_auth_returns_401(self, client: TestClient):
        resp = client.get("/api/v1/tenants")
        assert resp.status_code == 401

    def test_invalid_auth_returns_401(self, client: TestClient):
        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_api_key_by_hash",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer wrong-key"},
            )
            assert resp.status_code == 401

    def test_superadmin_auth_works(self, client: TestClient, admin_headers: dict):
        with patch(
            "bsgateway.tenant.repository.TenantRepository.list_tenants",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/v1/tenants", headers=admin_headers)
            assert resp.status_code == 200

    def test_expired_api_key_returns_401(self, client: TestClient):
        expired_at = datetime.now(UTC) - timedelta(hours=1)
        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_api_key_by_hash",
            new_callable=AsyncMock,
            return_value={
                "id": uuid4(),
                "tenant_id": uuid4(),
                "key_hash": "fakehash",
                "key_prefix": "bsg_test1234",
                "name": "expired-key",
                "scopes": ["admin"],
                "is_active": True,
                "expires_at": expired_at,
                "last_used_at": None,
                "created_at": datetime.now(UTC),
                "tenant_is_active": True,
            },
        ):
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer some-tenant-key"},
            )
            assert resp.status_code == 401
            assert "expired" in resp.json()["detail"].lower()

    def test_non_expired_api_key_works(self, client: TestClient):
        tid = uuid4()
        future = datetime.now(UTC) + timedelta(hours=24)
        with (
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_api_key_by_hash",
                new_callable=AsyncMock,
                return_value={
                    "id": uuid4(),
                    "tenant_id": tid,
                    "key_hash": "fakehash",
                    "key_prefix": "bsg_test1234",
                    "name": "valid-key",
                    "scopes": ["admin"],
                    "is_active": True,
                    "expires_at": future,
                    "last_used_at": None,
                    "created_at": datetime.now(UTC),
                    "tenant_is_active": True,
                },
            ),
            patch(
                "bsgateway.tenant.repository.TenantRepository.touch_api_key",
                new_callable=AsyncMock,
            ),
            patch(
                "bsgateway.tenant.repository.TenantRepository.list_tenants",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer some-tenant-key"},
            )
            assert resp.status_code == 200


class TestTenantCRUD:
    def test_create_tenant(self, client: TestClient, admin_headers: dict):
        row = _make_tenant_row()
        with patch(
            "bsgateway.tenant.repository.TenantRepository.create_tenant",
            new_callable=AsyncMock,
            return_value=row,
        ):
            resp = client.post(
                "/api/v1/tenants",
                json={"name": "Acme Corp", "slug": "acme"},
                headers=admin_headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["name"] == "Acme Corp"
            assert data["slug"] == "acme"
            assert data["is_active"] is True

    def test_create_tenant_invalid_slug(self, client: TestClient, admin_headers: dict):
        resp = client.post(
            "/api/v1/tenants",
            json={"name": "Test", "slug": "Invalid Slug!"},
            headers=admin_headers,
        )
        assert resp.status_code == 422  # Validation error

    def test_list_tenants(self, client: TestClient, admin_headers: dict):
        rows = [_make_tenant_row(), _make_tenant_row(name="Beta", slug="beta")]
        with patch(
            "bsgateway.tenant.repository.TenantRepository.list_tenants",
            new_callable=AsyncMock,
            return_value=rows,
        ):
            resp = client.get("/api/v1/tenants", headers=admin_headers)
            assert resp.status_code == 200
            assert len(resp.json()) == 2

    def test_get_tenant(self, client: TestClient, admin_headers: dict):
        tid = uuid4()
        row = _make_tenant_row(tenant_id=tid)
        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_tenant",
            new_callable=AsyncMock,
            return_value=row,
        ):
            resp = client.get(f"/api/v1/tenants/{tid}", headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["id"] == str(tid)

    def test_get_tenant_not_found(self, client: TestClient, admin_headers: dict):
        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_tenant",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(f"/api/v1/tenants/{uuid4()}", headers=admin_headers)
            assert resp.status_code == 404

    def test_deactivate_tenant(self, client: TestClient, admin_headers: dict):
        with patch(
            "bsgateway.tenant.repository.TenantRepository.deactivate_tenant",
            new_callable=AsyncMock,
        ):
            resp = client.delete(f"/api/v1/tenants/{uuid4()}", headers=admin_headers)
            assert resp.status_code == 204


class TestApiKeyEndpoints:
    def test_create_api_key(self, client: TestClient, admin_headers: dict):
        tid = uuid4()
        now = datetime.now(UTC)
        with (
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_tenant",
                new_callable=AsyncMock,
                return_value=_make_tenant_row(tenant_id=tid),
            ),
            patch(
                "bsgateway.tenant.repository.TenantRepository.create_api_key",
                new_callable=AsyncMock,
                return_value={
                    "id": uuid4(),
                    "tenant_id": tid,
                    "key_prefix": "bsg_abcd1234",
                    "name": "prod",
                    "scopes": ["read"],
                    "is_active": True,
                    "expires_at": None,
                    "last_used_at": None,
                    "created_at": now,
                },
            ),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/keys",
                json={"name": "prod", "scopes": ["read"]},
                headers=admin_headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["key"].startswith("bsg_")
            assert data["name"] == "prod"

    def test_create_api_key_tenant_not_found(self, client: TestClient, admin_headers: dict):
        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_tenant",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                f"/api/v1/tenants/{uuid4()}/keys",
                json={"name": "test"},
                headers=admin_headers,
            )
            assert resp.status_code == 404
            assert "Tenant not found" in resp.json()["detail"]

    def test_list_api_keys(self, client: TestClient, admin_headers: dict):
        tid = uuid4()
        with patch(
            "bsgateway.tenant.repository.TenantRepository.list_api_keys",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": uuid4(),
                    "tenant_id": tid,
                    "key_prefix": "bsg_abcd1234",
                    "name": "test",
                    "scopes": [],
                    "is_active": True,
                    "expires_at": None,
                    "last_used_at": None,
                    "created_at": datetime.now(UTC),
                }
            ],
        ):
            resp = client.get(f"/api/v1/tenants/{tid}/keys", headers=admin_headers)
            assert resp.status_code == 200
            assert len(resp.json()) == 1
            # Verify plaintext key is NOT returned in list
            assert "key" not in resp.json()[0]

    def test_revoke_api_key(self, client: TestClient, admin_headers: dict):
        with patch(
            "bsgateway.tenant.repository.TenantRepository.revoke_api_key",
            new_callable=AsyncMock,
        ):
            resp = client.delete(
                f"/api/v1/tenants/{uuid4()}/keys/{uuid4()}",
                headers=admin_headers,
            )
            assert resp.status_code == 204


class TestCrossTenantAccess:
    """Test that a tenant cannot access another tenant's resources."""

    def test_deactivated_tenant_returns_403(self, client: TestClient):
        tid = uuid4()
        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_api_key_by_hash",
            new_callable=AsyncMock,
            return_value={
                "id": uuid4(),
                "tenant_id": tid,
                "key_hash": "fakehash",
                "key_prefix": "bsg_test1234",
                "name": "key",
                "scopes": ["admin"],
                "is_active": True,
                "expires_at": None,
                "last_used_at": None,
                "created_at": datetime.now(UTC),
                "tenant_is_active": False,
            },
        ):
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer tenant-key"},
            )
            assert resp.status_code == 403

    def test_non_admin_scope_returns_403(self, client: TestClient):
        tid = uuid4()
        with (
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_api_key_by_hash",
                new_callable=AsyncMock,
                return_value={
                    "id": uuid4(),
                    "tenant_id": tid,
                    "key_hash": "fakehash",
                    "key_prefix": "bsg_test1234",
                    "name": "key",
                    "scopes": ["read"],  # no admin scope
                    "is_active": True,
                    "expires_at": None,
                    "last_used_at": None,
                    "created_at": datetime.now(UTC),
                    "tenant_is_active": True,
                },
            ),
            patch(
                "bsgateway.tenant.repository.TenantRepository.touch_api_key",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.get(
                "/api/v1/tenants",
                headers={"Authorization": "Bearer tenant-key"},
            )
            assert resp.status_code == 403
            assert "Admin scope required" in resp.json()["detail"]


class TestModelEndpoints:
    def test_create_model(self, client: TestClient, admin_headers: dict):
        tid = uuid4()
        now = datetime.now(UTC)
        with patch(
            "bsgateway.tenant.repository.TenantRepository.create_model",
            new_callable=AsyncMock,
            return_value={
                "id": uuid4(),
                "tenant_id": tid,
                "model_name": "my-gpt4",
                "provider": "openai",
                "litellm_model": "openai/gpt-4o",
                "api_base": None,
                "is_active": True,
                "extra_params": "{}",
                "created_at": now,
                "updated_at": now,
            },
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/models",
                json={
                    "model_name": "my-gpt4",
                    "provider": "openai",
                    "litellm_model": "openai/gpt-4o",
                    "api_key": "sk-test-key",
                },
                headers=admin_headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["model_name"] == "my-gpt4"
            # API key should NOT be returned
            assert "api_key" not in data
            assert "api_key_encrypted" not in data

    def test_list_models(self, client: TestClient, admin_headers: dict):
        tid = uuid4()
        now = datetime.now(UTC)
        with patch(
            "bsgateway.tenant.repository.TenantRepository.list_models",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": uuid4(),
                    "tenant_id": tid,
                    "model_name": "my-gpt4",
                    "provider": "openai",
                    "litellm_model": "openai/gpt-4o",
                    "api_base": None,
                    "is_active": True,
                    "extra_params": "{}",
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        ):
            resp = client.get(f"/api/v1/tenants/{tid}/models", headers=admin_headers)
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    def test_delete_model(self, client: TestClient, admin_headers: dict):
        with patch(
            "bsgateway.tenant.repository.TenantRepository.delete_model",
            new_callable=AsyncMock,
        ):
            resp = client.delete(
                f"/api/v1/tenants/{uuid4()}/models/{uuid4()}",
                headers=admin_headers,
            )
            assert resp.status_code == 204
