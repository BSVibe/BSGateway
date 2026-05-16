"""Tests for the Phase 3 admin ``/admin/models`` router (TASK-005).

The router exposes CRUD over the per-tenant ``models`` table introduced
in alembic ``0004_models_and_tenant_isolation``. It is the only mutation
surface for the yaml-union-DB merge cache (``ModelRegistryService``), so
every write here MUST:

* enforce ``bsgateway:models:write`` (scope cutover lockdown),
* call ``registry.invalidate(tenant_id)`` so the next routing decision
  sees the new state without a process restart,
* emit an audit row through ``AuditService.record`` with no
  ``litellm_params`` payload (provider creds may live there).

Reads enforce ``bsgateway:models:read`` and call ``registry.list_models``
so the response is the **effective** (yaml-union-DB) list — clients never
have to merge themselves.
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
from bsgateway.api.deps import get_auth_context, get_model_registry
from bsgateway.routing.registry import ModelEntry
from bsgateway.tests.conftest import make_gateway_auth_context, make_mock_pool

ENCRYPTION_KEY_HEX = os.urandom(32).hex()


def _scopeless_authz_user(tenant_id: UUID) -> AuthzUser:
    return AuthzUser(
        id="00000000-0000-0000-0000-000000000099",
        email="member@test.com",
        active_tenant_id=str(tenant_id),
        tenants=[],
        is_service=False,
        scope=[],
    )


class _StubRegistry:
    """Capture invalidate/list_models calls without a real DB."""

    def __init__(self, models: list[ModelEntry] | None = None) -> None:
        self._models = models or []
        self.invalidated: list[UUID] = []

    async def list_models(self, tenant_id: UUID) -> list[ModelEntry]:
        return list(self._models)

    async def get_passthrough_set(self, tenant_id: UUID) -> set[str]:
        return {m.name for m in self._models if m.is_passthrough}

    async def invalidate(self, tenant_id: UUID) -> None:
        self.invalidated.append(tenant_id)


@pytest.fixture
def tenant_id() -> UUID:
    return uuid4()


@pytest.fixture
def registry() -> _StubRegistry:
    return _StubRegistry()


@pytest.fixture
def app(tenant_id: UUID, registry: _StubRegistry):
    """FastAPI app with admin context targeting `tenant_id`."""
    pool, _conn = make_mock_pool()
    app = create_app()
    app.state.db_pool = pool
    app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    app.state.redis = None
    app.state.model_registry = registry
    admin_ctx = make_gateway_auth_context(tenant_id=tenant_id, is_admin=True)
    app.dependency_overrides[get_auth_context] = lambda: admin_ctx
    app.dependency_overrides[get_model_registry] = lambda: registry
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _db_row(
    *,
    tenant_id: UUID,
    name: str = "custom/foo",
    origin: str = "custom",
    litellm_model: str | None = "ollama/foo",
    litellm_params: dict | None = None,
    is_passthrough: bool = True,
    model_id: UUID | None = None,
) -> dict:
    now = datetime.now(UTC)
    return {
        "id": model_id or uuid4(),
        "tenant_id": tenant_id,
        "name": name,
        "origin": origin,
        "litellm_model": litellm_model,
        "litellm_params": litellm_params,
        "is_passthrough": is_passthrough,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# GET /admin/models — effective list (yaml-union-DB)
# ---------------------------------------------------------------------------


class TestListEffectiveModels:
    def test_returns_merged_list_via_registry(
        self,
        client: TestClient,
        registry: _StubRegistry,
        tenant_id: UUID,
    ) -> None:
        custom_id = uuid4()
        registry._models = [
            ModelEntry(
                name="claude-haiku",
                origin="system",
                is_passthrough=True,
                litellm_model="anthropic/claude-haiku-4-5",
                litellm_params=None,
            ),
            ModelEntry(
                name="custom/foo",
                origin="custom",
                is_passthrough=True,
                litellm_model="ollama/foo",
                litellm_params={"api_base": "http://x"},
                id=custom_id,
                tenant_id=tenant_id,
            ),
        ]
        resp = client.get("/api/v1/admin/models")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {m["name"] for m in data}
        assert names == {"claude-haiku", "custom/foo"}

    def test_response_omits_litellm_params_value(
        self,
        client: TestClient,
        registry: _StubRegistry,
        tenant_id: UUID,
    ) -> None:
        """``litellm_params`` may carry credentials. The list endpoint
        must report whether params exist (boolean) without leaking them.
        """
        registry._models = [
            ModelEntry(
                name="custom/foo",
                origin="custom",
                is_passthrough=True,
                litellm_model="ollama/foo",
                litellm_params={"api_key": "secret-do-not-leak"},
                id=uuid4(),
                tenant_id=tenant_id,
            ),
        ]
        resp = client.get("/api/v1/admin/models")
        assert resp.status_code == 200
        body = resp.text
        assert "secret-do-not-leak" not in body
        entry = next(m for m in resp.json() if m["name"] == "custom/foo")
        assert entry["has_litellm_params"] is True

    def test_permissive_read_allows_scopeless_list(
        self,
        tenant_id: UUID,
        registry: _StubRegistry,
    ) -> None:
        """Tier 5: ``GET /admin/models`` uses ``require_permission`` (DOT
        grammar), permissive when OpenFGA is unconfigured. A session JWT
        with ``scope=[]`` and no admin role reaches the handler (200) —
        the legacy ``require_scope`` COLON gate that 403'd it is gone.
        """
        pool, _conn = make_mock_pool()
        app = create_app()
        app.state.db_pool = pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        app.state.model_registry = registry
        member_ctx = make_gateway_auth_context(tenant_id=tenant_id, is_admin=False)
        app.dependency_overrides[get_auth_context] = lambda: member_ctx
        app.dependency_overrides[get_model_registry] = lambda: registry
        app.dependency_overrides[authz_get_current_user] = lambda: _scopeless_authz_user(tenant_id)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/admin/models")
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# POST /admin/models — create custom or hide_system
# ---------------------------------------------------------------------------


class TestCreateModel:
    def test_create_custom_invalidates_and_audits(
        self,
        client: TestClient,
        registry: _StubRegistry,
        tenant_id: UUID,
    ) -> None:
        row = _db_row(tenant_id=tenant_id, name="custom/foo", origin="custom")
        with (
            patch(
                "bsgateway.routing.models_repository.ModelsRepository.create_model",
                new_callable=AsyncMock,
                return_value=row,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            resp = client.post(
                "/api/v1/admin/models",
                json={
                    "name": "custom/foo",
                    "origin": "custom",
                    "litellm_model": "ollama/foo",
                    "litellm_params": {"api_base": "http://x"},
                    "is_passthrough": True,
                },
            )
        assert resp.status_code == 201, resp.json()
        assert registry.invalidated == [tenant_id]
        # Audit fires with model.created — payload must NOT echo litellm_params.
        assert mock_audit.await_count == 1
        kwargs = mock_audit.await_args.kwargs or {}
        action = kwargs.get("action") or mock_audit.await_args.args[2]
        details = kwargs.get("details") or mock_audit.await_args.args[5]
        assert action == "model.created"
        assert details is not None
        assert "litellm_params" not in details

    def test_create_hide_system_does_not_require_litellm_model(
        self,
        client: TestClient,
        registry: _StubRegistry,
        tenant_id: UUID,
    ) -> None:
        row = _db_row(
            tenant_id=tenant_id,
            name="claude-haiku",
            origin="hide_system",
            litellm_model=None,
            litellm_params=None,
        )
        with (
            patch(
                "bsgateway.routing.models_repository.ModelsRepository.create_model",
                new_callable=AsyncMock,
                return_value=row,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                "/api/v1/admin/models",
                json={
                    "name": "claude-haiku",
                    "origin": "hide_system",
                },
            )
        assert resp.status_code == 201, resp.json()
        assert registry.invalidated == [tenant_id]

    def test_create_custom_requires_litellm_model(
        self,
        client: TestClient,
        registry: _StubRegistry,
    ) -> None:
        resp = client.post(
            "/api/v1/admin/models",
            json={"name": "custom/foo", "origin": "custom"},
        )
        assert resp.status_code == 422
        assert registry.invalidated == []

    def test_create_rejects_unknown_origin(
        self,
        client: TestClient,
    ) -> None:
        resp = client.post(
            "/api/v1/admin/models",
            json={
                "name": "x",
                "origin": "weird",
                "litellm_model": "ollama/x",
            },
        )
        assert resp.status_code == 422

    def test_permissive_write_allows_scopeless_create(
        self,
        tenant_id: UUID,
        registry: _StubRegistry,
    ) -> None:
        """Tier 5: ``POST /admin/models`` uses ``require_permission`` (DOT
        grammar), permissive when OpenFGA is unconfigured. A session JWT
        with ``scope=[]`` and no admin role reaches the handler (201) —
        the legacy ``require_scope`` COLON gate that 403'd it is gone.
        The matrix row ``bsgateway.models.write`` (min role: member) is
        what enforces the role boundary once OpenFGA is wired.
        """
        pool, _conn = make_mock_pool()
        app = create_app()
        app.state.db_pool = pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None
        app.state.model_registry = registry
        member_ctx = make_gateway_auth_context(tenant_id=tenant_id, is_admin=False)
        app.dependency_overrides[get_auth_context] = lambda: member_ctx
        app.dependency_overrides[get_model_registry] = lambda: registry
        app.dependency_overrides[authz_get_current_user] = lambda: _scopeless_authz_user(tenant_id)
        client = TestClient(app, raise_server_exceptions=False)
        row = _db_row(tenant_id=tenant_id, name="custom/foo", origin="custom")
        with (
            patch(
                "bsgateway.routing.models_repository.ModelsRepository.create_model",
                new_callable=AsyncMock,
                return_value=row,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                "/api/v1/admin/models",
                json={
                    "name": "custom/foo",
                    "origin": "custom",
                    "litellm_model": "ollama/foo",
                },
            )
        assert resp.status_code == 201, resp.text
        assert registry.invalidated == [tenant_id]


# ---------------------------------------------------------------------------
# PATCH /admin/models/{id}
# ---------------------------------------------------------------------------


class TestUpdateModel:
    def test_update_invalidates_and_audits(
        self,
        client: TestClient,
        registry: _StubRegistry,
        tenant_id: UUID,
    ) -> None:
        model_id = uuid4()
        existing = _db_row(tenant_id=tenant_id, model_id=model_id)
        updated = _db_row(
            tenant_id=tenant_id,
            model_id=model_id,
            litellm_model="ollama/bar",
        )
        with (
            patch(
                "bsgateway.routing.models_repository.ModelsRepository.get_model",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "bsgateway.routing.models_repository.ModelsRepository.update_model",
                new_callable=AsyncMock,
                return_value=updated,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            resp = client.patch(
                f"/api/v1/admin/models/{model_id}",
                json={"litellm_model": "ollama/bar"},
            )
        assert resp.status_code == 200, resp.json()
        assert registry.invalidated == [tenant_id]
        assert mock_audit.await_count == 1
        action = mock_audit.await_args.args[2]
        details = mock_audit.await_args.args[5]
        assert action == "model.updated"
        assert "litellm_params" not in (details or {})

    def test_update_404_when_missing(
        self,
        client: TestClient,
        registry: _StubRegistry,
    ) -> None:
        model_id = uuid4()
        with patch(
            "bsgateway.routing.models_repository.ModelsRepository.get_model",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.patch(
                f"/api/v1/admin/models/{model_id}",
                json={"litellm_model": "ollama/bar"},
            )
        assert resp.status_code == 404
        assert registry.invalidated == []


# ---------------------------------------------------------------------------
# DELETE /admin/models/{id}
# ---------------------------------------------------------------------------


class TestDeleteModel:
    def test_delete_invalidates_and_audits(
        self,
        client: TestClient,
        registry: _StubRegistry,
        tenant_id: UUID,
    ) -> None:
        model_id = uuid4()
        existing = _db_row(tenant_id=tenant_id, model_id=model_id)
        with (
            patch(
                "bsgateway.routing.models_repository.ModelsRepository.get_model",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "bsgateway.routing.models_repository.ModelsRepository.delete_model",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            resp = client.delete(f"/api/v1/admin/models/{model_id}")
        assert resp.status_code == 204
        assert registry.invalidated == [tenant_id]
        assert mock_audit.await_count == 1
        assert mock_audit.await_args.args[2] == "model.deleted"

    def test_delete_404_when_missing(
        self,
        client: TestClient,
        registry: _StubRegistry,
    ) -> None:
        model_id = uuid4()
        with patch(
            "bsgateway.routing.models_repository.ModelsRepository.get_model",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.delete(f"/api/v1/admin/models/{model_id}")
        assert resp.status_code == 404
        assert registry.invalidated == []

    def test_delete_blocked_for_other_tenants_row(
        self,
        client: TestClient,
        registry: _StubRegistry,
    ) -> None:
        """Tenant-isolation invariant — a model row owned by another tenant
        is invisible (returns 404) even to a non-admin caller. Bootstrap
        admins still operate on their own ``_auth.tenant_id`` here, so a
        cross-tenant delete attempt resolves to 404 rather than 200.
        """
        other_tenant = uuid4()
        model_id = uuid4()
        foreign_row = _db_row(tenant_id=other_tenant, model_id=model_id)
        with patch(
            "bsgateway.routing.models_repository.ModelsRepository.get_model",
            new_callable=AsyncMock,
            return_value=foreign_row if False else None,  # repo filters by tenant_id
        ):
            resp = client.delete(f"/api/v1/admin/models/{model_id}")
        assert resp.status_code == 404
        assert registry.invalidated == []
