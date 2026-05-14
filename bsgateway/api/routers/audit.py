from __future__ import annotations

import asyncio
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from bsgateway.api.deps import (
    GatewayAuthContext,
    get_pool,
    require_permission,
    require_tenant_access,
)
from bsgateway.audit.repository import AuditRepository
from bsgateway.core.utils import safe_json_loads

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/tenants/{tenant_id}/audit",
    tags=["audit"],
)


class AuditLogResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    actor: str
    action: str
    resource_type: str
    resource_id: str
    details: dict
    created_at: str


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int


@router.get("", response_model=AuditLogListResponse, summary="List audit logs")
async def list_audit_logs(
    tenant_id: UUID,
    request: Request,
    auth: GatewayAuthContext = Depends(require_tenant_access),
    _allowed: None = Depends(require_permission("bsgateway.audit.read")),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AuditLogListResponse:
    """List audit logs for a tenant."""
    pool = get_pool(request)
    repo = AuditRepository(pool)
    rows, total = await asyncio.gather(
        repo.list_by_tenant(tenant_id, limit, offset),
        repo.count_by_tenant(tenant_id),
    )

    items = [
        AuditLogResponse(
            id=row["id"],
            tenant_id=row["tenant_id"],
            actor=row["actor"],
            action=row["action"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            details=safe_json_loads(row["details"]),
            created_at=row["created_at"].isoformat() if row["created_at"] else "",
        )
        for row in rows
    ]
    return AuditLogListResponse(items=items, total=total)
