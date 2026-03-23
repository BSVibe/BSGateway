from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from bsgateway.api.deps import GatewayAuthContext, get_pool, require_tenant_access
from bsgateway.presets.repository import FeedbackRepository
from bsgateway.presets.schemas import FeedbackCreate, FeedbackResponse

router = APIRouter(tags=["feedback"])


@router.post(
    "/tenants/{tenant_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit feedback",
)
async def submit_feedback(
    tenant_id: UUID,
    body: FeedbackCreate,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> FeedbackResponse:
    """Submit feedback for a routing decision."""
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
    summary="List feedback",
)
async def list_feedback(
    tenant_id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> list[FeedbackResponse]:
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
