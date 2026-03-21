"""Tests for POST /api/v1/auth/token endpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bsgateway.core.security import hash_api_key

TEST_API_KEY = "bsg_test-key-for-auth"
TEST_KEY_HASH = hash_api_key(TEST_API_KEY)


@pytest.fixture()
def _app():
    from bsgateway.api.app import create_app

    app = create_app()
    app.state.db_pool = MagicMock()
    app.state.encryption_key = b"\x00" * 32
    app.state.superadmin_key_hash = ""
    app.state.jwt_secret = "test-jwt-secret-that-is-long-enough"
    app.state.redis = None
    return app


@pytest.fixture()
def client(_app):
    return TestClient(_app, raise_server_exceptions=False)


def _make_key_row(
    tenant_id=None,
    is_active=True,
    tenant_is_active=True,
    scopes=None,
    expires_at=None,
    tenant_name="Test Tenant",
    tenant_slug="test-tenant",
):
    tid = tenant_id or uuid4()
    row = {
        "id": uuid4(),
        "tenant_id": tid,
        "key_hash": TEST_KEY_HASH,
        "key_prefix": "bsg_test1234",
        "name": "default",
        "scopes": scopes or ["chat", "admin"],
        "is_active": is_active,
        "expires_at": expires_at,
        "last_used_at": None,
        "created_at": datetime.now(UTC),
        "tenant_is_active": tenant_is_active,
        "tenant_name": tenant_name,
        "tenant_slug": tenant_slug,
    }
    return row


@pytest.fixture(autouse=True)
def _reset_auth_rate_limiter():
    """Ensure auth rate limiter state is clean between tests."""
    from bsgateway.api.routers import auth as auth_module

    auth_module._auth_attempts.clear()
    yield
    auth_module._auth_attempts.clear()


class TestAuthToken:
    """POST /api/v1/auth/token"""

    def test_valid_key_returns_token(self, client):
        row = _make_key_row()
        with patch("bsgateway.api.routers.auth.TenantRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.get_api_key_by_hash = AsyncMock(return_value=row)
            repo.touch_api_key = AsyncMock()

            res = client.post("/api/v1/auth/token", json={"api_key": TEST_API_KEY})

        assert res.status_code == 200
        body = res.json()
        assert "token" in body
        assert body["tenant_id"] == str(row["tenant_id"])
        assert body["tenant_slug"] == "test-tenant"
        assert body["tenant_name"] == "Test Tenant"
        assert body["scopes"] == ["chat", "admin"]

    def test_invalid_key_returns_401(self, client):
        with patch("bsgateway.api.routers.auth.TenantRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.get_api_key_by_hash = AsyncMock(return_value=None)

            res = client.post("/api/v1/auth/token", json={"api_key": "bsg_bad"})

        assert res.status_code == 401

    def test_expired_key_returns_401(self, client):
        row = _make_key_row(expires_at=datetime.now(UTC) - timedelta(hours=1))
        with patch("bsgateway.api.routers.auth.TenantRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.get_api_key_by_hash = AsyncMock(return_value=row)

            res = client.post("/api/v1/auth/token", json={"api_key": TEST_API_KEY})

        assert res.status_code == 401

    def test_inactive_key_returns_401(self, client):
        row = _make_key_row(is_active=False)
        with patch("bsgateway.api.routers.auth.TenantRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.get_api_key_by_hash = AsyncMock(return_value=row)

            res = client.post("/api/v1/auth/token", json={"api_key": TEST_API_KEY})

        assert res.status_code == 401

    def test_deactivated_tenant_returns_403(self, client):
        row = _make_key_row(tenant_is_active=False)
        with patch("bsgateway.api.routers.auth.TenantRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.get_api_key_by_hash = AsyncMock(return_value=row)

            res = client.post("/api/v1/auth/token", json={"api_key": TEST_API_KEY})

        assert res.status_code == 403

    def test_missing_api_key_returns_422(self, client):
        res = client.post("/api/v1/auth/token", json={})
        assert res.status_code == 422

    def test_empty_api_key_returns_422(self, client):
        res = client.post("/api/v1/auth/token", json={"api_key": ""})
        assert res.status_code == 422

    def test_invalid_prefix_returns_422(self, client):
        """API key must start with bsg_ prefix."""
        res = client.post("/api/v1/auth/token", json={"api_key": "sk-some-key"})
        assert res.status_code == 422

    def test_rate_limit_blocks_after_threshold(self, client):
        """Auth endpoint rate limits at 10 req/min per IP."""
        with patch("bsgateway.api.routers.auth.TenantRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.get_api_key_by_hash = AsyncMock(return_value=None)

            for _ in range(10):
                client.post("/api/v1/auth/token", json={"api_key": TEST_API_KEY})

            res = client.post("/api/v1/auth/token", json={"api_key": TEST_API_KEY})

        assert res.status_code == 429
        assert "Too many" in res.json()["detail"]

    def test_token_is_valid_jwt(self, client):
        row = _make_key_row()
        with patch("bsgateway.api.routers.auth.TenantRepository") as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.get_api_key_by_hash = AsyncMock(return_value=row)
            repo.touch_api_key = AsyncMock()

            res = client.post("/api/v1/auth/token", json={"api_key": TEST_API_KEY})

        token = res.json()["token"]
        from bsgateway.core.security import decode_jwt

        payload = decode_jwt(token, "test-jwt-secret-that-is-long-enough")
        assert payload.tenant_id == str(row["tenant_id"])
        assert payload.scopes == ["chat", "admin"]
