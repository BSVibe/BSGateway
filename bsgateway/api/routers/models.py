"""Phase 3 / TASK-005 — admin REST surface for the per-tenant ``models``
table.

The router is the **only** mutation site for the yaml-union-DB merge
that ``ModelRegistryService`` caches. Every write therefore:

* enforces ``gateway:models:write`` (Phase 1 scope cutover),
* calls ``registry.invalidate(tenant_id)`` so the next routing
  decision sees the new state without a process restart,
* records a ``model.created`` / ``model.updated`` / ``model.deleted``
  audit row through :class:`AuditService`. ``litellm_params`` is
  **never** echoed into the audit payload — provider credentials
  may live there.

GET reads enforce ``gateway:models:read`` and return the *effective*
list (yaml-union-DB) so callers don't have to re-implement the merge.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from bsvibe_audit.events.base import AuditActor
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator

from bsgateway.api.deps import (
    GatewayAuthContext,
    get_audit_service,
    get_auth_context,
    get_model_registry,
    get_pool,
    require_scope,
)
from bsgateway.audit.events import (
    ModelCreated,
    ModelDeleted,
    ModelHidden,
    ModelUpdated,
)
from bsgateway.audit_publisher import emit_event
from bsgateway.routing.models_repository import ModelsRepository

router = APIRouter(prefix="/admin/models", tags=["admin-models"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class EffectiveModel(BaseModel):
    """One entry in the effective (yaml-union-DB) model list.

    ``has_litellm_params`` is a boolean stand-in for the real value —
    callers see whether per-model overrides exist without provider
    credentials leaking into the response body.
    """

    name: str
    origin: Literal["system", "custom"]
    is_passthrough: bool
    litellm_model: str | None
    has_litellm_params: bool
    id: UUID | None = None
    tenant_id: UUID | None = None


class ModelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    origin: Literal["custom", "hide_system"]
    litellm_model: str | None = Field(None, max_length=255)
    litellm_params: dict | None = None
    is_passthrough: bool = True

    @model_validator(mode="after")
    def _check_origin_payload(self) -> ModelCreate:
        if self.origin == "custom" and not self.litellm_model:
            raise ValueError("custom origin requires litellm_model")
        if self.origin == "hide_system" and (self.litellm_model or self.litellm_params):
            raise ValueError("hide_system origin must not carry litellm payload")
        return self


class ModelUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    origin: Literal["custom", "hide_system"] | None = None
    litellm_model: str | None = Field(None, max_length=255)
    litellm_params: dict | None = None
    is_passthrough: bool | None = None

    model_config = {"extra": "forbid"}


class ModelResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    origin: Literal["custom", "hide_system"]
    litellm_model: str | None
    has_litellm_params: bool
    is_passthrough: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(row: dict) -> ModelResponse:
    return ModelResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        origin=row["origin"],
        litellm_model=row["litellm_model"],
        has_litellm_params=row.get("litellm_params") is not None,
        is_passthrough=row["is_passthrough"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _get_repo(request: Request) -> ModelsRepository:
    return ModelsRepository(get_pool(request))


async def _invalidate(registry: object | None, tenant_id: UUID) -> None:
    """Best-effort registry invalidation. Lifespan may have failed to
    attach the registry (``app.state.model_registry == None``); we still
    let mutations succeed in that case so the admin surface is usable
    against a degraded baseline. The next process restart will pick up
    fresh state from the DB anyway.
    """
    if registry is None:
        return
    await registry.invalidate(tenant_id)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[EffectiveModel],
    summary="List effective models",
)
async def list_effective_models(
    request: Request,
    _scope: None = Depends(require_scope("gateway:models:read")),
    auth: GatewayAuthContext = Depends(get_auth_context),
    registry=Depends(get_model_registry),
) -> list[EffectiveModel]:
    """Return the merged yaml-union-DB list for the caller's tenant.

    Bootstrap admins (``tenant_id == UUID(int=0)``) see only the yaml
    half — there is no per-tenant DB row keyed by the all-zeros UUID.
    """
    if registry is None:
        # Registry attachment failed at boot — surface an empty effective
        # list rather than 500ing. Operators see ``model_registry_attach_failed``
        # in logs already.
        return []
    entries = await registry.list_models(auth.tenant_id)
    return [
        EffectiveModel(
            name=m.name,
            origin="custom" if m.origin == "custom" else "system",
            is_passthrough=m.is_passthrough,
            litellm_model=m.litellm_model,
            has_litellm_params=m.litellm_params is not None,
            id=m.id,
            tenant_id=m.tenant_id,
        )
        for m in entries
    ]


@router.post(
    "",
    response_model=ModelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add custom or hide_system model",
)
async def create_model(
    request: Request,
    body: Annotated[ModelCreate, Body()],
    _scope: None = Depends(require_scope("gateway:models:write")),
    auth: GatewayAuthContext = Depends(get_auth_context),
    registry=Depends(get_model_registry),
) -> ModelResponse:
    repo = _get_repo(request)
    try:
        row = await repo.create_model(
            tenant_id=auth.tenant_id,
            name=body.name,
            origin=body.origin,
            litellm_model=body.litellm_model,
            litellm_params=body.litellm_params,
            is_passthrough=body.is_passthrough,
        )
    except Exception as exc:  # asyncpg.UniqueViolationError, etc.
        # Surface duplicate (tenant_id, name) as 409.
        if "models_tenant_id_name_key" in str(exc) or "duplicate key" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Model '{body.name}' already exists for this tenant",
            ) from exc
        raise

    await _invalidate(registry, auth.tenant_id)

    payload = {
        "name": body.name,
        "origin": body.origin,
        "is_passthrough": body.is_passthrough,
        "has_litellm_params": body.litellm_params is not None,
    }
    audit = get_audit_service(request)
    await audit.record(
        auth.tenant_id,
        str(auth.identity.id),
        "model.created",
        "model",
        str(row["id"]),
        payload,
    )
    event_cls = ModelHidden if body.origin == "hide_system" else ModelCreated
    await emit_event(
        request.app.state,
        event_cls(
            actor=AuditActor(type="user", id=str(auth.identity.id), email=auth.identity.email),
            tenant_id=str(auth.tenant_id),
            data={"target_id": str(row["id"]), **payload},
        ),
    )
    return _to_response(row)


@router.patch(
    "/{model_id}",
    response_model=ModelResponse,
    summary="Update model",
)
async def update_model(
    model_id: UUID,
    body: ModelUpdate,
    request: Request,
    _scope: None = Depends(require_scope("gateway:models:write")),
    auth: GatewayAuthContext = Depends(get_auth_context),
    registry=Depends(get_model_registry),
) -> ModelResponse:
    repo = _get_repo(request)
    existing = await repo.get_model(model_id, auth.tenant_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Model not found")

    fields = body.model_dump(exclude_unset=True)
    row = await repo.update_model(
        model_id=model_id,
        tenant_id=auth.tenant_id,
        name=fields.get("name"),
        origin=fields.get("origin"),
        litellm_model=fields.get("litellm_model"),
        litellm_params=fields.get("litellm_params"),
        is_passthrough=fields.get("is_passthrough"),
        litellm_model_set="litellm_model" in fields,
        litellm_params_set="litellm_params" in fields,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")

    await _invalidate(registry, auth.tenant_id)

    audit = get_audit_service(request)
    await audit.record(
        auth.tenant_id,
        str(auth.identity.id),
        "model.updated",
        "model",
        str(model_id),
        {"changed_fields": sorted(fields.keys())},
    )
    await emit_event(
        request.app.state,
        ModelUpdated(
            actor=AuditActor(type="user", id=str(auth.identity.id), email=auth.identity.email),
            tenant_id=str(auth.tenant_id),
            data={
                "target_id": str(model_id),
                "changed_fields": sorted(fields.keys()),
            },
        ),
    )
    return _to_response(row)


@router.delete(
    "/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete model",
)
async def delete_model(
    model_id: UUID,
    request: Request,
    _scope: None = Depends(require_scope("gateway:models:write")),
    auth: GatewayAuthContext = Depends(get_auth_context),
    registry=Depends(get_model_registry),
) -> None:
    repo = _get_repo(request)
    existing = await repo.get_model(model_id, auth.tenant_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Model not found")

    await repo.delete_model(model_id, auth.tenant_id)
    await _invalidate(registry, auth.tenant_id)

    audit = get_audit_service(request)
    await audit.record(
        auth.tenant_id,
        str(auth.identity.id),
        "model.deleted",
        "model",
        str(model_id),
    )
    await emit_event(
        request.app.state,
        ModelDeleted(
            actor=AuditActor(type="user", id=str(auth.identity.id), email=auth.identity.email),
            tenant_id=str(auth.tenant_id),
            data={"target_id": str(model_id)},
        ),
    )
