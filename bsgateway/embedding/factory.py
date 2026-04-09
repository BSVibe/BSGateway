"""Tenant-scoped factory for `EmbeddingService` and `EmbeddingProvider`.

Loads tenant settings from the DB, extracts the embedding configuration, and
constructs a fresh provider/service instance. Returns ``None`` when the tenant
has no embedding model configured — all callers treat this as "feature disabled
for this tenant" and gracefully no-op.
"""

from __future__ import annotations

from uuid import UUID

import structlog

from bsgateway.core.utils import safe_json_loads
from bsgateway.embedding.provider import EmbeddingProvider, build_provider
from bsgateway.embedding.service import EmbeddingService
from bsgateway.embedding.settings import EmbeddingSettings
from bsgateway.tenant.repository import TenantRepository

logger = structlog.get_logger(__name__)


async def load_embedding_settings(
    tenant_repo: TenantRepository,
    tenant_id: UUID,
) -> EmbeddingSettings | None:
    """Load embedding settings for a tenant from the DB.

    Returns None when the tenant doesn't exist, isn't active, has no embedding
    configured, or when the lookup itself fails. The "fail closed" behaviour
    is intentional: a transient DB error here should silently disable
    embeddings for the request rather than crash the chat path.
    """
    try:
        row = await tenant_repo.get_tenant(tenant_id)
    except Exception:
        logger.warning("embedding_settings_lookup_failed", tenant_id=str(tenant_id), exc_info=True)
        return None
    if not row or not row["is_active"]:
        return None
    settings_dict = safe_json_loads(row["settings"])
    return EmbeddingSettings.from_tenant_settings(settings_dict)


async def build_provider_for_tenant(
    tenant_repo: TenantRepository,
    tenant_id: UUID,
) -> EmbeddingProvider | None:
    settings = await load_embedding_settings(tenant_repo, tenant_id)
    return build_provider(settings)


async def build_service_for_tenant(
    tenant_repo: TenantRepository,
    tenant_id: UUID,
) -> EmbeddingService | None:
    provider = await build_provider_for_tenant(tenant_repo, tenant_id)
    if provider is None:
        return None
    return EmbeddingService(provider)
