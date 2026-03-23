from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from bsgateway.api.deps import (
    GatewayAuthContext,
    get_audit_service,
    get_cache,
    get_encryption_key,
    get_pool,
    require_admin,
    require_tenant_access,
)
from bsgateway.core.exceptions import DuplicateError
from bsgateway.tenant.models import (
    TenantCreate,
    TenantModelCreate,
    TenantModelResponse,
    TenantModelUpdate,
    TenantResponse,
    TenantUpdate,
)
from bsgateway.tenant.repository import TenantRepository
from bsgateway.tenant.service import TenantService

router = APIRouter(prefix="/tenants", tags=["tenants"])


def get_tenant_service(request: Request) -> TenantService:
    """DI dependency for TenantService."""
    pool = get_pool(request)
    encryption_key = get_encryption_key(request)
    cache = get_cache(request)
    return TenantService(TenantRepository(pool, cache=cache), encryption_key)


# ---------------------------------------------------------------------------
# Tenant CRUD
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create tenant",
    description="Create a new multi-tenant workspace. Requires admin role.",
)
async def create_tenant(
    body: TenantCreate,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_admin),
) -> TenantResponse:
    svc = get_tenant_service(request)
    try:
        result = await svc.create_tenant(body.name, body.slug, body.settings)
    except DuplicateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message) from e
    audit = get_audit_service(request)
    await audit.record(
        result.id,
        str(_auth.tenant_id),
        "tenant.created",
        "tenant",
        str(result.id),
        {"name": body.name, "slug": body.slug},
    )
    return result


@router.get("", response_model=list[TenantResponse], summary="List tenants")
async def list_tenants(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _auth: GatewayAuthContext = Depends(require_admin),
) -> list[TenantResponse]:
    svc = get_tenant_service(request)
    return await svc.list_tenants(limit, offset)


@router.get("/{tenant_id}", response_model=TenantResponse, summary="Get tenant")
async def get_tenant(
    tenant_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> TenantResponse:
    svc = get_tenant_service(request)
    tenant = await svc.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.patch("/{tenant_id}", response_model=TenantResponse, summary="Update tenant")
async def update_tenant(
    tenant_id: UUID,
    body: TenantUpdate,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_admin),
) -> TenantResponse:
    svc = get_tenant_service(request)
    existing = await svc.get_tenant(tenant_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant = await svc.update_tenant(
        tenant_id,
        name=body.name or existing.name,
        slug=body.slug or existing.slug,
        settings=body.settings if body.settings is not None else existing.settings,
    )
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate tenant")
async def deactivate_tenant(
    tenant_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_admin),
) -> None:
    svc = get_tenant_service(request)
    await svc.deactivate_tenant(tenant_id)
    audit = get_audit_service(request)
    await audit.record(
        tenant_id,
        str(_auth.tenant_id),
        "tenant.deactivated",
        "tenant",
        str(tenant_id),
    )


# ---------------------------------------------------------------------------
# Tenant Models
# ---------------------------------------------------------------------------


@router.post(
    "/{tenant_id}/models",
    response_model=TenantModelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register model",
)
async def create_model(
    tenant_id: UUID,
    body: TenantModelCreate,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> TenantModelResponse:
    svc = get_tenant_service(request)
    try:
        result = await svc.create_model(tenant_id, body)
    except DuplicateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    audit = get_audit_service(request)
    provider = body.litellm_model.split("/")[0] if "/" in body.litellm_model else "unknown"
    await audit.record(
        tenant_id,
        str(_auth.tenant_id),
        "model.created",
        "model",
        str(result.id),
        {"model_name": body.model_name, "provider": provider},
    )
    return result


@router.get("/{tenant_id}/models", response_model=list[TenantModelResponse], summary="List models")
async def list_models(
    tenant_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> list[TenantModelResponse]:
    svc = get_tenant_service(request)
    return await svc.list_models(tenant_id)


@router.get(
    "/{tenant_id}/models/{model_id}",
    response_model=TenantModelResponse,
    summary="Get model",
)
async def get_model(
    tenant_id: UUID,
    model_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> TenantModelResponse:
    svc = get_tenant_service(request)
    model = await svc.get_model(model_id, tenant_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.patch(
    "/{tenant_id}/models/{model_id}",
    response_model=TenantModelResponse,
    summary="Update model",
)
async def update_model(
    tenant_id: UUID,
    model_id: UUID,
    body: TenantModelUpdate,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> TenantModelResponse:
    svc = get_tenant_service(request)
    try:
        model = await svc.update_model(model_id, tenant_id, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.delete(
    "/{tenant_id}/models/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete model",
)
async def delete_model(
    tenant_id: UUID,
    model_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> None:
    svc = get_tenant_service(request)
    await svc.delete_model(model_id, tenant_id)
    audit = get_audit_service(request)
    await audit.record(
        tenant_id,
        str(_auth.tenant_id),
        "model.deleted",
        "model",
        str(model_id),
    )
