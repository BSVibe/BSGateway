"""TASK-003 — domain MCP tools as first-class :class:`Tool` definitions.

Pins the contract between the domain MCP surface (`MCPService`) and the
Phase-7 first-class registry from TASK-002:

* ``register_domain_tools`` registers exactly the 9 ops the existing
  FastAPI MCP router exposes today (list/create/update/delete rule,
  list/register model, simulate routing, cost report, usage stats).
* Tool names follow the ``bsgateway_mcp_<op>`` pattern surveyed in
  ``.agent/mcp-inventory.md`` so they don't collide with the admin
  catalog (``bsgateway_<subapp>_<action>``) coming in TASK-004.
* Required scopes mirror the equivalent REST routes
  (``gateway:routing:*``, ``gateway:models:*``, ``gateway:usage:read``).
* Mutating tools carry the matching ``audit_event`` literal so the
  registry's audit step fires the same gateway.* events REST does.
* Each tool's handler delegates to an :class:`MCPService` built from the
  caller's :class:`ToolContext` via an injected service factory — the
  service-layer call is what's shared between REST and MCP, never the
  router/Typer presentation.

The pre-existing REST tests in ``test_mcp_router.py`` /
``test_mcp_service.py`` are intentionally NOT touched — TASK-003 says
the domain contract must be preserved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from bsvibe_authz import User

from bsgateway.mcp.api import Tool, ToolContext, ToolError, ToolRegistry
from bsgateway.mcp.schemas import (
    MCPCostReport,
    MCPModelResponse,
    MCPRuleResponse,
    MCPSimulateResponse,
    MCPUsageStats,
)
from bsgateway.mcp.server import register_domain_tools

TENANT_ID = uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(scopes: list[str] | None = None, tenant_id: str | None = None) -> User:
    return User(
        id="user-1",
        email="u@example.com",
        active_tenant_id=tenant_id or str(TENANT_ID),
        tenants=[],
        is_service=False,
        scope=scopes or ["gateway:*"],
    )


def _make_ctx(user: User | None = None) -> ToolContext:
    return ToolContext(
        settings=MagicMock(),
        user=user or _make_user(),
        db=None,
        audit_app_state=None,
        log=MagicMock(),
    )


def _rule_response(name: str = "test-rule", rule_id: UUID | None = None) -> MCPRuleResponse:
    now = datetime.now(UTC)
    return MCPRuleResponse(
        id=rule_id or uuid4(),
        tenant_id=TENANT_ID,
        name=name,
        priority=1,
        is_active=True,
        is_default=False,
        target_model="gpt-4o",
        conditions=[],
        created_at=now,
        updated_at=now,
    )


def _model_response() -> MCPModelResponse:
    return MCPModelResponse(
        id=uuid4(),
        tenant_id=TENANT_ID,
        model_name="gpt-4o",
        provider="openai",
        litellm_model="openai/gpt-4o",
        api_base=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_service() -> MagicMock:
    svc = MagicMock()
    svc.list_rules = AsyncMock(return_value=[_rule_response()])
    svc.create_rule = AsyncMock(return_value=_rule_response(name="new-rule"))
    svc.update_rule = AsyncMock(return_value=_rule_response(name="updated"))
    svc.delete_rule = AsyncMock(return_value=True)
    svc.list_models = AsyncMock(return_value=[_model_response()])
    svc.register_model = AsyncMock(return_value=_model_response())
    svc.simulate_routing = AsyncMock(
        return_value=MCPSimulateResponse(
            matched_rule=None, target_model=None, evaluation_trace=[], context={}
        )
    )
    svc.get_cost_report = AsyncMock(
        return_value=MCPCostReport(period="day", total_requests=10, total_tokens=5000, by_model={})
    )
    svc.get_usage_stats = AsyncMock(
        return_value=MCPUsageStats(total_requests=100, total_tokens=20000, by_model={}, by_rule={})
    )
    return svc


@pytest.fixture
def registry(mock_service: MagicMock) -> ToolRegistry:
    reg = ToolRegistry()
    register_domain_tools(reg, service_factory=lambda _ctx: mock_service)
    return reg


# ---------------------------------------------------------------------------
# Catalog shape
# ---------------------------------------------------------------------------


EXPECTED_TOOLS: dict[str, dict[str, Any]] = {
    "bsgateway_mcp_list_rules": {
        "scopes": ["gateway:routing:read"],
        "audit": None,
    },
    "bsgateway_mcp_create_rule": {
        "scopes": ["gateway:routing:write"],
        "audit": "gateway.routing.rule.created",
    },
    "bsgateway_mcp_update_rule": {
        "scopes": ["gateway:routing:write"],
        "audit": "gateway.routing.rule.updated",
    },
    "bsgateway_mcp_delete_rule": {
        "scopes": ["gateway:routing:write"],
        "audit": "gateway.routing.rule.deleted",
    },
    "bsgateway_mcp_list_models": {
        "scopes": ["gateway:models:read"],
        "audit": None,
    },
    "bsgateway_mcp_register_model": {
        "scopes": ["gateway:models:write"],
        "audit": "gateway.model.created",
    },
    "bsgateway_mcp_simulate_routing": {
        "scopes": ["gateway:routing:read"],
        "audit": None,
    },
    "bsgateway_mcp_get_cost_report": {
        "scopes": ["gateway:usage:read"],
        "audit": None,
    },
    "bsgateway_mcp_get_usage_stats": {
        "scopes": ["gateway:usage:read"],
        "audit": None,
    },
}


class TestCatalogShape:
    def test_registers_all_nine_domain_tools(self, registry: ToolRegistry) -> None:
        names = set(registry.names())
        assert names == set(EXPECTED_TOOLS.keys())

    def test_each_tool_has_expected_scope_and_audit(self, registry: ToolRegistry) -> None:
        for name, expected in EXPECTED_TOOLS.items():
            tool: Tool | None = registry.get(name)
            assert tool is not None, f"missing tool: {name}"
            assert tool.required_scopes == expected["scopes"], (
                f"{name}: scopes={tool.required_scopes}, expected={expected['scopes']}"
            )
            assert tool.audit_event == expected["audit"], (
                f"{name}: audit={tool.audit_event}, expected={expected['audit']}"
            )

    def test_list_tools_emits_json_schemas(self, registry: ToolRegistry) -> None:
        listing = registry.list_tools()
        assert len(listing) == len(EXPECTED_TOOLS)
        # Every tool must declare a JSON Schema with object type.
        for item in listing:
            assert item.inputSchema["type"] == "object"
            # tenant_id is a required field on every domain tool.
            assert "tenant_id" in item.inputSchema.get("properties", {})


# ---------------------------------------------------------------------------
# Per-tool dispatch
# ---------------------------------------------------------------------------


class TestRulesTools:
    async def test_list_rules_calls_service(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        result = await registry.call_tool(
            "bsgateway_mcp_list_rules",
            {"tenant_id": str(TENANT_ID)},
            _make_ctx(),
        )
        mock_service.list_rules.assert_awaited_once_with(TENANT_ID)
        assert "rules" in result
        assert len(result["rules"]) == 1
        assert result["rules"][0]["name"] == "test-rule"

    async def test_create_rule_calls_service_with_typed_conditions(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        result = await registry.call_tool(
            "bsgateway_mcp_create_rule",
            {
                "tenant_id": str(TENANT_ID),
                "name": "new-rule",
                "target_model": "gpt-4o",
                "priority": 5,
                "conditions": [],
            },
            _make_ctx(),
        )
        mock_service.create_rule.assert_awaited_once()
        kwargs = mock_service.create_rule.await_args.kwargs
        assert kwargs["tenant_id"] == TENANT_ID
        assert kwargs["name"] == "new-rule"
        assert kwargs["target_model"] == "gpt-4o"
        assert kwargs["priority"] == 5
        assert kwargs["conditions"] == []
        assert result["name"] == "new-rule"

    async def test_update_rule_propagates_optional_fields(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        rule_id = uuid4()
        result = await registry.call_tool(
            "bsgateway_mcp_update_rule",
            {
                "tenant_id": str(TENANT_ID),
                "rule_id": str(rule_id),
                "name": "updated",
            },
            _make_ctx(),
        )
        mock_service.update_rule.assert_awaited_once()
        kwargs = mock_service.update_rule.await_args.kwargs
        assert kwargs["rule_id"] == rule_id
        assert kwargs["tenant_id"] == TENANT_ID
        assert kwargs["name"] == "updated"
        # conditions / priority etc. must default to None when omitted.
        assert kwargs["conditions"] is None
        assert kwargs["priority"] is None
        assert result["name"] == "updated"

    async def test_update_rule_not_found_raises_tool_error(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        mock_service.update_rule = AsyncMock(return_value=None)
        with pytest.raises(ToolError) as exc:
            await registry.call_tool(
                "bsgateway_mcp_update_rule",
                {
                    "tenant_id": str(TENANT_ID),
                    "rule_id": str(uuid4()),
                    "name": "x",
                },
                _make_ctx(),
            )
        assert exc.value.code == "not_found"

    async def test_delete_rule_returns_deleted_true(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        rule_id = uuid4()
        result = await registry.call_tool(
            "bsgateway_mcp_delete_rule",
            {"tenant_id": str(TENANT_ID), "rule_id": str(rule_id)},
            _make_ctx(),
        )
        mock_service.delete_rule.assert_awaited_once_with(rule_id, TENANT_ID)
        assert result == {"deleted": True}

    async def test_delete_rule_not_found_raises_tool_error(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        mock_service.delete_rule = AsyncMock(return_value=False)
        with pytest.raises(ToolError) as exc:
            await registry.call_tool(
                "bsgateway_mcp_delete_rule",
                {"tenant_id": str(TENANT_ID), "rule_id": str(uuid4())},
                _make_ctx(),
            )
        assert exc.value.code == "not_found"


class TestModelsTools:
    async def test_list_models_calls_service(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        result = await registry.call_tool(
            "bsgateway_mcp_list_models",
            {"tenant_id": str(TENANT_ID)},
            _make_ctx(),
        )
        mock_service.list_models.assert_awaited_once_with(TENANT_ID)
        assert "models" in result
        assert len(result["models"]) == 1

    async def test_register_model_passes_through_config(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        result = await registry.call_tool(
            "bsgateway_mcp_register_model",
            {
                "tenant_id": str(TENANT_ID),
                "name": "gpt-4o",
                "provider": "openai",
                "config": {"api_base": "https://api.openai.com/v1"},
            },
            _make_ctx(),
        )
        mock_service.register_model.assert_awaited_once()
        kwargs = mock_service.register_model.await_args.kwargs
        assert kwargs["tenant_id"] == TENANT_ID
        assert kwargs["name"] == "gpt-4o"
        assert kwargs["provider"] == "openai"
        assert kwargs["config"] == {"api_base": "https://api.openai.com/v1"}
        assert result["model_name"] == "gpt-4o"


class TestSimulateAndUsageTools:
    async def test_simulate_routing_calls_service(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        result = await registry.call_tool(
            "bsgateway_mcp_simulate_routing",
            {"tenant_id": str(TENANT_ID), "model_hint": "auto", "text": "hello"},
            _make_ctx(),
        )
        mock_service.simulate_routing.assert_awaited_once_with(TENANT_ID, "auto", "hello")
        assert "evaluation_trace" in result

    async def test_get_cost_report_default_period_is_day(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        result = await registry.call_tool(
            "bsgateway_mcp_get_cost_report",
            {"tenant_id": str(TENANT_ID)},
            _make_ctx(),
        )
        mock_service.get_cost_report.assert_awaited_once_with(TENANT_ID, "day")
        assert result["total_requests"] == 10

    async def test_get_cost_report_validates_period(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        with pytest.raises(ToolError) as exc:
            await registry.call_tool(
                "bsgateway_mcp_get_cost_report",
                {"tenant_id": str(TENANT_ID), "period": "year"},
                _make_ctx(),
            )
        assert exc.value.code == "invalid_input"

    async def test_get_usage_stats_calls_service(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        result = await registry.call_tool(
            "bsgateway_mcp_get_usage_stats",
            {"tenant_id": str(TENANT_ID)},
            _make_ctx(),
        )
        mock_service.get_usage_stats.assert_awaited_once_with(TENANT_ID)
        assert result["total_requests"] == 100


# ---------------------------------------------------------------------------
# Scope enforcement — tools share the dispatcher's enforcement, but we
# pin one read + one write to make sure the wiring is correct.
# ---------------------------------------------------------------------------


class TestScopeEnforcement:
    async def test_list_rules_denied_without_routing_read(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        ctx = _make_ctx(_make_user(scopes=["gateway:models:read"]))
        with pytest.raises(ToolError) as exc:
            await registry.call_tool(
                "bsgateway_mcp_list_rules",
                {"tenant_id": str(TENANT_ID)},
                ctx,
            )
        assert exc.value.code == "permission_denied"
        mock_service.list_rules.assert_not_awaited()

    async def test_create_rule_denied_without_routing_write(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        ctx = _make_ctx(_make_user(scopes=["gateway:routing:read"]))
        with pytest.raises(ToolError) as exc:
            await registry.call_tool(
                "bsgateway_mcp_create_rule",
                {
                    "tenant_id": str(TENANT_ID),
                    "name": "x",
                    "target_model": "gpt-4o",
                    "conditions": [],
                },
                ctx,
            )
        assert exc.value.code == "permission_denied"
        mock_service.create_rule.assert_not_awaited()

    async def test_gateway_prefix_wildcard_grants_subscopes(
        self, registry: ToolRegistry, mock_service: MagicMock
    ) -> None:
        ctx = _make_ctx(_make_user(scopes=["gateway:*"]))
        result = await registry.call_tool(
            "bsgateway_mcp_list_models",
            {"tenant_id": str(TENANT_ID)},
            ctx,
        )
        assert "models" in result
