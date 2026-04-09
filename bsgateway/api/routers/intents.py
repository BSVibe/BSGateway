from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from bsgateway.api.deps import GatewayAuthContext, get_cache, get_pool, require_tenant_access
from bsgateway.embedding.factory import build_service_for_tenant
from bsgateway.embedding.service import EmbeddingService
from bsgateway.rules.repository import RulesRepository
from bsgateway.rules.schemas import (
    ExampleCreate,
    ExampleResponse,
    IntentCreate,
    IntentResponse,
    IntentUpdate,
    ReembedResponse,
)
from bsgateway.tenant.repository import TenantRepository

router = APIRouter(prefix="/tenants/{tenant_id}/intents", tags=["intents"])


def _get_repo(request: Request) -> RulesRepository:
    return RulesRepository(get_pool(request), cache=get_cache(request))


def _get_tenant_repo(request: Request) -> TenantRepository:
    return TenantRepository(get_pool(request), cache=get_cache(request))


async def _get_embedding_service(request: Request, tenant_id: UUID) -> EmbeddingService | None:
    return await build_service_for_tenant(_get_tenant_repo(request), tenant_id)


def _to_response(row: asyncpg.Record) -> IntentResponse:
    return IntentResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        description=row["description"],
        threshold=row["threshold"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post(
    "",
    response_model=IntentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create intent",
)
async def create_intent(
    tenant_id: UUID,
    body: IntentCreate,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> IntentResponse:
    repo = _get_repo(request)
    row = await repo.create_intent(
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        threshold=body.threshold,
    )

    # Generate embeddings for examples in a single batch call when an embedding
    # service is configured for the tenant. Failures degrade gracefully — the
    # example row is still inserted, just without an embedding, and can be
    # backfilled later via /reembed.
    embed_svc = await _get_embedding_service(request, tenant_id)
    if embed_svc and body.examples:
        embedded = await embed_svc.embed_many(list(body.examples))
        for ex in embedded:
            await repo.add_example(
                row["id"],
                ex.text,
                embedding=ex.embedding,
                embedding_model=ex.model if ex.embedding else None,
            )
    else:
        for example_text in body.examples:
            await repo.add_example(row["id"], example_text)

    return _to_response(row)


@router.get("", response_model=list[IntentResponse], summary="List intents")
async def list_intents(
    tenant_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> list[IntentResponse]:
    repo = _get_repo(request)
    rows = await repo.list_intents(tenant_id)
    return [_to_response(r) for r in rows]


@router.get("/{intent_id}", response_model=IntentResponse, summary="Get intent")
async def get_intent(
    tenant_id: UUID,
    intent_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> IntentResponse:
    repo = _get_repo(request)
    row = await repo.get_intent(intent_id, tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Intent not found")
    return _to_response(row)


@router.patch("/{intent_id}", response_model=IntentResponse, summary="Update intent")
async def update_intent(
    tenant_id: UUID,
    intent_id: UUID,
    body: IntentUpdate,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> IntentResponse:
    repo = _get_repo(request)
    existing = await repo.get_intent(intent_id, tenant_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Intent not found")

    row = await repo.update_intent(
        intent_id=intent_id,
        tenant_id=tenant_id,
        name=body.name or existing["name"],
        description=(body.description if body.description is not None else existing["description"]),
        threshold=(body.threshold if body.threshold is not None else existing["threshold"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Intent not found")
    return _to_response(row)


@router.delete("/{intent_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete intent")
async def delete_intent(
    tenant_id: UUID,
    intent_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> None:
    repo = _get_repo(request)
    await repo.delete_intent(intent_id, tenant_id)


# ---------------------------------------------------------------------------
# Examples
# ---------------------------------------------------------------------------


@router.post(
    "/{intent_id}/examples",
    response_model=ExampleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add example",
)
async def add_example(
    tenant_id: UUID,
    intent_id: UUID,
    body: ExampleCreate,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> ExampleResponse:
    repo = _get_repo(request)
    # Verify intent belongs to tenant
    intent = await repo.get_intent(intent_id, tenant_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    embed_svc = await _get_embedding_service(request, tenant_id)
    if embed_svc:
        result = await embed_svc.embed_one(body.text)
        row = await repo.add_example(
            intent_id,
            body.text,
            embedding=result.embedding,
            embedding_model=result.model if result.embedding else None,
        )
    else:
        row = await repo.add_example(intent_id, body.text)

    return ExampleResponse(
        id=row["id"],
        intent_id=row["intent_id"],
        text=row["text"],
        created_at=row["created_at"],
    )


@router.delete(
    "/{intent_id}/examples/{example_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete example",
)
async def delete_example(
    tenant_id: UUID,
    intent_id: UUID,
    example_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> None:
    repo = _get_repo(request)
    intent = await repo.get_intent(intent_id, tenant_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    await repo.delete_example(example_id, intent_id)


@router.get("/{intent_id}/examples", response_model=list[ExampleResponse], summary="List examples")
async def list_examples(
    tenant_id: UUID,
    intent_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> list[ExampleResponse]:
    repo = _get_repo(request)
    # Verify intent belongs to tenant
    intent = await repo.get_intent(intent_id, tenant_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    rows = await repo.list_examples(intent_id)
    return [
        ExampleResponse(
            id=r["id"],
            intent_id=r["intent_id"],
            text=r["text"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post(
    "/reembed",
    response_model=ReembedResponse,
    summary="Re-embed stale examples",
)
async def reembed(
    tenant_id: UUID,
    request: Request,
    _auth: GatewayAuthContext = Depends(require_tenant_access),
) -> ReembedResponse:
    """Backfill embeddings for examples that are missing one or were generated
    by a different model than the tenant's currently configured embedding model.

    Idempotent: safe to call repeatedly. Examples that already have a current
    embedding are skipped.
    """
    embed_svc = await _get_embedding_service(request, tenant_id)
    if embed_svc is None:
        raise HTTPException(
            status_code=400,
            detail="No embedding model configured for this tenant",
        )

    repo = _get_repo(request)
    stale = await repo.list_examples_needing_reembedding(tenant_id, embed_svc.model)
    if not stale:
        return ReembedResponse(refreshed=0, failed=0, model=embed_svc.model)

    embedded = await embed_svc.embed_many([r["text"] for r in stale])
    refreshed = 0
    failed = 0
    for row, ex in zip(stale, embedded, strict=True):
        if ex.embedding is None:
            failed += 1
            continue
        await repo.update_example_embedding(row["id"], ex.embedding, ex.model)
        refreshed += 1

    return ReembedResponse(refreshed=refreshed, failed=failed, model=embed_svc.model)
