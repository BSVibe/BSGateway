from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from bsgateway.apikey.models import ApiKeyCreated, ApiKeyInfo, ValidatedKey
from bsgateway.apikey.repository import ApiKeyRepository
from bsgateway.core.utils import safe_json_loads

if TYPE_CHECKING:
    import asyncpg

logger = structlog.get_logger(__name__)

API_KEY_PREFIX = "bsg_live_"
_KEY_PREFIX_LEN = 12  # "bsg_live_abc" — enough for identification


class ApiKeyService:
    """Business logic for API key generation, hashing, and validation."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._repo = ApiKeyRepository(pool)

    def generate_raw_key(self) -> str:
        """Generate a new raw API key: bsg_live_ + 32 random bytes hex."""
        return API_KEY_PREFIX + os.urandom(32).hex()

    def hash_key(self, raw_key: str) -> str:
        """SHA-256 hash of the raw key."""
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def get_prefix(self, raw_key: str) -> str:
        """Extract display prefix from a raw key."""
        return raw_key[:_KEY_PREFIX_LEN]

    async def create_key(
        self,
        tenant_id: UUID,
        name: str,
        scopes: list[str] | None = None,
        expires_in_days: int | None = None,
    ) -> ApiKeyCreated:
        """Generate a new API key and store its hash."""
        raw_key = self.generate_raw_key()
        key_hash = self.hash_key(raw_key)
        key_prefix = self.get_prefix(raw_key)
        scopes = scopes or ["chat"]

        expires_at = None
        if expires_in_days:
            expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)

        row = await self._repo.create(
            tenant_id=tenant_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes=scopes,
            expires_at=expires_at,
        )

        logger.info("api_key_created", tenant_id=str(tenant_id), name=name, prefix=key_prefix)

        return ApiKeyCreated(
            id=row["id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            key_prefix=row["key_prefix"],
            raw_key=raw_key,
            scopes=safe_json_loads(row["scopes"]),
            created_at=row["created_at"],
        )

    async def validate_key(
        self,
        raw_key: str,
        *,
        background_tasks: set[asyncio.Task] | None = None,
    ) -> ValidatedKey | None:
        """Validate a raw API key. Returns None if invalid/expired/revoked."""
        key_hash = self.hash_key(raw_key)
        row = await self._repo.get_by_hash(key_hash)

        if not row:
            return None

        if not row["is_active"]:
            return None

        if row["expires_at"] and row["expires_at"] < datetime.now(UTC):
            return None

        # Fire-and-forget: update last_used_at outside the auth hot path
        task = asyncio.create_task(self._repo.touch_last_used(row["id"]))
        if background_tasks is not None:
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)

        return ValidatedKey(
            key_id=row["id"],
            tenant_id=row["tenant_id"],
            scopes=safe_json_loads(row["scopes"]),
        )

    async def list_keys(self, tenant_id: UUID) -> list[ApiKeyInfo]:
        """List all API keys for a tenant (no secrets)."""
        rows = await self._repo.list_by_tenant(tenant_id)
        return [
            ApiKeyInfo(
                id=r["id"],
                tenant_id=r["tenant_id"],
                name=r["name"],
                key_prefix=r["key_prefix"],
                scopes=safe_json_loads(r["scopes"]),
                is_active=r["is_active"],
                expires_at=r["expires_at"],
                last_used_at=r["last_used_at"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def revoke_key(self, key_id: UUID, tenant_id: UUID) -> None:
        """Revoke (deactivate) an API key."""
        await self._repo.revoke(key_id, tenant_id)
        logger.info("api_key_revoked", tenant_id=str(tenant_id), key_id=str(key_id))
