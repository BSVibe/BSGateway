from __future__ import annotations

from uuid import UUID

from bsvibe_audit.events.base import AuditActor
from bsvibe_audit.events.gateway import ApiKeyIssued, ApiKeyRevoked
from fastapi import APIRouter, Depends, Request, status

from bsgateway.api.deps import (
    GatewayAuthContext,
    get_pool,
    require_permission,
    require_tenant_access,
)
from bsgateway.apikey.models import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyInfoResponse,
)
from bsgateway.apikey.service import ApiKeyService
from bsgateway.audit_publisher import emit_event

router = APIRouter(prefix="/tenants/{tenant_id}/api-keys", tags=["api-keys"])


def _get_apikey_service(request: Request) -> ApiKeyService:
    pool = get_pool(request)
    return ApiKeyService(pool)


@router.post(
    "",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create API key",
)
async def create_api_key(
    tenant_id: UUID,
    body: ApiKeyCreate,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
    _allowed: None = Depends(require_permission("bsgateway.api-keys.create")),
) -> ApiKeyCreatedResponse:
    svc = _get_apikey_service(request)
    result = await svc.create_key(
        tenant_id,
        body.name,
        scopes=body.scopes,
        expires_in_days=body.expires_in_days,
    )
    # Phase Audit Batch 2 — gateway.api_key.issued. Emitted post-create
    # (best-effort): the raw key is *not* in the payload (only id,
    # prefix, name, scopes) so audit logs never carry a usable secret.
    await emit_event(
        request.app.state,
        ApiKeyIssued(
            actor=AuditActor(type="user", id=str(_auth.identity.id), email=_auth.identity.email),
            tenant_id=str(tenant_id),
            data={
                "key_id": str(result.id),
                "key_prefix": result.key_prefix,
                "name": result.name,
                "scopes": list(result.scopes),
                "expires_in_days": body.expires_in_days,
            },
        ),
    )
    return ApiKeyCreatedResponse.model_validate(result)


@router.get(
    "",
    response_model=list[ApiKeyInfoResponse],
    summary="List API keys",
)
async def list_api_keys(
    tenant_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
    _allowed: None = Depends(require_permission("bsgateway.api-keys.read")),
) -> list[ApiKeyInfoResponse]:
    svc = _get_apikey_service(request)
    keys = await svc.list_keys(tenant_id)
    return [ApiKeyInfoResponse.model_validate(k) for k in keys]


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke API key",
)
async def revoke_api_key(
    tenant_id: UUID,
    key_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
    _allowed: None = Depends(require_permission("bsgateway.api-keys.delete")),
) -> None:
    svc = _get_apikey_service(request)
    await svc.revoke_key(key_id, tenant_id)
    # Phase Audit Batch 2 — gateway.api_key.revoked.
    await emit_event(
        request.app.state,
        ApiKeyRevoked(
            actor=AuditActor(type="user", id=str(_auth.identity.id), email=_auth.identity.email),
            tenant_id=str(tenant_id),
            data={"key_id": str(key_id)},
        ),
    )
