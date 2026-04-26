from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
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

# PBKDF2 parameters. OWASP (2023) recommends >= 600_000 iterations for
# PBKDF2-HMAC-SHA256. Keep iterations in the stored hash so they can be
# rotated without breaking existing rows.
_PBKDF2_ALGO = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_SALT_BYTES = 16
_PBKDF2_DKLEN = 32


def _pbkdf2_hash(raw_key: str, salt: bytes, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """Return a self-describing PBKDF2 hash string.

    Format: ``pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>`` where the b64
    encoding is urlsafe and unpadded so the field stays compact.
    """
    derived = hashlib.pbkdf2_hmac(
        "sha256", raw_key.encode("utf-8"), salt, iterations, _PBKDF2_DKLEN
    )
    salt_b64 = base64.urlsafe_b64encode(salt).rstrip(b"=").decode("ascii")
    hash_b64 = base64.urlsafe_b64encode(derived).rstrip(b"=").decode("ascii")
    return f"{_PBKDF2_ALGO}${iterations}${salt_b64}${hash_b64}"


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class ApiKeyService:
    """Business logic for API key generation, hashing, and validation."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._repo = ApiKeyRepository(pool)

    def generate_raw_key(self) -> str:
        """Generate a new raw API key: bsg_live_ + 32 random bytes hex."""
        return API_KEY_PREFIX + os.urandom(32).hex()

    def hash_key(self, raw_key: str) -> str:
        """Salted PBKDF2-HMAC-SHA256 hash of the raw key.

        Replaces the previous fast SHA-256 used for hash-table lookups
        (audit issue H3, Lockin decision #2). Lookup is now done by
        ``key_prefix`` + ``verify_key`` so per-key salts are safe.
        """
        salt = os.urandom(_PBKDF2_SALT_BYTES)
        return _pbkdf2_hash(raw_key, salt)

    @staticmethod
    def verify_key(raw_key: str, stored_hash: str) -> bool:
        """Constant-time verification of ``raw_key`` against ``stored_hash``.

        Only ``pbkdf2_sha256`` hashes are accepted. Legacy unsalted SHA-256
        digests (64 hex chars) are rejected explicitly so old rows that
        survive a botched migration do not authenticate.
        """
        if not stored_hash or "$" not in stored_hash:
            return False
        try:
            algo, iter_str, salt_b64, hash_b64 = stored_hash.split("$", 3)
        except ValueError:
            return False
        if algo != _PBKDF2_ALGO:
            return False
        try:
            iterations = int(iter_str)
        except ValueError:
            return False
        if iterations < 1:
            return False
        try:
            salt = _b64decode(salt_b64)
            expected = _b64decode(hash_b64)
        except (ValueError, base64.binascii.Error):
            return False
        # Reject malformed entries with empty salt/hash bytes BEFORE calling
        # pbkdf2_hmac (which raises ValueError on dklen=0). Empty components
        # cannot represent a real key derivation under any policy.
        if not salt or not expected:
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256", raw_key.encode("utf-8"), salt, iterations, len(expected)
        )
        return hmac.compare_digest(derived, expected)

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
        """Validate a raw API key. Returns None if invalid/expired/revoked.

        With salted PBKDF2 we cannot look up by hash (each verify needs the
        per-row salt). Lookup keys by ``key_prefix`` (already indexed) and
        verify with constant-time comparison. Prefix space is 2^48 so
        practical collisions are negligible, but the loop handles any.
        """
        if not raw_key.startswith(API_KEY_PREFIX):
            return None
        prefix = self.get_prefix(raw_key)
        candidates = await self._repo.list_active_by_prefix(prefix)
        if not candidates:
            return None

        now = datetime.now(UTC)
        for row in candidates:
            if not row["is_active"]:
                continue
            if row["expires_at"] and row["expires_at"] < now:
                continue
            if not self.verify_key(raw_key, row["key_hash"]):
                continue

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

        return None

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
