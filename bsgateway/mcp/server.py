"""Domain MCP tools wired as first-class :class:`Tool` definitions (TASK-003).

The pre-existing FastAPI router in :mod:`bsgateway.mcp.router` and the
service-layer in :mod:`bsgateway.mcp.service` continue to back the REST
surface — this module wraps the same :class:`MCPService` methods as
first-class tools so the Phase-7 MCP transports (HTTP `/mcp` and stdio)
can call them through the single dispatcher introduced in TASK-002.

Each tool's handler delegates to ``MCPService`` directly; CLI and MCP
both call the service layer, never each other's presentation surface.
The schemas declared here are thin wrappers around the existing
:mod:`bsgateway.mcp.schemas` models — they add the ``tenant_id`` (and
``rule_id`` where applicable) that REST routes carry as path params, and
list-shaped responses get a containing model so the dispatcher's
``output_schema`` requirement is satisfied without leaking
implementation details to callers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from bsgateway.mcp.api import Tool, ToolContext, ToolError, ToolRegistry
from bsgateway.mcp.schemas import (
    MCPCondition,
    MCPCostReport,
    MCPCreateRule,
    MCPModelResponse,
    MCPRegisterModel,
    MCPRuleResponse,
    MCPSimulateRequest,
    MCPSimulateResponse,
    MCPUpdateRule,
    MCPUsageStats,
)
from bsgateway.mcp.service import MCPService

_ServiceFactory = Callable[[ToolContext], MCPService]


# ---------------------------------------------------------------------------
# Tool I/O schemas — wrap REST schemas with tenant_id / rule_id +
# list-output containers (Pydantic v2 models, not bare ``list[...]``).
# ---------------------------------------------------------------------------


class _TenantScoped(BaseModel):
    """Mixin: every domain tool requires the caller's ``tenant_id``."""

    tenant_id: UUID


class ListRulesInput(_TenantScoped):
    pass


class ListRulesOutput(BaseModel):
    rules: list[MCPRuleResponse] = Field(default_factory=list)


class CreateRuleInput(_TenantScoped, MCPCreateRule):
    pass


class UpdateRuleInput(_TenantScoped, MCPUpdateRule):
    rule_id: UUID


class DeleteRuleInput(_TenantScoped):
    rule_id: UUID


class DeleteRuleOutput(BaseModel):
    deleted: bool


class ListModelsInput(_TenantScoped):
    pass


class ListModelsOutput(BaseModel):
    models: list[MCPModelResponse] = Field(default_factory=list)


class RegisterModelInput(_TenantScoped, MCPRegisterModel):
    pass


class SimulateRoutingInput(_TenantScoped, MCPSimulateRequest):
    pass


class GetCostReportInput(_TenantScoped):
    period: Literal["day", "week", "month"] = "day"


class GetUsageStatsInput(_TenantScoped):
    pass


# ---------------------------------------------------------------------------
# Handler factories — each returns an ``async def`` closed over the
# injected service factory so the dispatcher can invoke it uniformly.
# ---------------------------------------------------------------------------


def _list_rules_handler(factory: _ServiceFactory):
    async def handler(args: ListRulesInput, ctx: ToolContext) -> ListRulesOutput:
        svc = factory(ctx)
        rules = await svc.list_rules(args.tenant_id)
        return ListRulesOutput(rules=rules)

    return handler


def _create_rule_handler(factory: _ServiceFactory):
    async def handler(args: CreateRuleInput, ctx: ToolContext) -> MCPRuleResponse:
        svc = factory(ctx)
        return await svc.create_rule(
            tenant_id=args.tenant_id,
            name=args.name,
            conditions=list(args.conditions),
            target_model=args.target_model,
            priority=args.priority,
            is_default=args.is_default,
        )

    return handler


def _update_rule_handler(factory: _ServiceFactory):
    async def handler(args: UpdateRuleInput, ctx: ToolContext) -> MCPRuleResponse:
        svc = factory(ctx)
        result = await svc.update_rule(
            rule_id=args.rule_id,
            tenant_id=args.tenant_id,
            name=args.name,
            conditions=(list(args.conditions) if args.conditions is not None else None),
            target_model=args.target_model,
            priority=args.priority,
            is_default=args.is_default,
        )
        if result is None:
            raise ToolError(code="not_found", message="Rule not found")
        return result

    return handler


def _delete_rule_handler(factory: _ServiceFactory):
    async def handler(args: DeleteRuleInput, ctx: ToolContext) -> DeleteRuleOutput:
        svc = factory(ctx)
        deleted = await svc.delete_rule(args.rule_id, args.tenant_id)
        if not deleted:
            raise ToolError(code="not_found", message="Rule not found")
        return DeleteRuleOutput(deleted=True)

    return handler


def _list_models_handler(factory: _ServiceFactory):
    async def handler(args: ListModelsInput, ctx: ToolContext) -> ListModelsOutput:
        svc = factory(ctx)
        models = await svc.list_models(args.tenant_id)
        return ListModelsOutput(models=models)

    return handler


def _register_model_handler(factory: _ServiceFactory):
    async def handler(args: RegisterModelInput, ctx: ToolContext) -> MCPModelResponse:
        svc = factory(ctx)
        return await svc.register_model(
            tenant_id=args.tenant_id,
            name=args.name,
            provider=args.provider,
            config=dict(args.config),
        )

    return handler


def _simulate_handler(factory: _ServiceFactory):
    async def handler(args: SimulateRoutingInput, ctx: ToolContext) -> MCPSimulateResponse:
        svc = factory(ctx)
        return await svc.simulate_routing(args.tenant_id, args.model_hint, args.text)

    return handler


def _cost_report_handler(factory: _ServiceFactory):
    async def handler(args: GetCostReportInput, ctx: ToolContext) -> MCPCostReport:
        svc = factory(ctx)
        return await svc.get_cost_report(args.tenant_id, args.period)

    return handler


def _usage_stats_handler(factory: _ServiceFactory):
    async def handler(args: GetUsageStatsInput, ctx: ToolContext) -> MCPUsageStats:
        svc = factory(ctx)
        return await svc.get_usage_stats(args.tenant_id)

    return handler


# ---------------------------------------------------------------------------
# Public registration — single entry point used by the lifespan wiring
# (TASK-005) and by tests.
# ---------------------------------------------------------------------------


def register_domain_tools(
    registry: ToolRegistry,
    *,
    service_factory: _ServiceFactory,
) -> None:
    """Register the 9 pre-existing domain MCP operations on ``registry``.

    ``service_factory`` builds an :class:`MCPService` for each call —
    production wiring (TASK-005) reads ``ctx.audit_app_state`` for the
    DB pool + cache; tests inject a mock returning a stub service.
    """
    tools: list[Tool] = [
        Tool(
            name="bsgateway_mcp_list_rules",
            description="List routing rules for a tenant.",
            input_schema=ListRulesInput,
            output_schema=ListRulesOutput,
            handler=_list_rules_handler(service_factory),
            required_scopes=["gateway:routing:read"],
        ),
        Tool(
            name="bsgateway_mcp_create_rule",
            description="Create a routing rule for a tenant.",
            input_schema=CreateRuleInput,
            output_schema=MCPRuleResponse,
            handler=_create_rule_handler(service_factory),
            required_scopes=["gateway:routing:write"],
            audit_event="gateway.routing.rule.created",
        ),
        Tool(
            name="bsgateway_mcp_update_rule",
            description="Update a routing rule (partial — None fields preserved).",
            input_schema=UpdateRuleInput,
            output_schema=MCPRuleResponse,
            handler=_update_rule_handler(service_factory),
            required_scopes=["gateway:routing:write"],
            audit_event="gateway.routing.rule.updated",
        ),
        Tool(
            name="bsgateway_mcp_delete_rule",
            description="Delete a routing rule by id.",
            input_schema=DeleteRuleInput,
            output_schema=DeleteRuleOutput,
            handler=_delete_rule_handler(service_factory),
            required_scopes=["gateway:routing:write"],
            audit_event="gateway.routing.rule.deleted",
        ),
        Tool(
            name="bsgateway_mcp_list_models",
            description="List registered models for a tenant.",
            input_schema=ListModelsInput,
            output_schema=ListModelsOutput,
            handler=_list_models_handler(service_factory),
            required_scopes=["gateway:models:read"],
        ),
        Tool(
            name="bsgateway_mcp_register_model",
            description="Register a model for a tenant.",
            input_schema=RegisterModelInput,
            output_schema=MCPModelResponse,
            handler=_register_model_handler(service_factory),
            required_scopes=["gateway:models:write"],
            audit_event="gateway.model.created",
        ),
        Tool(
            name="bsgateway_mcp_simulate_routing",
            description="Simulate the routing decision for a hypothetical request.",
            input_schema=SimulateRoutingInput,
            output_schema=MCPSimulateResponse,
            handler=_simulate_handler(service_factory),
            required_scopes=["gateway:routing:read"],
        ),
        Tool(
            name="bsgateway_mcp_get_cost_report",
            description="Cost / token totals for a tenant over the chosen period.",
            input_schema=GetCostReportInput,
            output_schema=MCPCostReport,
            handler=_cost_report_handler(service_factory),
            required_scopes=["gateway:usage:read"],
        ),
        Tool(
            name="bsgateway_mcp_get_usage_stats",
            description="Aggregate usage stats for a tenant (last 30 days).",
            input_schema=GetUsageStatsInput,
            output_schema=MCPUsageStats,
            handler=_usage_stats_handler(service_factory),
            required_scopes=["gateway:usage:read"],
        ),
    ]
    for tool in tools:
        registry.register(tool)


# Re-exported so callers don't have to know which schema lives where.
__all__ = [
    "CreateRuleInput",
    "DeleteRuleInput",
    "DeleteRuleOutput",
    "GetCostReportInput",
    "GetUsageStatsInput",
    "ListModelsInput",
    "ListModelsOutput",
    "ListRulesInput",
    "ListRulesOutput",
    "MCPCondition",
    "RegisterModelInput",
    "SimulateRoutingInput",
    "UpdateRuleInput",
    "register_domain_tools",
]
