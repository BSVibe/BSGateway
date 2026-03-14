from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from bsgateway.api.deps import AuthContext, get_pool, require_admin
from bsgateway.presets.models import PresetApplyRequest
from bsgateway.presets.registry import PresetRegistry
from bsgateway.presets.schemas import (
    FeedbackCreate,
    FeedbackResponse,
    PresetApplyResponse,
    PresetSummary,
)
from bsgateway.presets.service import PresetService
from bsgateway.rules.repository import RulesRepository

router = APIRouter(tags=["presets"])

_registry = PresetRegistry()


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


@router.get("/presets", response_model=list[PresetSummary])
async def list_presets(
    _auth: AuthContext = Depends(require_admin),
) -> list[PresetSummary]:
    """List all available preset templates."""
    return [
        PresetSummary(
            name=p.name,
            description=p.description,
            intent_count=len(p.intents),
            rule_count=len(p.rules),
        )
        for p in _registry.list_all()
    ]


@router.post(
    "/tenants/{tenant_id}/presets/apply",
    response_model=PresetApplyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def apply_preset(
    tenant_id: UUID,
    body: PresetApplyRequest,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> PresetApplyResponse:
    """Apply a preset template to a tenant."""
    pool = get_pool(request)
    rules_repo = RulesRepository(pool)
    service = PresetService(rules_repo)

    try:
        result = await service.apply_preset(
            tenant_id=tenant_id,
            preset_name=body.preset_name,
            model_mapping=body.model_mapping,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PresetApplyResponse(
        preset_name=result.preset_name,
        rules_created=result.rules_created,
        intents_created=result.intents_created,
        examples_created=result.examples_created,
    )


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


@router.post(
    "/tenants/{tenant_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    tenant_id: UUID,
    body: FeedbackCreate,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> FeedbackResponse:
    """Submit feedback for a routing decision."""
    from bsgateway.presets.repository import FeedbackRepository

    pool = get_pool(request)
    repo = FeedbackRepository(pool)
    row = await repo.create_feedback(
        tenant_id=tenant_id,
        routing_id=body.routing_id,
        rating=body.rating,
        comment=body.comment,
    )
    return FeedbackResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        routing_id=row["routing_id"],
        rating=row["rating"],
        comment=row["comment"],
        created_at=row["created_at"],
    )


@router.get(
    "/tenants/{tenant_id}/feedback",
    response_model=list[FeedbackResponse],
)
async def list_feedback(
    tenant_id: UUID,
    request: Request,
    limit: int = 50,
    offset: int = 0,
    _auth: AuthContext = Depends(require_admin),
) -> list[FeedbackResponse]:
    from bsgateway.presets.repository import FeedbackRepository

    pool = get_pool(request)
    repo = FeedbackRepository(pool)
    rows = await repo.list_feedback(tenant_id, limit, offset)
    return [
        FeedbackResponse(
            id=r["id"],
            tenant_id=r["tenant_id"],
            routing_id=r["routing_id"],
            rating=r["rating"],
            comment=r["comment"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
