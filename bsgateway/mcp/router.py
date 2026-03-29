"""FastAPI router exposing MCP-compatible tool endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from bsgateway.api.deps import (
    GatewayAuthContext,
    get_cache,
    get_pool,
    require_tenant_access,
)
from bsgateway.core.exceptions import DuplicateError
from bsgateway.mcp.schemas import (
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

router = APIRouter(
    prefix="/tenants/{tenant_id}/mcp",
    tags=["mcp"],
)


def _get_service(request: Request) -> MCPService:
    return MCPService(get_pool(request), cache=get_cache(request))


# -- Rules -------------------------------------------------------------------


@router.get("/rules", response_model=list[MCPRuleResponse], summary="MCP: list routing rules")
async def list_rules(
    tenant_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> list[MCPRuleResponse]:
    svc = _get_service(request)
    return await svc.list_rules(tenant_id)


@router.post(
    "/rules",
    response_model=MCPRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="MCP: create routing rule",
)
async def create_rule(
    tenant_id: UUID,
    body: MCPCreateRule,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> MCPRuleResponse:
    svc = _get_service(request)
    try:
        return await svc.create_rule(
            tenant_id=tenant_id,
            name=body.name,
            conditions=body.conditions,
            target_model=body.target_model,
            priority=body.priority,
            is_default=body.is_default,
        )
    except DuplicateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message) from e


@router.patch(
    "/rules/{rule_id}",
    response_model=MCPRuleResponse,
    summary="MCP: update routing rule",
)
async def update_rule(
    tenant_id: UUID,
    rule_id: UUID,
    body: MCPUpdateRule,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> MCPRuleResponse:
    svc = _get_service(request)
    result = await svc.update_rule(
        rule_id=rule_id,
        tenant_id=tenant_id,
        name=body.name,
        conditions=body.conditions,
        target_model=body.target_model,
        priority=body.priority,
        is_default=body.is_default,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return result


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="MCP: delete routing rule",
)
async def delete_rule(
    tenant_id: UUID,
    rule_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> None:
    svc = _get_service(request)
    deleted = await svc.delete_rule(rule_id, tenant_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")


# -- Models ------------------------------------------------------------------


@router.get(
    "/models",
    response_model=list[MCPModelResponse],
    summary="MCP: list registered models",
)
async def list_models(
    tenant_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> list[MCPModelResponse]:
    svc = _get_service(request)
    return await svc.list_models(tenant_id)


@router.post(
    "/models",
    response_model=MCPModelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="MCP: register a model",
)
async def register_model(
    tenant_id: UUID,
    body: MCPRegisterModel,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> MCPModelResponse:
    svc = _get_service(request)
    try:
        return await svc.register_model(
            tenant_id=tenant_id,
            name=body.name,
            provider=body.provider,
            config=body.config,
        )
    except DuplicateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message) from e


# -- Simulate routing --------------------------------------------------------


@router.post(
    "/simulate",
    response_model=MCPSimulateResponse,
    summary="MCP: simulate routing decision",
)
async def simulate_routing(
    tenant_id: UUID,
    body: MCPSimulateRequest,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> MCPSimulateResponse:
    svc = _get_service(request)
    return await svc.simulate_routing(tenant_id, body.model_hint, body.text)


# -- Cost / Usage ------------------------------------------------------------


@router.get(
    "/cost-report",
    response_model=MCPCostReport,
    summary="MCP: cost/usage for period",
)
async def get_cost_report(
    tenant_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
    period: str = Query("day", pattern="^(day|week|month)$"),
) -> MCPCostReport:
    svc = _get_service(request)
    return await svc.get_cost_report(tenant_id, period)


@router.get(
    "/usage-stats",
    response_model=MCPUsageStats,
    summary="MCP: overall usage stats",
)
async def get_usage_stats(
    tenant_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> MCPUsageStats:
    svc = _get_service(request)
    return await svc.get_usage_stats(tenant_id)
