from __future__ import annotations

import json
from uuid import UUID

import structlog

from bsgateway.core.security import (
    decrypt_value,
    encrypt_value,
    generate_api_key,
    hash_api_key,
)
from bsgateway.tenant.models import (
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    TenantModelCreate,
    TenantModelResponse,
    TenantModelUpdate,
    TenantResponse,
)
from bsgateway.tenant.repository import TenantRepository

logger = structlog.get_logger(__name__)


def _record_to_tenant(row) -> TenantResponse:
    settings = row["settings"]
    if isinstance(settings, str):
        settings = json.loads(settings)
    return TenantResponse(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        is_active=row["is_active"],
        settings=settings,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _record_to_model(row) -> TenantModelResponse:
    extra_params = row["extra_params"]
    if isinstance(extra_params, str):
        extra_params = json.loads(extra_params)
    return TenantModelResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        model_name=row["model_name"],
        provider=row["provider"],
        litellm_model=row["litellm_model"],
        api_base=row["api_base"],
        is_active=row["is_active"],
        extra_params=extra_params,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class TenantService:
    """Business logic layer for tenant management."""

    def __init__(self, repo: TenantRepository, encryption_key: bytes) -> None:
        self._repo = repo
        self._encryption_key = encryption_key

    # -- Tenants --

    async def create_tenant(
        self, name: str, slug: str, settings: dict | None = None,
    ) -> TenantResponse:
        row = await self._repo.create_tenant(name, slug, settings)
        logger.info("tenant_created", tenant_id=str(row["id"]), slug=slug)
        return _record_to_tenant(row)

    async def get_tenant(self, tenant_id: UUID) -> TenantResponse | None:
        row = await self._repo.get_tenant(tenant_id)
        return _record_to_tenant(row) if row else None

    async def list_tenants(self, limit: int = 50, offset: int = 0) -> list[TenantResponse]:
        rows = await self._repo.list_tenants(limit, offset)
        return [_record_to_tenant(r) for r in rows]

    async def update_tenant(
        self, tenant_id: UUID, name: str, slug: str, settings: dict,
    ) -> TenantResponse | None:
        row = await self._repo.update_tenant(tenant_id, name, slug, settings)
        if row:
            logger.info("tenant_updated", tenant_id=str(tenant_id))
        return _record_to_tenant(row) if row else None

    async def deactivate_tenant(self, tenant_id: UUID) -> None:
        await self._repo.deactivate_tenant(tenant_id)
        logger.info("tenant_deactivated", tenant_id=str(tenant_id))

    # -- API Keys --

    async def create_api_key(
        self, tenant_id: UUID, name: str = "", scopes: list[str] | None = None,
    ) -> ApiKeyCreatedResponse:
        plaintext_key, prefix = generate_api_key()
        key_hash = hash_api_key(plaintext_key)
        row = await self._repo.create_api_key(tenant_id, key_hash, prefix, name, scopes)
        logger.info("api_key_created", tenant_id=str(tenant_id), key_prefix=prefix)
        return ApiKeyCreatedResponse(
            id=row["id"],
            tenant_id=row["tenant_id"],
            key=plaintext_key,
            key_prefix=row["key_prefix"],
            name=row["name"],
            scopes=list(row["scopes"]),
            created_at=row["created_at"],
        )

    async def list_api_keys(self, tenant_id: UUID) -> list[ApiKeyResponse]:
        rows = await self._repo.list_api_keys(tenant_id)
        return [
            ApiKeyResponse(
                id=r["id"],
                tenant_id=r["tenant_id"],
                key_prefix=r["key_prefix"],
                name=r["name"],
                scopes=list(r["scopes"]),
                is_active=r["is_active"],
                expires_at=r["expires_at"],
                last_used_at=r["last_used_at"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def revoke_api_key(self, key_id: UUID, tenant_id: UUID) -> None:
        await self._repo.revoke_api_key(key_id, tenant_id)
        logger.info("api_key_revoked", tenant_id=str(tenant_id), key_id=str(key_id))

    # -- Tenant Models --

    async def create_model(
        self, tenant_id: UUID, data: TenantModelCreate,
    ) -> TenantModelResponse:
        encrypted_key = None
        if data.api_key and self._encryption_key:
            encrypted_key = encrypt_value(data.api_key, self._encryption_key)

        row = await self._repo.create_model(
            tenant_id=tenant_id,
            model_name=data.model_name,
            provider=data.provider,
            litellm_model=data.litellm_model,
            api_key_encrypted=encrypted_key,
            api_base=data.api_base,
            extra_params=data.extra_params,
        )
        logger.info("tenant_model_created", tenant_id=str(tenant_id), model=data.model_name)
        return _record_to_model(row)

    async def get_model(self, model_id: UUID, tenant_id: UUID) -> TenantModelResponse | None:
        row = await self._repo.get_model(model_id, tenant_id)
        return _record_to_model(row) if row else None

    async def list_models(self, tenant_id: UUID) -> list[TenantModelResponse]:
        rows = await self._repo.list_models(tenant_id)
        return [_record_to_model(r) for r in rows]

    async def update_model(
        self,
        model_id: UUID,
        tenant_id: UUID,
        data: TenantModelUpdate,
    ) -> TenantModelResponse | None:
        existing = await self._repo.get_model(model_id, tenant_id)
        if not existing:
            return None

        encrypted_key = existing["api_key_encrypted"]
        if data.api_key is not None and self._encryption_key:
            encrypted_key = encrypt_value(data.api_key, self._encryption_key)

        existing_extra = existing["extra_params"]
        if isinstance(existing_extra, str):
            existing_extra = json.loads(existing_extra)

        row = await self._repo.update_model(
            model_id=model_id,
            tenant_id=tenant_id,
            model_name=data.model_name or existing["model_name"],
            provider=data.provider or existing["provider"],
            litellm_model=data.litellm_model or existing["litellm_model"],
            api_key_encrypted=encrypted_key,
            api_base=data.api_base if data.api_base is not None else existing["api_base"],
            extra_params=data.extra_params if data.extra_params is not None else existing_extra,
        )
        logger.info("tenant_model_updated", tenant_id=str(tenant_id), model_id=str(model_id))
        return _record_to_model(row) if row else None

    async def delete_model(self, model_id: UUID, tenant_id: UUID) -> None:
        await self._repo.delete_model(model_id, tenant_id)
        logger.info("tenant_model_deleted", tenant_id=str(tenant_id), model_id=str(model_id))

    async def get_model_api_key(self, model_id: UUID, tenant_id: UUID) -> str | None:
        """Decrypt and return a tenant model's provider API key."""
        row = await self._repo.get_model(model_id, tenant_id)
        if not row or not row["api_key_encrypted"]:
            return None
        if not self._encryption_key:
            return None
        return decrypt_value(row["api_key_encrypted"], self._encryption_key)
