"""Tests for MCP service layer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from bsgateway.mcp.schemas import MCPCondition
from bsgateway.mcp.service import MCPService, _period_range
from bsgateway.tests.conftest import MockAcquire, MockTransaction


def _make_pool_conn():
    """Create a mock pool + conn pair for MCPService."""
    pool = MagicMock()
    pool._closed = False
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=MockTransaction())
    pool.acquire.return_value = MockAcquire(conn)
    return pool, conn


def _rule_row(
    tenant_id: UUID | None = None,
    rule_id: UUID | None = None,
    name: str = "r1",
    priority: int = 1,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": rule_id or uuid4(),
        "tenant_id": tenant_id or uuid4(),
        "name": name,
        "priority": priority,
        "is_active": True,
        "is_default": False,
        "target_model": "gpt-4o",
        "created_at": now,
        "updated_at": now,
    }


def _cond_row(rule_id: UUID) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "rule_id": rule_id,
        "condition_type": "token_count",
        "field": "estimated_tokens",
        "operator": "gt",
        "value": json.dumps(500),
        "negate": False,
    }


def _model_row(tenant_id: UUID | None = None) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "tenant_id": tenant_id or uuid4(),
        "model_name": "gpt-4o",
        "provider": "openai",
        "litellm_model": "openai/gpt-4o",
        "api_base": None,
        "extra_params": "{}",
        "created_at": datetime.now(UTC),
    }


# ---------------------------------------------------------------------------
# list_rules
# ---------------------------------------------------------------------------


async def test_list_rules_returns_rules():
    pool, conn = _make_pool_conn()
    tid = uuid4()
    rid = uuid4()
    row = _rule_row(tenant_id=tid, rule_id=rid)
    cond = _cond_row(rid)
    conn.fetch.side_effect = [
        [row],  # list_rules
        [cond],  # list_conditions_for_tenant
    ]

    svc = MCPService(pool)
    rules = await svc.list_rules(tid)
    assert len(rules) == 1
    assert rules[0].name == "r1"
    assert len(rules[0].conditions) == 1


async def test_list_rules_empty():
    pool, conn = _make_pool_conn()
    conn.fetch.return_value = []
    svc = MCPService(pool)
    result = await svc.list_rules(uuid4())
    assert result == []


# ---------------------------------------------------------------------------
# create_rule
# ---------------------------------------------------------------------------


async def test_create_rule():
    pool, conn = _make_pool_conn()
    tid = uuid4()
    rid = uuid4()
    row = _rule_row(tenant_id=tid, rule_id=rid, name="my-rule")
    conn.fetchrow.side_effect = [row, _cond_row(rid)]
    conn.execute.return_value = None
    conn.fetch.return_value = [_cond_row(rid)]

    svc = MCPService(pool)
    result = await svc.create_rule(
        tenant_id=tid,
        name="my-rule",
        conditions=[
            MCPCondition(condition_type="token_count", field="estimated_tokens", value=500),
        ],
        target_model="gpt-4o",
    )
    assert result.name == "my-rule"
    assert result.target_model == "gpt-4o"


async def test_create_rule_no_conditions():
    pool, conn = _make_pool_conn()
    tid = uuid4()
    rid = uuid4()
    row = _rule_row(tenant_id=tid, rule_id=rid)
    conn.fetchrow.return_value = row
    conn.fetch.return_value = []

    svc = MCPService(pool)
    result = await svc.create_rule(
        tenant_id=tid,
        name="default-rule",
        conditions=[],
        target_model="gpt-4o-mini",
    )
    assert result.conditions == []


# ---------------------------------------------------------------------------
# update_rule
# ---------------------------------------------------------------------------


async def test_update_rule():
    pool, conn = _make_pool_conn()
    tid = uuid4()
    rid = uuid4()
    existing = _rule_row(tenant_id=tid, rule_id=rid, name="old")
    updated = _rule_row(tenant_id=tid, rule_id=rid, name="new")
    conn.fetchrow.side_effect = [existing, updated]
    conn.fetch.return_value = []

    svc = MCPService(pool)
    result = await svc.update_rule(rid, tid, name="new")
    assert result is not None
    assert result.name == "new"


async def test_update_rule_not_found():
    pool, conn = _make_pool_conn()
    conn.fetchrow.return_value = None
    svc = MCPService(pool)
    result = await svc.update_rule(uuid4(), uuid4(), name="x")
    assert result is None


# ---------------------------------------------------------------------------
# delete_rule
# ---------------------------------------------------------------------------


async def test_delete_rule():
    pool, conn = _make_pool_conn()
    conn.execute.return_value = None
    svc = MCPService(pool)
    await svc.delete_rule(uuid4(), uuid4())  # should not raise


# ---------------------------------------------------------------------------
# list_models / register_model
# ---------------------------------------------------------------------------


async def test_list_models():
    pool, conn = _make_pool_conn()
    tid = uuid4()
    conn.fetch.return_value = [_model_row(tid)]
    svc = MCPService(pool)
    models = await svc.list_models(tid)
    assert len(models) == 1
    assert models[0].provider == "openai"


async def test_register_model():
    pool, conn = _make_pool_conn()
    tid = uuid4()
    conn.fetchrow.return_value = _model_row(tid)
    svc = MCPService(pool)
    result = await svc.register_model(
        tenant_id=tid,
        name="gpt-4o",
        provider="openai",
        config={"litellm_model": "openai/gpt-4o"},
    )
    assert result.model_name == "gpt-4o"


# ---------------------------------------------------------------------------
# simulate_routing
# ---------------------------------------------------------------------------


async def test_simulate_routing_no_rules():
    pool, conn = _make_pool_conn()
    conn.fetch.return_value = []
    svc = MCPService(pool)
    result = await svc.simulate_routing(uuid4(), "auto", "hello world")
    assert result.matched_rule is None
    assert result.target_model is None


async def test_simulate_routing_with_default_rule():
    pool, conn = _make_pool_conn()
    tid = uuid4()
    rid = uuid4()
    row = _rule_row(tenant_id=tid, rule_id=rid)
    row["is_default"] = True
    conn.fetch.side_effect = [
        [row],  # list_rules
        [],  # list_conditions_for_tenant
    ]
    svc = MCPService(pool)
    result = await svc.simulate_routing(tid, "auto", "hello")
    assert result.matched_rule is not None
    assert result.target_model == "gpt-4o"


# ---------------------------------------------------------------------------
# cost_report / usage_stats
# ---------------------------------------------------------------------------


async def test_get_cost_report():
    pool, conn = _make_pool_conn()
    conn.fetchrow.return_value = {"total_requests": 42, "total_tokens": 9000}
    conn.fetch.return_value = [
        {"resolved_model": "gpt-4o", "requests": 42, "tokens": 9000, "day": "2026-03-29"},
    ]
    svc = MCPService(pool)
    report = await svc.get_cost_report(uuid4(), "day")
    assert report.total_requests == 42
    assert report.total_tokens == 9000
    assert "gpt-4o" in report.by_model


async def test_get_usage_stats():
    pool, conn = _make_pool_conn()
    conn.fetchrow.return_value = {"total_requests": 100, "total_tokens": 20000}
    conn.fetch.side_effect = [
        [{"resolved_model": "gpt-4o", "requests": 100, "tokens": 20000, "day": "2026-03-29"}],
        [{"rule_id": uuid4(), "rule_name": "route-complex", "requests": 50}],
    ]
    svc = MCPService(pool)
    stats = await svc.get_usage_stats(uuid4())
    assert stats.total_requests == 100
    assert "route-complex" in stats.by_rule


# ---------------------------------------------------------------------------
# _period_range
# ---------------------------------------------------------------------------


def test_period_range_day():
    start, end = _period_range("day")
    assert start < end


def test_period_range_week():
    start, end = _period_range("week")
    delta = (end - start).days
    assert delta >= 7


def test_period_range_month():
    start, end = _period_range("month")
    delta = (end - start).days
    assert delta >= 30
