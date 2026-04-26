from __future__ import annotations

from collections import defaultdict
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from bsgateway.api.deps import (
    GatewayAuthContext,
    get_audit_service,
    get_cache,
    get_pool,
    require_permission,
    require_tenant_access,
)
from bsgateway.core.exceptions import DuplicateError
from bsgateway.core.utils import parse_jsonb_value, safe_json_loads
from bsgateway.embedding.provider import build_provider
from bsgateway.embedding.serialization import hydrate_intent_definitions
from bsgateway.embedding.settings import EmbeddingSettings
from bsgateway.rules.engine import RuleEngine
from bsgateway.rules.intent import IntentClassifier
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
from bsgateway.tenant.repository import TenantRepository

router = APIRouter(prefix="/tenants/{tenant_id}/rules", tags=["rules"])


def _get_repo(request: Request) -> RulesRepository:
    return RulesRepository(get_pool(request), cache=get_cache(request))


async def _validate_target_model(
    request: Request,
    tenant_id: UUID,
    target_model: str,
) -> None:
    """Validate that target_model is registered for the tenant."""
    tenant_repo = TenantRepository(get_pool(request), cache=get_cache(request))
    model = await tenant_repo.get_model_by_name(tenant_id, target_model)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model '{target_model}' is not registered for this tenant",
        )


async def _build_rule_response(
    repo: RulesRepository,
    row: asyncpg.Record,
    tenant_id: UUID,
) -> RuleResponse:
    """Build a single rule response (fetches conditions for this rule only)."""
    conditions = await repo.list_conditions(row["id"])
    return _row_to_rule_response(row, conditions)


def _row_to_rule_response(
    row: asyncpg.Record,
    conditions: list[asyncpg.Record],
) -> RuleResponse:
    """Convert a rule row + condition rows to a RuleResponse."""
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
                value=parse_jsonb_value(c["value"]),
                negate=c["negate"],
            )
            for c in conditions
        ],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _build_rule_responses_batch(
    repo: RulesRepository,
    rows: list[asyncpg.Record],
    tenant_id: UUID,
) -> list[RuleResponse]:
    """Build multiple rule responses with a single conditions query (avoids N+1).

    Rule rows may come from the cache (where ``id`` is a JSON-deserialized
    string) or from a fresh DB fetch (where it is a UUID object). Conditions
    always come from the DB and have UUID rule_ids. We normalize both sides
    to strings so the lookup works regardless of source.
    """
    all_conditions = await repo.list_conditions_for_tenant(tenant_id)
    conditions_by_rule: dict[str, list[asyncpg.Record]] = defaultdict(list)
    for c in all_conditions:
        conditions_by_rule[str(c["rule_id"])].append(c)
    return [_row_to_rule_response(r, conditions_by_rule.get(str(r["id"]), [])) for r in rows]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create routing rule",
)
async def create_rule(
    tenant_id: UUID,
    body: RuleCreate,
    request: Request,
    # Intentionally uses require_tenant_access (not require_admin) so that
    # tenant members can manage their own rules without superadmin privilege.
    _auth: GatewayAuthContext = Depends(require_tenant_access),
    _allowed: None = Depends(require_permission("bsgateway.routes.create")),
) -> RuleResponse:
    await _validate_target_model(request, tenant_id, body.target_model)
    repo = _get_repo(request)
    try:
        row = await repo.create_rule(
            tenant_id=tenant_id,
            name=body.name,
            priority=body.priority,
            target_model=body.target_model,
            is_default=body.is_default,
        )
    except DuplicateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message) from e

    if body.conditions:
        await repo.replace_conditions(
            row["id"],
            [c.model_dump() for c in body.conditions],
        )

    audit = get_audit_service(request)
    await audit.record(
        tenant_id,
        str(_auth.tenant_id),
        "rule.created",
        "rule",
        str(row["id"]),
        {"name": body.name, "target_model": body.target_model},
    )

    return await _build_rule_response(repo, row, tenant_id)


@router.post("/reorder", status_code=status.HTTP_204_NO_CONTENT, summary="Reorder rules")
async def reorder_rules(
    tenant_id: UUID,
    body: ReorderRequest,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> None:
    repo = _get_repo(request)
    await repo.reorder_rules(tenant_id, body.priorities)


# ---------------------------------------------------------------------------
# Test endpoint
# ---------------------------------------------------------------------------


@router.post("/test", response_model=RuleTestResponse, summary="Test rule matching")
async def test_rules(
    tenant_id: UUID,
    body: RuleTestRequest,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> RuleTestResponse:
    """Test which rule would match for a given request."""
    repo = _get_repo(request)
    rule_rows = await repo.list_rules(tenant_id)

    # Build routing rules with conditions (batch fetch to avoid N+1)
    all_conditions = await repo.list_conditions_for_tenant(tenant_id)
    cond_by_rule: dict[UUID, list] = defaultdict(list)
    for c in all_conditions:
        cond_by_rule[c["rule_id"]].append(c)

    rules: list[RoutingRule] = []
    for r in rule_rows:
        conditions = [
            RuleCondition(
                condition_type=c["condition_type"],
                field=c["field"],
                operator=c["operator"],
                value=parse_jsonb_value(c["value"]),
                negate=c["negate"],
            )
            for c in cond_by_rule.get(r["id"], [])
        ]
        rules.append(
            RoutingRule(
                id=str(r["id"]),
                tenant_id=str(tenant_id),
                name=r["name"],
                priority=r["priority"],
                is_active=r["is_active"],
                is_default=r["is_default"],
                target_model=r["target_model"],
                conditions=conditions,
            )
        )

    # Load tenant settings to discover the embedding model + hydrate intents
    tenant_repo = TenantRepository(get_pool(request), cache=get_cache(request))
    tenant_row = await tenant_repo.get_tenant(tenant_id)
    tenant_settings = safe_json_loads(tenant_row["settings"]) if tenant_row else {}
    embedding_settings = EmbeddingSettings.from_tenant_settings(tenant_settings)

    intent_example_rows = await repo.list_examples_for_tenant(tenant_id)
    intent_definitions = hydrate_intent_definitions(
        intent_example_rows,
        active_model=embedding_settings.model if embedding_settings else None,
    )

    tenant_config = TenantConfig(
        tenant_id=str(tenant_id),
        slug="",
        models={},
        rules=rules,
        settings=tenant_settings,
        embedding_settings=embedding_settings,
        intent_definitions=intent_definitions,
    )

    data = {"messages": body.messages, "model": body.model}

    # Check if any rule uses intent conditions
    has_intent_conditions = any(c.condition_type == "intent" for r in rules for c in r.conditions)

    # Build a classifier when both embedding settings and current intents exist.
    intent_classifier: IntentClassifier | None = None
    if embedding_settings and intent_definitions:
        provider = build_provider(embedding_settings)
        if provider is not None:

            async def _embed_one(text: str) -> list[float]:
                vectors = await provider.embed([text])
                return vectors[0]

            intent_classifier = IntentClassifier(
                embed_fn=_embed_one,
                intents=intent_definitions,
            )

    engine = RuleEngine()
    match = await engine.evaluate(data, tenant_config, intent_classifier=intent_classifier)

    # Surface a warning only when the configuration is incomplete: rules
    # reference intents but the tenant has no usable classifier (no model set
    # or all stored embeddings are stale relative to the active model).
    intent_warning = None
    if has_intent_conditions and intent_classifier is None:
        if not embedding_settings:
            intent_warning = (
                "Intent conditions present but no embedding model configured for this "
                "tenant. Set tenant.settings.embedding.model to enable intent classification."
            )
        else:
            intent_warning = (
                "Intent conditions present but no usable example embeddings found for "
                f"model '{embedding_settings.model}'. Run POST /intents/reembed to backfill."
            )

    ctx = EvaluationContext.from_request(data)

    # Resolve the rule's internal slug to a human-readable description.
    # Intent-based rules share their slug with the paired intent; the
    # intent's description field is what the operator actually typed.
    matched_display_name: str | None = None
    if match:
        matched_display_name = match.rule.name
        intent_row = await repo.get_intent_by_name(tenant_id, match.rule.name)
        if intent_row and intent_row["description"]:
            matched_display_name = intent_row["description"]

    return RuleTestResponse(
        matched_rule=(
            {
                "id": match.rule.id,
                "name": matched_display_name or match.rule.name,
                "priority": match.rule.priority,
            }
            if match
            else None
        ),
        target_model=match.target_model if match else None,
        evaluation_trace=(
            (match.trace or []) + ([{"warning": intent_warning}] if intent_warning else [])
            if match
            else ([{"warning": intent_warning}] if intent_warning else [])
        ),
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


@router.get("", response_model=list[RuleResponse], summary="List rules")
async def list_rules(
    tenant_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
    _allowed: None = Depends(require_permission("bsgateway.routes.read")),
) -> list[RuleResponse]:
    repo = _get_repo(request)
    rows = await repo.list_rules(tenant_id)
    return await _build_rule_responses_batch(repo, rows, tenant_id)


@router.get("/{rule_id}", response_model=RuleResponse, summary="Get rule")
async def get_rule(
    tenant_id: UUID,
    rule_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> RuleResponse:
    repo = _get_repo(request)
    row = await repo.get_rule(rule_id, tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return await _build_rule_response(repo, row, tenant_id)


@router.patch("/{rule_id}", response_model=RuleResponse, summary="Update rule")
async def update_rule(
    tenant_id: UUID,
    rule_id: UUID,
    body: RuleUpdate,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> RuleResponse:
    repo = _get_repo(request)
    existing = await repo.get_rule(rule_id, tenant_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")

    final_target = body.target_model or existing["target_model"]
    await _validate_target_model(request, tenant_id, final_target)

    row = await repo.update_rule(
        rule_id=rule_id,
        tenant_id=tenant_id,
        name=body.name or existing["name"],
        priority=body.priority if body.priority is not None else existing["priority"],
        is_default=(body.is_default if body.is_default is not None else existing["is_default"]),
        target_model=body.target_model or existing["target_model"],
    )
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")

    if body.conditions is not None:
        await repo.replace_conditions(
            rule_id,
            [c.model_dump() for c in body.conditions],
        )

    return await _build_rule_response(repo, row, tenant_id)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete rule")
async def delete_rule(
    tenant_id: UUID,
    rule_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> None:
    repo = _get_repo(request)
    await repo.delete_rule(rule_id, tenant_id)
    audit = get_audit_service(request)
    await audit.record(
        tenant_id,
        str(_auth.tenant_id),
        "rule.deleted",
        "rule",
        str(rule_id),
    )
