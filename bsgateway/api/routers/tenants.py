from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from bsgateway.api.deps import AuthContext, get_encryption_key, get_pool, require_admin
from bsgateway.tenant.models import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
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


def _get_service(request: Request) -> TenantService:
    pool = get_pool(request)
    encryption_key = get_encryption_key(request)
    return TenantService(TenantRepository(pool), encryption_key)


# ---------------------------------------------------------------------------
# Tenant CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> TenantResponse:
    svc = _get_service(request)
    return await svc.create_tenant(body.name, body.slug, body.settings)


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    _auth: AuthContext = Depends(require_admin),
) -> list[TenantResponse]:
    svc = _get_service(request)
    return await svc.list_tenants(limit, offset)


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: UUID,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> TenantResponse:
    svc = _get_service(request)
    tenant = await svc.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: UUID,
    body: TenantUpdate,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> TenantResponse:
    svc = _get_service(request)
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


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_tenant(
    tenant_id: UUID,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> None:
    svc = _get_service(request)
    await svc.deactivate_tenant(tenant_id)


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------


@router.post(
    "/{tenant_id}/keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    tenant_id: UUID,
    body: ApiKeyCreate,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> ApiKeyCreatedResponse:
    svc = _get_service(request)
    tenant = await svc.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return await svc.create_api_key(tenant_id, body.name, body.scopes)


@router.get("/{tenant_id}/keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    tenant_id: UUID,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> list[ApiKeyResponse]:
    svc = _get_service(request)
    return await svc.list_api_keys(tenant_id)


@router.delete("/{tenant_id}/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    tenant_id: UUID,
    key_id: UUID,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> None:
    svc = _get_service(request)
    await svc.revoke_api_key(key_id, tenant_id)


# ---------------------------------------------------------------------------
# Tenant Models
# ---------------------------------------------------------------------------


@router.post(
    "/{tenant_id}/models",
    response_model=TenantModelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_model(
    tenant_id: UUID,
    body: TenantModelCreate,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> TenantModelResponse:
    svc = _get_service(request)
    return await svc.create_model(tenant_id, body)


@router.get("/{tenant_id}/models", response_model=list[TenantModelResponse])
async def list_models(
    tenant_id: UUID,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> list[TenantModelResponse]:
    svc = _get_service(request)
    return await svc.list_models(tenant_id)


@router.get("/{tenant_id}/models/{model_id}", response_model=TenantModelResponse)
async def get_model(
    tenant_id: UUID,
    model_id: UUID,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> TenantModelResponse:
    svc = _get_service(request)
    model = await svc.get_model(model_id, tenant_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.patch("/{tenant_id}/models/{model_id}", response_model=TenantModelResponse)
async def update_model(
    tenant_id: UUID,
    model_id: UUID,
    body: TenantModelUpdate,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> TenantModelResponse:
    svc = _get_service(request)
    model = await svc.update_model(model_id, tenant_id, body)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.delete("/{tenant_id}/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    tenant_id: UUID,
    model_id: UUID,
    request: Request,
    _auth: AuthContext = Depends(require_admin),
) -> None:
    svc = _get_service(request)
    await svc.delete_model(model_id, tenant_id)
