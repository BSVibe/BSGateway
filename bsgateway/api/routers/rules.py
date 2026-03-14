from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from bsgateway.api.deps import AuthContext, get_pool, require_admin
from bsgateway.rules.engine import RuleEngine
from bsgateway.rules.models import (
    EvaluationContext,
    RoutingRule,
    RuleCondition,
    TenantConfig,
)
from bsgateway.rules.repository import RulesRepository
from bsgateway.rules.schemas import (
    ConditionResponse,
    ReorderRequest,
    RuleCreate,
    RuleResponse,
    RuleTestRequest,
    RuleTestResponse,
    RuleUpdate,
)

router = APIRouter(prefix="/tenants/{tenant_id}/rules", tags=["rules"])


def _get_repo(request: Request) -> RulesRepository:
    return RulesRepository(get_pool(request))


def _parse_value(raw):
    """Parse JSONB value from DB record."""
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


async def _build_rule_response(
    repo: RulesRepository, row, tenant_id: UUID,
) -> RuleResponse:
    conditions = await repo.list_conditions(row["id"])
    return RuleResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        priority=row["priority"],
        is_active=row["is_active"],
        is_default=row["is_default"],
        target_model=row["target_model"],
        conditions=[
            ConditionResponse(
                id=c["id"],
                condition_type=c["condition_type"],
                field=c["field"],
                operator=c["operator"],
                value=_parse_value(c["value"]),
                negate=c["negate"],
            )
            for c in conditions
        ],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    tenant_id: UUID,
    body: RuleCreate,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> RuleResponse:
    repo = _get_repo(request)
    row = await repo.create_rule(
        tenant_id=tenant_id,
        name=body.name,
        priority=body.priority,
        target_model=body.target_model,
        is_default=body.is_default,
    )

    if body.conditions:
        await repo.replace_conditions(
            row["id"],
            [c.model_dump() for c in body.conditions],
        )

    return await _build_rule_response(repo, row, tenant_id)


@router.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_rules(
    tenant_id: UUID,
    body: ReorderRequest,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> None:
    repo = _get_repo(request)
    await repo.reorder_rules(tenant_id, body.priorities)


# ---------------------------------------------------------------------------
# Test endpoint
# ---------------------------------------------------------------------------


@router.post("/test", response_model=RuleTestResponse)
async def test_rules(
    tenant_id: UUID,
    body: RuleTestRequest,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> RuleTestResponse:
    """Test which rule would match for a given request."""
    repo = _get_repo(request)
    rule_rows = await repo.list_rules(tenant_id)

    # Build routing rules with conditions
    rules: list[RoutingRule] = []
    for r in rule_rows:
        cond_rows = await repo.list_conditions(r["id"])
        conditions = [
            RuleCondition(
                condition_type=c["condition_type"],
                field=c["field"],
                operator=c["operator"],
                value=_parse_value(c["value"]),
                negate=c["negate"],
            )
            for c in cond_rows
        ]
        rules.append(RoutingRule(
            id=str(r["id"]),
            tenant_id=str(tenant_id),
            name=r["name"],
            priority=r["priority"],
            is_active=r["is_active"],
            is_default=r["is_default"],
            target_model=r["target_model"],
            conditions=conditions,
        ))

    tenant_config = TenantConfig(
        tenant_id=str(tenant_id),
        slug="",
        models={},
        rules=rules,
    )

    data = {"messages": body.messages, "model": body.model}
    engine = RuleEngine()
    match = await engine.evaluate(data, tenant_config)

    ctx = EvaluationContext.from_request(data)

    return RuleTestResponse(
        matched_rule={
            "id": match.rule.id,
            "name": match.rule.name,
            "priority": match.rule.priority,
        } if match else None,
        target_model=match.target_model if match else None,
        evaluation_trace=match.trace if match else [],
        context={
            "estimated_tokens": ctx.estimated_tokens,
            "conversation_turns": ctx.conversation_turns,
            "has_code_blocks": ctx.has_code_blocks,
            "has_error_trace": ctx.has_error_trace,
            "tool_count": ctx.tool_count,
            "original_model": ctx.original_model,
            "classified_intent": ctx.classified_intent,
        },
    )


# ---------------------------------------------------------------------------
# Individual rule operations
# ---------------------------------------------------------------------------


@router.get("", response_model=list[RuleResponse])
async def list_rules(
    tenant_id: UUID,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> list[RuleResponse]:
    repo = _get_repo(request)
    rows = await repo.list_rules(tenant_id)
    return [await _build_rule_response(repo, r, tenant_id) for r in rows]


@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(
    tenant_id: UUID,
    rule_id: UUID,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> RuleResponse:
    repo = _get_repo(request)
    row = await repo.get_rule(rule_id, tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return await _build_rule_response(repo, row, tenant_id)


@router.patch("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    tenant_id: UUID,
    rule_id: UUID,
    body: RuleUpdate,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> RuleResponse:
    repo = _get_repo(request)
    existing = await repo.get_rule(rule_id, tenant_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")

    row = await repo.update_rule(
        rule_id=rule_id,
        tenant_id=tenant_id,
        name=body.name or existing["name"],
        priority=body.priority if body.priority is not None else existing["priority"],
        is_default=body.is_default if body.is_default is not None else existing["is_default"],
        target_model=body.target_model or existing["target_model"],
    )

    if body.conditions is not None:
        await repo.replace_conditions(
            rule_id,
            [c.model_dump() for c in body.conditions],
        )

    return await _build_rule_response(repo, row, tenant_id)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    tenant_id: UUID,
    rule_id: UUID,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> None:
    repo = _get_repo(request)
    await repo.delete_rule(rule_id, tenant_id)
