"""Tests for MCP router endpoints."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.api.deps import get_auth_context
from bsgateway.tests.conftest import make_gateway_auth_context, make_mock_pool

ENCRYPTION_KEY_HEX = os.urandom(32).hex()
TENANT_ID = uuid4()


@pytest.fixture
def mock_pool():
    pool, _conn = make_mock_pool()
    return pool


@pytest.fixture
def app(mock_pool):
    app = create_app()
    app.state.db_pool = mock_pool
    app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    app.state.redis = None
    app.state.cache = None
    ctx = make_gateway_auth_context(tenant_id=TENANT_ID, is_admin=True)
    app.dependency_overrides[get_auth_context] = lambda: ctx
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _rule_row(tenant_id=None, rule_id=None, name="test-rule"):
    now = datetime.now(UTC)
    return {
        "id": rule_id or uuid4(),
        "tenant_id": tenant_id or TENANT_ID,
        "name": name,
        "priority": 1,
        "is_active": True,
        "is_default": False,
        "target_model": "gpt-4o",
        "created_at": now,
        "updated_at": now,
    }


def _model_row(tenant_id=None):
    return {
        "id": uuid4(),
        "tenant_id": tenant_id or TENANT_ID,
        "model_name": "gpt-4o",
        "provider": "openai",
        "litellm_model": "openai/gpt-4o",
        "api_base": None,
        "extra_params": "{}",
        "created_at": datetime.now(UTC),
    }


# ---------------------------------------------------------------------------
# Rules endpoints
# ---------------------------------------------------------------------------


@patch("bsgateway.mcp.service.MCPService.list_rules")
def test_list_rules(mock_list, client):
    from bsgateway.mcp.schemas import MCPRuleResponse

    row = _rule_row()
    mock_list.return_value = [
        MCPRuleResponse(**{**row, "conditions": []}),
    ]
    resp = client.get(f"/api/v1/tenants/{TENANT_ID}/mcp/rules")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "test-rule"


@patch("bsgateway.mcp.service.MCPService.create_rule")
def test_create_rule(mock_create, client):
    from bsgateway.mcp.schemas import MCPRuleResponse

    row = _rule_row(name="new-rule")
    mock_create.return_value = MCPRuleResponse(**{**row, "name": "new-rule", "conditions": []})
    resp = client.post(
        f"/api/v1/tenants/{TENANT_ID}/mcp/rules",
        json={"name": "new-rule", "target_model": "gpt-4o", "conditions": []},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "new-rule"


@patch("bsgateway.mcp.service.MCPService.update_rule")
def test_update_rule(mock_update, client):
    from bsgateway.mcp.schemas import MCPRuleResponse

    rid = uuid4()
    row = _rule_row(rule_id=rid, name="updated")
    mock_update.return_value = MCPRuleResponse(**{**row, "name": "updated", "conditions": []})
    resp = client.patch(
        f"/api/v1/tenants/{TENANT_ID}/mcp/rules/{rid}",
        json={"name": "updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated"


@patch("bsgateway.mcp.service.MCPService.update_rule")
def test_update_rule_not_found(mock_update, client):
    mock_update.return_value = None
    resp = client.patch(
        f"/api/v1/tenants/{TENANT_ID}/mcp/rules/{uuid4()}",
        json={"name": "x"},
    )
    assert resp.status_code == 404


@patch("bsgateway.mcp.service.MCPService.delete_rule")
def test_delete_rule(mock_delete, client):
    mock_delete.return_value = None
    resp = client.delete(f"/api/v1/tenants/{TENANT_ID}/mcp/rules/{uuid4()}")
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Models endpoints
# ---------------------------------------------------------------------------


@patch("bsgateway.mcp.service.MCPService.list_models")
def test_list_models(mock_list, client):
    from bsgateway.mcp.schemas import MCPModelResponse

    mock_list.return_value = [MCPModelResponse(**_model_row())]
    resp = client.get(f"/api/v1/tenants/{TENANT_ID}/mcp/models")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@patch("bsgateway.mcp.service.MCPService.register_model")
def test_register_model(mock_register, client):
    from bsgateway.mcp.schemas import MCPModelResponse

    mock_register.return_value = MCPModelResponse(**_model_row())
    resp = client.post(
        f"/api/v1/tenants/{TENANT_ID}/mcp/models",
        json={"name": "gpt-4o", "provider": "openai", "config": {}},
    )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Simulate routing
# ---------------------------------------------------------------------------


@patch("bsgateway.mcp.service.MCPService.simulate_routing")
def test_simulate_routing(mock_sim, client):
    from bsgateway.mcp.schemas import MCPSimulateResponse

    mock_sim.return_value = MCPSimulateResponse(
        matched_rule=None,
        target_model=None,
        evaluation_trace=[],
        context={},
    )
    resp = client.post(
        f"/api/v1/tenants/{TENANT_ID}/mcp/simulate",
        json={"model_hint": "auto", "text": "hello world"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Cost / Usage
# ---------------------------------------------------------------------------


@patch("bsgateway.mcp.service.MCPService.get_cost_report")
def test_get_cost_report(mock_cost, client):
    from bsgateway.mcp.schemas import MCPCostReport

    mock_cost.return_value = MCPCostReport(
        period="day",
        total_requests=10,
        total_tokens=5000,
        by_model={},
    )
    resp = client.get(f"/api/v1/tenants/{TENANT_ID}/mcp/cost-report?period=day")
    assert resp.status_code == 200
    assert resp.json()["total_requests"] == 10


@patch("bsgateway.mcp.service.MCPService.get_usage_stats")
def test_get_usage_stats(mock_usage, client):
    from bsgateway.mcp.schemas import MCPUsageStats

    mock_usage.return_value = MCPUsageStats(
        total_requests=100,
        total_tokens=20000,
        by_model={},
        by_rule={},
    )
    resp = client.get(f"/api/v1/tenants/{TENANT_ID}/mcp/usage-stats")
    assert resp.status_code == 200
    assert resp.json()["total_requests"] == 100
