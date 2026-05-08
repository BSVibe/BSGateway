"""Phase 3 / TASK-006 — typed audit events emitted by every router mutation.

The tests assert that:

* every router mutation site (models / intents / presets / tenants / rules)
  calls :func:`bsgateway.audit_publisher.emit_event` with the right
  ``DEFAULT_EVENT_TYPE``,
* the event ``tenant_id`` matches the request scope,
* no provider credential ever rides the ``data`` payload — explicitly,
  ``litellm_params``, ``api_key`` and ``token`` keys are absent.

Approach: each router is exercised through a real :class:`TestClient`
against the FastAPI app with a stub repository / service so the route
runs end-to-end. We patch ``emit_event`` on the *router module* (the
import site bound at collection time) and capture the events.
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
from bsgateway.api.deps import (
    get_auth_context,
    get_model_registry,
)
from bsgateway.audit.events import (
    ModelCreated,
    ModelDeleted,
    ModelHidden,
    ModelUpdated,
    RoutingIntentCreated,
    RoutingIntentDeleted,
    RoutingIntentUpdated,
    RoutingPresetApplied,
    RoutingRuleCreated,
    RoutingRuleDeleted,
    RoutingRuleUpdated,
    TenantCreated,
    TenantDeactivated,
    TenantUpdated,
)
from bsgateway.tests.conftest import make_gateway_auth_context, make_mock_pool

ENCRYPTION_KEY_HEX = os.urandom(32).hex()


def _admin_authz(tenant_id: UUID) -> AuthzUser:
    return AuthzUser(
        id="00000000-0000-0000-0000-000000000099",
        email="admin@test.com",
        active_tenant_id=str(tenant_id),
        tenants=[],
        is_service=False,
        scope=["gateway:*"],
    )


class _StubRegistry:
    def __init__(self) -> None:
        self.invalidated: list[UUID] = []

    async def list_models(self, tenant_id: UUID) -> list:
        return []

    async def get_passthrough_set(self, tenant_id: UUID) -> set[str]:
        return set()

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
    pool, _conn = make_mock_pool()
    application = create_app()
    application.state.db_pool = pool
    application.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    application.state.redis = None
    application.state.model_registry = registry
    application.state.audit_emitter = None
    application.state.audit_outbox_session_factory = None
    admin_ctx = make_gateway_auth_context(tenant_id=tenant_id, is_admin=True)
    application.dependency_overrides[get_auth_context] = lambda: admin_ctx
    application.dependency_overrides[get_model_registry] = lambda: registry
    application.dependency_overrides[authz_get_current_user] = lambda: _admin_authz(tenant_id)
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _model_row(tenant_id: UUID, model_id: UUID, *, origin: str = "custom") -> dict:
    return {
        "id": model_id,
        "tenant_id": tenant_id,
        "name": "custom/foo",
        "origin": origin,
        "litellm_model": "ollama/foo" if origin == "custom" else None,
        "litellm_params": {"api_key": "secret"} if origin == "custom" else None,
        "is_passthrough": True,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


def _assert_no_secrets(payload: dict) -> None:
    """Provider creds and tokens must never reach the audit pipeline."""
    forbidden = {"litellm_params", "api_key", "token", "secret"}
    for key in forbidden:
        assert key not in payload, f"audit payload leaked secret-like key: {key}"


# ---------------------------------------------------------------------------
# Event registry — DEFAULT_EVENT_TYPE pinning + tenant_id round-trip.
# ---------------------------------------------------------------------------


class TestEventCatalog:
    """Each event subclass pins ``DEFAULT_EVENT_TYPE`` and round-trips."""

    @pytest.mark.parametrize(
        ("cls", "expected"),
        [
            (ModelCreated, "gateway.model.created"),
            (ModelUpdated, "gateway.model.updated"),
            (ModelDeleted, "gateway.model.deleted"),
            (ModelHidden, "gateway.model.hidden"),
            (RoutingRuleCreated, "gateway.routing.rule.created"),
            (RoutingRuleUpdated, "gateway.routing.rule.updated"),
            (RoutingRuleDeleted, "gateway.routing.rule.deleted"),
            (RoutingIntentCreated, "gateway.routing.intent.created"),
            (RoutingIntentUpdated, "gateway.routing.intent.updated"),
            (RoutingIntentDeleted, "gateway.routing.intent.deleted"),
            (RoutingPresetApplied, "gateway.routing.preset.applied"),
            (TenantCreated, "gateway.tenant.created"),
            (TenantUpdated, "gateway.tenant.updated"),
            (TenantDeactivated, "gateway.tenant.deactivated"),
        ],
    )
    def test_default_event_type_pinned(self, cls, expected: str) -> None:
        assert cls.DEFAULT_EVENT_TYPE == expected
        from bsvibe_audit.events.base import AuditActor

        # Auto-fills event_type when not supplied.
        instance = cls(actor=AuditActor(type="user", id="u1"))
        assert instance.event_type == expected


# ---------------------------------------------------------------------------
# /admin/models — typed model.* events.
# ---------------------------------------------------------------------------


class TestAdminModelsEmits:
    def test_create_custom_emits_model_created(self, client: TestClient, tenant_id: UUID) -> None:
        from bsgateway.api.routers import models as models_router

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        row = _model_row(tenant_id, uuid4(), origin="custom")
        with (
            patch.object(models_router, "emit_event", _capture),
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
                    "litellm_params": {"api_key": "secret"},
                    "is_passthrough": True,
                },
            )
        assert resp.status_code == 201, resp.json()
        assert len(captured) == 1
        event = captured[0]
        assert isinstance(event, ModelCreated)
        assert event.event_type == "gateway.model.created"
        assert event.tenant_id == str(tenant_id)
        _assert_no_secrets(event.data)

    def test_create_hide_system_emits_model_hidden(
        self, client: TestClient, tenant_id: UUID
    ) -> None:
        from bsgateway.api.routers import models as models_router

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        row = _model_row(tenant_id, uuid4(), origin="hide_system")
        with (
            patch.object(models_router, "emit_event", _capture),
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
                json={"name": "claude-haiku", "origin": "hide_system"},
            )
        assert resp.status_code == 201, resp.json()
        assert len(captured) == 1
        assert isinstance(captured[0], ModelHidden)
        assert captured[0].event_type == "gateway.model.hidden"
        assert captured[0].tenant_id == str(tenant_id)
        _assert_no_secrets(captured[0].data)

    def test_update_emits_model_updated(self, client: TestClient, tenant_id: UUID) -> None:
        from bsgateway.api.routers import models as models_router

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        model_id = uuid4()
        row = _model_row(tenant_id, model_id)
        with (
            patch.object(models_router, "emit_event", _capture),
            patch(
                "bsgateway.routing.models_repository.ModelsRepository.get_model",
                new_callable=AsyncMock,
                return_value=row,
            ),
            patch(
                "bsgateway.routing.models_repository.ModelsRepository.update_model",
                new_callable=AsyncMock,
                return_value=row,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.patch(
                f"/api/v1/admin/models/{model_id}",
                json={"litellm_model": "ollama/bar"},
            )
        assert resp.status_code == 200, resp.json()
        assert len(captured) == 1
        assert isinstance(captured[0], ModelUpdated)
        assert captured[0].tenant_id == str(tenant_id)
        _assert_no_secrets(captured[0].data)

    def test_delete_emits_model_deleted(self, client: TestClient, tenant_id: UUID) -> None:
        from bsgateway.api.routers import models as models_router

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        model_id = uuid4()
        row = _model_row(tenant_id, model_id)
        with (
            patch.object(models_router, "emit_event", _capture),
            patch(
                "bsgateway.routing.models_repository.ModelsRepository.get_model",
                new_callable=AsyncMock,
                return_value=row,
            ),
            patch(
                "bsgateway.routing.models_repository.ModelsRepository.delete_model",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.delete(f"/api/v1/admin/models/{model_id}")
        assert resp.status_code == 204
        assert len(captured) == 1
        assert isinstance(captured[0], ModelDeleted)
        assert captured[0].tenant_id == str(tenant_id)
        _assert_no_secrets(captured[0].data)


# ---------------------------------------------------------------------------
# /tenants/{id}/intents — typed routing.intent.* events.
# ---------------------------------------------------------------------------


class TestIntentsEmits:
    def test_create_intent_emits_routing_intent_created(
        self, client: TestClient, tenant_id: UUID
    ) -> None:
        from bsgateway.api.routers import intents as intents_router

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        intent_row = {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "name": "buy",
            "description": "purchase intent",
            "threshold": 0.8,
            "is_active": True,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        with (
            patch.object(intents_router, "emit_event", _capture),
            patch.object(
                intents_router,
                "build_service_for_tenant",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.create_intent",
                new_callable=AsyncMock,
                return_value=intent_row,
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.add_example",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tenant_id}/intents",
                json={
                    "name": "buy",
                    "description": "purchase intent",
                    "threshold": 0.8,
                    "examples": ["buy this", "purchase"],
                },
            )
        assert resp.status_code == 201, resp.json()
        assert len(captured) == 1
        assert isinstance(captured[0], RoutingIntentCreated)
        assert captured[0].tenant_id == str(tenant_id)
        assert captured[0].data["example_count"] == 2
        _assert_no_secrets(captured[0].data)

    def test_update_intent_emits_routing_intent_updated(
        self, client: TestClient, tenant_id: UUID
    ) -> None:
        from bsgateway.api.routers import intents as intents_router

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        intent_id = uuid4()
        existing = {
            "id": intent_id,
            "tenant_id": tenant_id,
            "name": "buy",
            "description": "x",
            "threshold": 0.8,
            "is_active": True,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        with (
            patch.object(intents_router, "emit_event", _capture),
            patch(
                "bsgateway.rules.repository.RulesRepository.get_intent",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.update_intent",
                new_callable=AsyncMock,
                return_value=existing,
            ),
        ):
            resp = client.patch(
                f"/api/v1/tenants/{tenant_id}/intents/{intent_id}",
                json={"threshold": 0.9},
            )
        assert resp.status_code == 200, resp.json()
        assert len(captured) == 1
        assert isinstance(captured[0], RoutingIntentUpdated)
        assert captured[0].tenant_id == str(tenant_id)
        _assert_no_secrets(captured[0].data)

    def test_delete_intent_emits_routing_intent_deleted(
        self, client: TestClient, tenant_id: UUID
    ) -> None:
        from bsgateway.api.routers import intents as intents_router

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        intent_id = uuid4()
        with (
            patch.object(intents_router, "emit_event", _capture),
            patch(
                "bsgateway.rules.repository.RulesRepository.delete_intent",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.delete(f"/api/v1/tenants/{tenant_id}/intents/{intent_id}")
        assert resp.status_code == 204
        assert len(captured) == 1
        assert isinstance(captured[0], RoutingIntentDeleted)
        assert captured[0].tenant_id == str(tenant_id)
        _assert_no_secrets(captured[0].data)


# ---------------------------------------------------------------------------
# /tenants — typed tenant.* events.
# ---------------------------------------------------------------------------


class TestTenantsEmits:
    def test_create_tenant_emits_tenant_created(self, client: TestClient) -> None:
        from bsgateway.api.routers import tenants as tenants_router
        from bsgateway.tenant.models import TenantResponse

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        new_id = uuid4()
        tenant_resp = TenantResponse(
            id=new_id,
            name="acme",
            slug="acme",
            settings={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            is_active=True,
        )
        with (
            patch.object(tenants_router, "emit_event", _capture),
            patch(
                "bsgateway.tenant.service.TenantService.create_tenant",
                new_callable=AsyncMock,
                return_value=tenant_resp,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                "/api/v1/tenants",
                json={"name": "acme", "slug": "acme"},
            )
        assert resp.status_code == 201, resp.json()
        assert len(captured) == 1
        assert isinstance(captured[0], TenantCreated)
        assert captured[0].tenant_id == str(new_id)
        _assert_no_secrets(captured[0].data)

    def test_update_tenant_emits_tenant_updated(self, client: TestClient, tenant_id: UUID) -> None:
        from bsgateway.api.routers import tenants as tenants_router
        from bsgateway.tenant.models import TenantResponse

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        existing = TenantResponse(
            id=tenant_id,
            name="acme",
            slug="acme",
            settings={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            is_active=True,
        )
        with (
            patch.object(tenants_router, "emit_event", _capture),
            patch(
                "bsgateway.tenant.service.TenantService.get_tenant",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "bsgateway.tenant.service.TenantService.update_tenant",
                new_callable=AsyncMock,
                return_value=existing,
            ),
        ):
            resp = client.patch(
                f"/api/v1/tenants/{tenant_id}",
                json={"name": "acme-renamed"},
            )
        assert resp.status_code == 200, resp.json()
        assert len(captured) == 1
        assert isinstance(captured[0], TenantUpdated)
        assert captured[0].tenant_id == str(tenant_id)
        _assert_no_secrets(captured[0].data)

    def test_deactivate_tenant_emits_tenant_deactivated(
        self, client: TestClient, tenant_id: UUID
    ) -> None:
        from bsgateway.api.routers import tenants as tenants_router

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        with (
            patch.object(tenants_router, "emit_event", _capture),
            patch(
                "bsgateway.tenant.service.TenantService.deactivate_tenant",
                new_callable=AsyncMock,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.delete(f"/api/v1/tenants/{tenant_id}")
        assert resp.status_code == 204
        assert len(captured) == 1
        assert isinstance(captured[0], TenantDeactivated)
        assert captured[0].tenant_id == str(tenant_id)
        _assert_no_secrets(captured[0].data)


# ---------------------------------------------------------------------------
# /tenants/{id}/rules — typed routing.rule.* events (in addition to legacy
# RouteConfigChanged kept for backwards-compat with the cross-product audit).
# ---------------------------------------------------------------------------


class TestRulesTypedEmits:
    """``rules`` already emits ``RouteConfigChanged``. TASK-006 adds typed
    ``routing.rule.*`` mirrors so consumers can filter by verb without
    parsing the ``data.action`` field."""

    def test_create_rule_emits_routing_rule_created(
        self, client: TestClient, tenant_id: UUID
    ) -> None:
        from bsgateway.api.routers import rules as rules_router

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        rule_id = uuid4()
        rule_row = {
            "id": rule_id,
            "tenant_id": tenant_id,
            "name": "premium",
            "priority": 10,
            "is_active": True,
            "is_default": False,
            "target_model": "claude-opus-4-7",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        model_row = {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "model_name": "claude-opus-4-7",
            "litellm_model": "anthropic/claude-opus-4-7",
        }
        with (
            patch.object(rules_router, "emit_event", _capture),
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_model_by_name",
                new_callable=AsyncMock,
                return_value=model_row,
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.create_rule",
                new_callable=AsyncMock,
                return_value=rule_row,
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.list_conditions",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tenant_id}/rules",
                json={
                    "name": "premium",
                    "priority": 10,
                    "is_default": False,
                    "target_model": "claude-opus-4-7",
                    "conditions": [],
                },
            )
        assert resp.status_code == 201, resp.json()
        # Two emits: legacy RouteConfigChanged + typed RoutingRuleCreated.
        types = [e.event_type for e in captured]
        assert "gateway.route.config_changed" in types
        assert "gateway.routing.rule.created" in types
        rule_created = next(e for e in captured if isinstance(e, RoutingRuleCreated))
        assert rule_created.tenant_id == str(tenant_id)
        _assert_no_secrets(rule_created.data)

    def test_delete_rule_emits_routing_rule_deleted(
        self, client: TestClient, tenant_id: UUID
    ) -> None:
        from bsgateway.api.routers import rules as rules_router

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        rule_id = uuid4()
        with (
            patch.object(rules_router, "emit_event", _capture),
            patch(
                "bsgateway.rules.repository.RulesRepository.delete_rule",
                new_callable=AsyncMock,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.delete(f"/api/v1/tenants/{tenant_id}/rules/{rule_id}")
        assert resp.status_code == 204
        types = [type(e) for e in captured]
        assert RoutingRuleDeleted in types
        deleted = next(e for e in captured if isinstance(e, RoutingRuleDeleted))
        assert deleted.tenant_id == str(tenant_id)
        _assert_no_secrets(deleted.data)


# ---------------------------------------------------------------------------
# /presets/apply — typed routing.preset.applied event.
# ---------------------------------------------------------------------------


class TestPresetsEmits:
    def test_apply_preset_emits_routing_preset_applied(
        self, client: TestClient, tenant_id: UUID
    ) -> None:
        from bsgateway.api.routers import presets as presets_router
        from bsgateway.presets.service import PresetApplyResult

        captured: list = []

        async def _capture(_state, event):
            captured.append(event)

        result = PresetApplyResult(
            preset_name="general-assistant",
            rules_created=2,
            intents_created=3,
            examples_created=10,
        )
        with (
            patch.object(presets_router, "emit_event", _capture),
            patch.object(
                presets_router,
                "build_service_for_tenant",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "bsgateway.presets.service.PresetService.apply_preset",
                new_callable=AsyncMock,
                return_value=result,
            ),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tenant_id}/presets/apply",
                json={
                    "preset_name": "general-assistant",
                    "model_mapping": {
                        "economy": "claude-haiku",
                        "premium": "claude-opus",
                        "balanced": "claude-sonnet",
                    },
                },
            )
        assert resp.status_code == 201, resp.json()
        assert len(captured) == 1
        assert isinstance(captured[0], RoutingPresetApplied)
        assert captured[0].tenant_id == str(tenant_id)
        assert captured[0].data["preset_name"] == "general-assistant"
        _assert_no_secrets(captured[0].data)
