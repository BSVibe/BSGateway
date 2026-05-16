"""Tests for the tenant API endpoints.

Uses FastAPI TestClient with dependency overrides for auth.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from bsvibe_authz import User as AuthzUser
from bsvibe_authz.deps import get_current_user as authz_get_current_user
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.api.deps import get_auth_context
from bsgateway.tests.conftest import make_gateway_auth_context, make_mock_pool


def _scopeless_authz_user() -> AuthzUser:
    """Authz user without admin scopes — used to assert ``require_scope`` 403s.

    The conftest auto-installs an ``authz_get_current_user`` override with
    ``scope=["*"]`` so that scope-less tests stay green. Tests that
    specifically exercise the scope gate clear that override and supply
    this scope-empty principal instead.
    """
    return AuthzUser(
        id="00000000-0000-0000-0000-000000000002",
        email="member@test.com",
        active_tenant_id="00000000-0000-0000-0000-0000000000aa",
        tenants=[],
        is_service=False,
        scope=[],
    )


ENCRYPTION_KEY_HEX = os.urandom(32).hex()
ADMIN_TENANT_ID = uuid4()


class _DenyFGA:
    """OpenFGA double that denies every check — drives ``require_admin``
    (OpenFGA-backed since bsvibe-authz 2.1.0) down its 403 branch."""

    async def check(self, *a: object, **k: object) -> bool:
        return False

    async def list_objects(self, *a: object, **k: object) -> list[str]:
        return []

    async def write_tuple(self, *a: object, **k: object) -> None:
        return None


@pytest.fixture
def mock_pool():
    """Create a mock asyncpg pool."""
    pool, _conn = make_mock_pool()
    return pool


@pytest.fixture
def app(mock_pool: AsyncMock):
    """Create a FastAPI app with mocked dependencies."""
    app = create_app()
    app.state.db_pool = mock_pool
    app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    app.state.redis = None
    # Override auth with admin context
    admin_ctx = make_gateway_auth_context(tenant_id=ADMIN_TENANT_ID, is_admin=True)
    app.dependency_overrides[get_auth_context] = lambda: admin_ctx
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


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
    def test_no_auth_returns_401(self, mock_pool):
        """Without dependency override, missing auth → 401."""
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.auth_provider = AsyncMock()
        app.state.redis = None
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/tenants")
        assert resp.status_code == 401

    def test_non_admin_returns_403(self, mock_pool):
        """Non-admin principal → 403 on genuine tenant-admin endpoints.

        ``GET /tenants`` is permissive ``require_permission`` (browser
        session JWT with ``scope=[]`` reaches the handler). ``POST
        /tenants`` gates on ``require_admin()`` — since bsvibe-authz 2.1.0
        an OpenFGA ``admin``-relation check (was the ``app_metadata.role``
        claim), permissive when OpenFGA is unconfigured. Prod wires
        OpenFGA (``deploy/.env``); this test points it at a deny FGA so
        the member genuinely 403s with ``admin role required``.
        """
        from bsvibe_authz import Settings as AuthzSettings
        from bsvibe_authz.deps import get_openfga_client, get_settings_dep

        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        member_ctx = make_gateway_auth_context(is_admin=False)
        app.dependency_overrides[get_auth_context] = lambda: member_ctx
        app.dependency_overrides[authz_get_current_user] = _scopeless_authz_user
        app.dependency_overrides[get_settings_dep] = lambda: AuthzSettings(
            openfga_api_url="http://openfga.test",
        )
        app.dependency_overrides[get_openfga_client] = lambda: _DenyFGA()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/tenants", json={"name": "t", "slug": "t"})
        assert resp.status_code == 403
        assert "admin role required" in resp.json()["detail"]

    def test_permissive_read_allows_non_admin_list_tenants(self, mock_pool):
        """Phase 2b: ``GET /tenants`` is now permissive — a browser session
        JWT with ``scope=[]`` and no admin role reaches the handler (200).

        This is the core fix: pure ``require_scope`` 403'd every dashboard
        request because the wrapped session JWT carries ``scope=[]``.
        """
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        member_ctx = make_gateway_auth_context(is_admin=False)
        app.dependency_overrides[get_auth_context] = lambda: member_ctx
        app.dependency_overrides[authz_get_current_user] = _scopeless_authz_user
        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "bsgateway.tenant.repository.TenantRepository.list_tenants",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/v1/tenants")
        assert resp.status_code == 200, resp.text


class TestTenantCRUD:
    def test_create_tenant(self, client: TestClient):
        row = _make_tenant_row()
        with patch(
            "bsgateway.tenant.repository.TenantRepository.create_tenant",
            new_callable=AsyncMock,
            return_value=row,
        ):
            resp = client.post(
                "/api/v1/tenants",
                json={"name": "Acme Corp", "slug": "acme"},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["name"] == "Acme Corp"
            assert data["slug"] == "acme"
            assert data["is_active"] is True

    def test_create_tenant_invalid_slug(self, client: TestClient):
        resp = client.post(
            "/api/v1/tenants",
            json={"name": "Test", "slug": "Invalid Slug!"},
        )
        assert resp.status_code == 422  # Validation error

    def test_list_tenants(self, client: TestClient):
        rows = [_make_tenant_row(), _make_tenant_row(name="Beta", slug="beta")]
        with patch(
            "bsgateway.tenant.repository.TenantRepository.list_tenants",
            new_callable=AsyncMock,
            return_value=rows,
        ):
            resp = client.get("/api/v1/tenants")
            assert resp.status_code == 200
            assert len(resp.json()) == 2

    def test_get_tenant(self, client: TestClient):
        tid = uuid4()
        row = _make_tenant_row(tenant_id=tid)
        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_tenant",
            new_callable=AsyncMock,
            return_value=row,
        ):
            resp = client.get(f"/api/v1/tenants/{tid}")
            assert resp.status_code == 200
            assert resp.json()["id"] == str(tid)

    def test_get_tenant_not_found(self, client: TestClient):
        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_tenant",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(f"/api/v1/tenants/{uuid4()}")
            assert resp.status_code == 404

    def test_deactivate_tenant(self, client: TestClient):
        with patch(
            "bsgateway.tenant.repository.TenantRepository.deactivate_tenant",
            new_callable=AsyncMock,
        ):
            resp = client.delete(f"/api/v1/tenants/{uuid4()}")
            assert resp.status_code == 204


class TestCrossTenantAccess:
    """Test that a tenant cannot access another tenant's resources."""

    def test_tenant_can_read_own_data(self, mock_pool):
        """A tenant with non-admin role can GET its own tenant record."""
        tid = uuid4()
        row = _make_tenant_row(tenant_id=tid)
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        member_ctx = make_gateway_auth_context(tenant_id=tid, is_admin=False)
        app.dependency_overrides[get_auth_context] = lambda: member_ctx
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_tenant",
            new_callable=AsyncMock,
            return_value=row,
        ):
            resp = client.get(f"/api/v1/tenants/{tid}")
            assert resp.status_code == 200
            assert resp.json()["id"] == str(tid)

    def test_tenant_cannot_read_other_tenant(self, mock_pool):
        """A tenant cannot GET another tenant's record."""
        own_tid = uuid4()
        other_tid = uuid4()
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        member_ctx = make_gateway_auth_context(tenant_id=own_tid, is_admin=False)
        app.dependency_overrides[get_auth_context] = lambda: member_ctx
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/api/v1/tenants/{other_tid}")
        assert resp.status_code == 403

    def test_tenant_cannot_update_other_tenant(self, mock_pool):
        """A non-admin principal cannot PATCH any tenant — ``require_admin`` blocks.

        Tenant administration (PATCH/DELETE ``/tenants/{id}``) gates on
        ``require_admin()`` — an OpenFGA ``admin``-relation check since
        bsvibe-authz 2.1.0, permissive when OpenFGA is unconfigured. This
        test points it at a deny FGA so the member 403s before the handler.
        """
        from bsvibe_authz import Settings as AuthzSettings
        from bsvibe_authz.deps import get_openfga_client, get_settings_dep

        own_tid = uuid4()
        other_tid = uuid4()
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        member_ctx = make_gateway_auth_context(tenant_id=own_tid, is_admin=False)
        app.dependency_overrides[get_auth_context] = lambda: member_ctx
        app.dependency_overrides[authz_get_current_user] = _scopeless_authz_user
        app.dependency_overrides[get_settings_dep] = lambda: AuthzSettings(
            openfga_api_url="http://openfga.test",
        )
        app.dependency_overrides[get_openfga_client] = lambda: _DenyFGA()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch(
            f"/api/v1/tenants/{other_tid}",
            json={"name": "Hacked"},
        )
        assert resp.status_code == 403

    def test_tenant_cannot_create_model_for_other_tenant(self, mock_pool):
        """A non-admin tenant cannot create models for other tenants."""
        own_tid = uuid4()
        other_tid = uuid4()
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        member_ctx = make_gateway_auth_context(tenant_id=own_tid, is_admin=False)
        app.dependency_overrides[get_auth_context] = lambda: member_ctx
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/v1/tenants/{other_tid}/models",
            json={
                "model_name": "stolen-model",
                "litellm_model": "openai/gpt-4o",
                "api_key": "sk-stolen",
            },
        )
        assert resp.status_code == 403


class TestModelEndpoints:
    def test_create_model(self, client: TestClient):
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
                    "litellm_model": "openai/gpt-4o",
                    "api_key": "sk-test-key",
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["model_name"] == "my-gpt4"
            # API key should NOT be returned
            assert "api_key" not in data
            assert "api_key_encrypted" not in data

    def test_list_models(self, client: TestClient):
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
            resp = client.get(f"/api/v1/tenants/{tid}/models")
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    def test_delete_model(self, client: TestClient):
        with patch(
            "bsgateway.tenant.repository.TenantRepository.delete_model",
            new_callable=AsyncMock,
        ):
            resp = client.delete(
                f"/api/v1/tenants/{uuid4()}/models/{uuid4()}",
            )
            assert resp.status_code == 204


class TestUpdateTenant:
    def test_update_tenant_not_found_on_get(self, client: TestClient):
        """PATCH tenant returns 404 when get_tenant finds nothing."""
        tid = uuid4()
        with patch(
            "bsgateway.tenant.service.TenantService.get_tenant",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.patch(
                f"/api/v1/tenants/{tid}",
                json={"name": "Updated"},
            )
        assert resp.status_code == 404
        assert "Tenant not found" in resp.json()["detail"]

    def test_update_tenant_not_found_on_update(self, client: TestClient):
        """PATCH tenant returns 404 when update_tenant returns None."""
        from bsgateway.tenant.models import TenantResponse

        tid = uuid4()
        now = datetime.now(UTC)
        existing = TenantResponse(
            id=tid,
            name="Acme",
            slug="acme",
            is_active=True,
            settings={},
            created_at=now,
            updated_at=now,
        )
        with (
            patch(
                "bsgateway.tenant.service.TenantService.get_tenant",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "bsgateway.tenant.service.TenantService.update_tenant",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = client.patch(
                f"/api/v1/tenants/{tid}",
                json={"name": "Updated"},
            )
        assert resp.status_code == 404
        assert "Tenant not found" in resp.json()["detail"]


class TestModelErrorCases:
    def test_create_model_duplicate_error(self, client: TestClient):
        """POST model returns 409 on DuplicateError."""
        from bsgateway.core.exceptions import DuplicateError

        tid = uuid4()
        with patch(
            "bsgateway.tenant.service.TenantService.create_model",
            new_callable=AsyncMock,
            side_effect=DuplicateError("Model name already exists"),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/models",
                json={
                    "model_name": "my-gpt4",
                    "litellm_model": "openai/gpt-4o",
                    "api_key": "sk-test",
                },
            )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_create_model_value_error(self, client: TestClient):
        """POST model returns 400 on ValueError."""
        tid = uuid4()
        with patch(
            "bsgateway.tenant.service.TenantService.create_model",
            new_callable=AsyncMock,
            side_effect=ValueError(
                "Unable to store API keys securely — encryption is not configured"
            ),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/models",
                json={
                    "model_name": "my-gpt4",
                    "litellm_model": "openai/gpt-4o",
                    "api_key": "sk-test",
                },
            )
        assert resp.status_code == 400
        assert "encryption" in resp.json()["detail"].lower()

    def test_update_model_not_found(self, client: TestClient):
        """PATCH model returns 404 when update_model returns None."""
        tid = uuid4()
        mid = uuid4()
        with patch(
            "bsgateway.tenant.service.TenantService.update_model",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.patch(
                f"/api/v1/tenants/{tid}/models/{mid}",
                json={"model_name": "updated-model"},
            )
        assert resp.status_code == 404
        assert "Model not found" in resp.json()["detail"]

    def test_update_model_value_error(self, client: TestClient):
        """PATCH model returns 400 on ValueError."""
        tid = uuid4()
        mid = uuid4()
        with patch(
            "bsgateway.tenant.service.TenantService.update_model",
            new_callable=AsyncMock,
            side_effect=ValueError(
                "Unable to store API keys securely — encryption is not configured"
            ),
        ):
            resp = client.patch(
                f"/api/v1/tenants/{tid}/models/{mid}",
                json={"api_key": "sk-new-key"},
            )
        assert resp.status_code == 400
        assert "encryption" in resp.json()["detail"].lower()
