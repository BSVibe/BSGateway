"""Tests for rules and intents API endpoints."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.api.deps import get_auth_context
from bsgateway.tests.conftest import make_gateway_auth_context, make_mock_pool

ENCRYPTION_KEY_HEX = os.urandom(32).hex()
ADMIN_TENANT_ID = uuid4()


@pytest.fixture
def mock_pool():
    pool, _conn = make_mock_pool()
    return pool


@pytest.fixture
def app(mock_pool: AsyncMock):
    app = create_app()
    app.state.db_pool = mock_pool
    app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    app.state.redis = None
    admin_ctx = make_gateway_auth_context(tenant_id=ADMIN_TENANT_ID, is_admin=True)
    app.dependency_overrides[get_auth_context] = lambda: admin_ctx
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _rule_row(
    tenant_id=None,
    rule_id=None,
    name="test-rule",
    priority=1,
    is_default=False,
    target="gpt-4o",
):
    now = datetime.now(UTC)
    return {
        "id": rule_id or uuid4(),
        "tenant_id": tenant_id or uuid4(),
        "name": name,
        "priority": priority,
        "is_active": True,
        "is_default": is_default,
        "target_model": target,
        "created_at": now,
        "updated_at": now,
    }


def _condition_row(rule_id=None, cond_id=None):
    return {
        "id": cond_id or uuid4(),
        "rule_id": rule_id or uuid4(),
        "condition_type": "token_count",
        "operator": "gt",
        "field": "estimated_tokens",
        "value": json.dumps(1000),
        "negate": False,
    }


def _intent_row(tenant_id=None, intent_id=None, name="test-intent"):
    now = datetime.now(UTC)
    return {
        "id": intent_id or uuid4(),
        "tenant_id": tenant_id or uuid4(),
        "name": name,
        "description": "test",
        "threshold": 0.7,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


class TestRulesCRUD:
    def test_create_rule(self, client: TestClient):
        tid = uuid4()
        row = _rule_row(tenant_id=tid)
        with (
            patch(
                "bsgateway.tenant.repository.TenantRepository.get_model_by_name",
                new_callable=AsyncMock,
                return_value={"model_name": "gpt-4o"},
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.create_rule",
                new_callable=AsyncMock,
                return_value=row,
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.replace_conditions",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.list_conditions_for_tenant",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "bsgateway.audit.repository.AuditRepository.record",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/rules",
                json={
                    "name": "test-rule",
                    "priority": 1,
                    "target_model": "gpt-4o",
                    "conditions": [
                        {
                            "condition_type": "token_count",
                            "field": "estimated_tokens",
                            "operator": "gt",
                            "value": 1000,
                        }
                    ],
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["name"] == "test-rule"
            assert data["target_model"] == "gpt-4o"

    def test_create_rule_invalid_target_model(self, client: TestClient):
        tid = uuid4()
        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_model_by_name",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/rules",
                json={
                    "name": "bad-rule",
                    "priority": 1,
                    "target_model": "nonexistent-model",
                },
            )
            assert resp.status_code == 400
            assert "not registered" in resp.json()["detail"]

    def test_create_default_rule_validates_model(self, client: TestClient):
        """Default rules also require a valid target_model."""
        tid = uuid4()
        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_model_by_name",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/rules",
                json={
                    "name": "default",
                    "priority": 99,
                    "target_model": "nonexistent-model",
                    "is_default": True,
                },
            )
            assert resp.status_code == 400
            assert "not registered" in resp.json()["detail"]

    def test_list_rules(self, client: TestClient):
        tid = uuid4()
        with (
            patch(
                "bsgateway.rules.repository.RulesRepository.list_rules",
                new_callable=AsyncMock,
                return_value=[_rule_row(tenant_id=tid)],
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.list_conditions_for_tenant",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = client.get(f"/api/v1/tenants/{tid}/rules")
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    def test_delete_rule(self, client: TestClient):
        with (
            patch(
                "bsgateway.rules.repository.RulesRepository.delete_rule",
                new_callable=AsyncMock,
            ),
            patch(
                "bsgateway.audit.repository.AuditRepository.record",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.delete(f"/api/v1/tenants/{uuid4()}/rules/{uuid4()}")
            assert resp.status_code == 204

    def test_get_rule_not_found(self, client: TestClient):
        with patch(
            "bsgateway.rules.repository.RulesRepository.get_rule",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(f"/api/v1/tenants/{uuid4()}/rules/{uuid4()}")
            assert resp.status_code == 404


class TestRuleTest:
    def test_rule_test_endpoint(self, client: TestClient):
        tid = uuid4()
        rid = uuid4()
        with (
            patch(
                "bsgateway.rules.repository.RulesRepository.list_rules",
                new_callable=AsyncMock,
                return_value=[
                    _rule_row(
                        tenant_id=tid,
                        rule_id=rid,
                        name="token-rule",
                        priority=1,
                        target="claude-opus",
                    ),
                    _rule_row(
                        tenant_id=tid,
                        name="default",
                        priority=99,
                        is_default=True,
                        target="gpt-4o-mini",
                    ),
                ],
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.list_conditions_for_tenant",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/rules/test",
                json={
                    "messages": [{"role": "user", "content": "Hello world"}],
                    "model": "auto",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["matched_rule"] is not None
            assert data["target_model"] is not None
            assert "context" in data

    def test_rule_test_endpoint_cached_rules_match_conditions_by_str_id(self, client: TestClient):
        """Regression: when list_rules returns from the JSON cache, rule
        ``id`` is a string while ``list_conditions_for_tenant`` returns
        UUID-typed ``rule_id``. The lookup must normalise both to str so
        cached rules still see their conditions — otherwise every rule
        looks unconditioned (empty AND-loop returns True) and the
        priority-1 rule unconditionally wins.
        """
        tid = uuid4()
        rid = uuid4()
        cached_rule_row = _rule_row(
            tenant_id=tid,
            rule_id=rid,
            name="urgent-only",
            priority=1,
            target="claude-opus",
        )
        # Simulate cache hit: id and tenant_id come back as strings.
        cached_rule_row["id"] = str(cached_rule_row["id"])
        cached_rule_row["tenant_id"] = str(cached_rule_row["tenant_id"])
        cached_rule_row["created_at"] = cached_rule_row["created_at"].isoformat()
        cached_rule_row["updated_at"] = cached_rule_row["updated_at"].isoformat()

        condition = {
            "id": uuid4(),
            "rule_id": rid,  # UUID — fresh from DB
            "condition_type": "text_pattern",
            "operator": "regex",
            "field": "user_text",
            "value": json.dumps(r"\b(URGENT|CRITICAL)\b"),
            "negate": False,
        }
        default_rule = _rule_row(
            tenant_id=tid,
            name="default",
            priority=99,
            is_default=True,
            target="gpt-4o-mini",
        )

        with (
            patch(
                "bsgateway.rules.repository.RulesRepository.list_rules",
                new_callable=AsyncMock,
                return_value=[cached_rule_row, default_rule],
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.list_conditions_for_tenant",
                new_callable=AsyncMock,
                return_value=[condition],
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.get_intent_by_name",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/rules/test",
                json={
                    "messages": [{"role": "user", "content": "hello there"}],
                    "model": "auto",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            # Without the str-normalised lookup the priority-1 rule would
            # match unconditionally; with the fix it falls through to default.
            assert data["target_model"] == "gpt-4o-mini"
            assert data["matched_rule"]["priority"] == 99
            # The conditioned rule must have been evaluated (and failed) —
            # otherwise the fix isn't doing anything.
            traced = [t for t in data["evaluation_trace"] if "rule" in t]
            assert any(t["rule"] == "urgent-only" and t["matched"] is False for t in traced)


class TestIntentsCRUD:
    def test_create_intent(self, client: TestClient):
        tid = uuid4()
        row = _intent_row(tenant_id=tid)
        with (
            patch(
                "bsgateway.rules.repository.RulesRepository.create_intent",
                new_callable=AsyncMock,
                return_value=row,
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.add_example",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/intents",
                json={
                    "name": "test-intent",
                    "description": "test",
                    "examples": ["example 1", "example 2"],
                },
            )
            assert resp.status_code == 201
            assert resp.json()["name"] == "test-intent"

    def test_list_intents(self, client: TestClient):
        tid = uuid4()
        with patch(
            "bsgateway.rules.repository.RulesRepository.list_intents",
            new_callable=AsyncMock,
            return_value=[_intent_row(tenant_id=tid)],
        ):
            resp = client.get(f"/api/v1/tenants/{tid}/intents")
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    def test_delete_intent(self, client: TestClient):
        with patch(
            "bsgateway.rules.repository.RulesRepository.delete_intent",
            new_callable=AsyncMock,
        ):
            resp = client.delete(f"/api/v1/tenants/{uuid4()}/intents/{uuid4()}")
            assert resp.status_code == 204

    def test_delete_example(self, client: TestClient):
        tid = uuid4()
        intent_id = uuid4()
        example_id = uuid4()
        with (
            patch(
                "bsgateway.rules.repository.RulesRepository.get_intent",
                new_callable=AsyncMock,
                return_value=_intent_row(tenant_id=tid, intent_id=intent_id),
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.delete_example",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.delete(
                f"/api/v1/tenants/{tid}/intents/{intent_id}/examples/{example_id}",
            )
            assert resp.status_code == 204

    def test_delete_example_intent_not_found(self, client: TestClient):
        with patch(
            "bsgateway.rules.repository.RulesRepository.get_intent",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.delete(
                f"/api/v1/tenants/{uuid4()}/intents/{uuid4()}/examples/{uuid4()}",
            )
            assert resp.status_code == 404

    def test_get_intent_not_found(self, client: TestClient):
        with patch(
            "bsgateway.rules.repository.RulesRepository.get_intent",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(f"/api/v1/tenants/{uuid4()}/intents/{uuid4()}")
            assert resp.status_code == 404

    def test_get_intent(self, client: TestClient):
        tid = uuid4()
        iid = uuid4()
        row = _intent_row(tenant_id=tid, intent_id=iid)
        with patch(
            "bsgateway.rules.repository.RulesRepository.get_intent",
            new_callable=AsyncMock,
            return_value=row,
        ):
            resp = client.get(f"/api/v1/tenants/{tid}/intents/{iid}")
            assert resp.status_code == 200
            assert resp.json()["name"] == "test-intent"

    def test_update_intent(self, client: TestClient):
        tid = uuid4()
        iid = uuid4()
        existing = _intent_row(tenant_id=tid, intent_id=iid)
        updated = _intent_row(tenant_id=tid, intent_id=iid, name="updated-intent")
        with (
            patch(
                "bsgateway.rules.repository.RulesRepository.get_intent",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.update_intent",
                new_callable=AsyncMock,
                return_value=updated,
            ),
        ):
            resp = client.patch(
                f"/api/v1/tenants/{tid}/intents/{iid}",
                json={"name": "updated-intent"},
            )
            assert resp.status_code == 200
            assert resp.json()["name"] == "updated-intent"

    def test_update_intent_not_found_on_get(self, client: TestClient):
        with patch(
            "bsgateway.rules.repository.RulesRepository.get_intent",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.patch(
                f"/api/v1/tenants/{uuid4()}/intents/{uuid4()}",
                json={"name": "x"},
            )
            assert resp.status_code == 404

    def test_update_intent_not_found_on_update(self, client: TestClient):
        tid = uuid4()
        iid = uuid4()
        existing = _intent_row(tenant_id=tid, intent_id=iid)
        with (
            patch(
                "bsgateway.rules.repository.RulesRepository.get_intent",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.update_intent",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = client.patch(
                f"/api/v1/tenants/{tid}/intents/{iid}",
                json={"name": "x"},
            )
            assert resp.status_code == 404

    def test_add_example(self, client: TestClient):
        tid = uuid4()
        iid = uuid4()
        intent_row = _intent_row(tenant_id=tid, intent_id=iid)
        example_row = {
            "id": uuid4(),
            "intent_id": iid,
            "text": "example text",
            "created_at": datetime.now(UTC),
        }
        with (
            patch(
                "bsgateway.rules.repository.RulesRepository.get_intent",
                new_callable=AsyncMock,
                return_value=intent_row,
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.add_example",
                new_callable=AsyncMock,
                return_value=example_row,
            ),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/intents/{iid}/examples",
                json={"text": "example text"},
            )
            assert resp.status_code == 201
            assert resp.json()["text"] == "example text"

    def test_add_example_intent_not_found(self, client: TestClient):
        with patch(
            "bsgateway.rules.repository.RulesRepository.get_intent",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                f"/api/v1/tenants/{uuid4()}/intents/{uuid4()}/examples",
                json={"text": "example text"},
            )
            assert resp.status_code == 404

    def test_list_examples(self, client: TestClient):
        tid = uuid4()
        iid = uuid4()
        intent_row = _intent_row(tenant_id=tid, intent_id=iid)
        example_rows = [
            {
                "id": uuid4(),
                "intent_id": iid,
                "text": "example 1",
                "created_at": datetime.now(UTC),
            },
            {
                "id": uuid4(),
                "intent_id": iid,
                "text": "example 2",
                "created_at": datetime.now(UTC),
            },
        ]
        with (
            patch(
                "bsgateway.rules.repository.RulesRepository.get_intent",
                new_callable=AsyncMock,
                return_value=intent_row,
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.list_examples",
                new_callable=AsyncMock,
                return_value=example_rows,
            ),
        ):
            resp = client.get(f"/api/v1/tenants/{tid}/intents/{iid}/examples")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            assert data[0]["text"] == "example 1"

    def test_list_examples_intent_not_found(self, client: TestClient):
        with patch(
            "bsgateway.rules.repository.RulesRepository.get_intent",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(
                f"/api/v1/tenants/{uuid4()}/intents/{uuid4()}/examples",
            )
            assert resp.status_code == 404
