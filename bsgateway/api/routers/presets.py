from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from bsgateway.api.deps import AuthContext, get_pool, require_admin
from bsgateway.presets.models import PresetApplyRequest
from bsgateway.presets.registry import PresetRegistry
from bsgateway.presets.schemas import PresetApplyResponse, PresetSummary
from bsgateway.presets.service import PresetService
from bsgateway.rules.repository import RulesRepository
from bsgateway.tenant.repository import TenantRepository

router = APIRouter(tags=["presets"])

_registry = PresetRegistry()


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
    tenant_repo = TenantRepository(pool)
    service = PresetService(rules_repo, tenant_repo)

    try:
        result = await service.apply_preset(
            tenant_id=tenant_id,
            preset_name=body.preset_name,
            model_mapping=body.model_mapping,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return PresetApplyResponse(
        preset_name=result.preset_name,
        rules_created=result.rules_created,
        intents_created=result.intents_created,
        examples_created=result.examples_created,
    )
