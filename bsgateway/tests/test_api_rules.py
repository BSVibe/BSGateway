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
from bsgateway.core.security import hash_api_key

SUPERADMIN_KEY = "test-superadmin-key"
ENCRYPTION_KEY_HEX = os.urandom(32).hex()


@pytest.fixture
def mock_pool() -> AsyncMock:
    pool = AsyncMock()
    pool._closed = False
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.fixture
def app(mock_pool: AsyncMock):
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


def _rule_row(
    tenant_id=None, rule_id=None, name="test-rule",
    priority=1, is_default=False, target="gpt-4o",
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
    def test_create_rule(self, client: TestClient, admin_headers: dict):
        tid = uuid4()
        row = _rule_row(tenant_id=tid)
        with (
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
                "bsgateway.rules.repository.RulesRepository.list_conditions",
                new_callable=AsyncMock,
                return_value=[],
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
                headers=admin_headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["name"] == "test-rule"
            assert data["target_model"] == "gpt-4o"

    def test_list_rules(self, client: TestClient, admin_headers: dict):
        tid = uuid4()
        with (
            patch(
                "bsgateway.rules.repository.RulesRepository.list_rules",
                new_callable=AsyncMock,
                return_value=[_rule_row(tenant_id=tid)],
            ),
            patch(
                "bsgateway.rules.repository.RulesRepository.list_conditions",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = client.get(
                f"/api/v1/tenants/{tid}/rules", headers=admin_headers,
            )
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    def test_delete_rule(self, client: TestClient, admin_headers: dict):
        with patch(
            "bsgateway.rules.repository.RulesRepository.delete_rule",
            new_callable=AsyncMock,
        ):
            resp = client.delete(
                f"/api/v1/tenants/{uuid4()}/rules/{uuid4()}",
                headers=admin_headers,
            )
            assert resp.status_code == 204

    def test_get_rule_not_found(self, client: TestClient, admin_headers: dict):
        with patch(
            "bsgateway.rules.repository.RulesRepository.get_rule",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(
                f"/api/v1/tenants/{uuid4()}/rules/{uuid4()}",
                headers=admin_headers,
            )
            assert resp.status_code == 404


class TestRuleTest:
    def test_rule_test_endpoint(self, client: TestClient, admin_headers: dict):
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
                "bsgateway.rules.repository.RulesRepository.list_conditions",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/rules/test",
                json={
                    "messages": [
                        {"role": "user", "content": "Hello world"}
                    ],
                    "model": "auto",
                },
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            # With no conditions, rule at priority 1 matches
            assert data["matched_rule"] is not None
            assert data["target_model"] is not None
            assert "context" in data


class TestIntentsCRUD:
    def test_create_intent(self, client: TestClient, admin_headers: dict):
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
                headers=admin_headers,
            )
            assert resp.status_code == 201
            assert resp.json()["name"] == "test-intent"

    def test_list_intents(self, client: TestClient, admin_headers: dict):
        tid = uuid4()
        with patch(
            "bsgateway.rules.repository.RulesRepository.list_intents",
            new_callable=AsyncMock,
            return_value=[_intent_row(tenant_id=tid)],
        ):
            resp = client.get(
                f"/api/v1/tenants/{tid}/intents",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    def test_delete_intent(self, client: TestClient, admin_headers: dict):
        with patch(
            "bsgateway.rules.repository.RulesRepository.delete_intent",
            new_callable=AsyncMock,
        ):
            resp = client.delete(
                f"/api/v1/tenants/{uuid4()}/intents/{uuid4()}",
                headers=admin_headers,
            )
            assert resp.status_code == 204

    def test_get_intent_not_found(self, client: TestClient, admin_headers: dict):
        with patch(
            "bsgateway.rules.repository.RulesRepository.get_intent",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(
                f"/api/v1/tenants/{uuid4()}/intents/{uuid4()}",
                headers=admin_headers,
            )
            assert resp.status_code == 404
