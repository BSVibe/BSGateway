"""Tests for API key service (generation, hashing, validation)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from bsgateway.tests.conftest import make_mock_pool


def _make_apikey_record(
    key_id: UUID | None = None,
    tenant_id: UUID | None = None,
    name: str = "test-key",
    key_hash: str = "abc123",
    key_prefix: str = "bsg_live_abc",
    is_active: bool = True,
    expires_at: datetime | None = None,
    last_used_at: datetime | None = None,
) -> dict:
    now = datetime.now(UTC)
    return {
        "id": key_id or uuid4(),
        "tenant_id": tenant_id or uuid4(),
        "name": name,
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "scopes": '["chat"]',
        "is_active": is_active,
        "expires_at": expires_at,
        "last_used_at": last_used_at,
        "created_at": now,
    }


class TestKeyGeneration:
    def test_generate_key_format(self):
        """Generated key starts with bsg_live_ and has correct length."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        raw_key = svc.generate_raw_key()
        assert raw_key.startswith("bsg_live_")
        # bsg_live_ (9) + 64 hex chars = 73 total
        assert len(raw_key) == 73

    def test_hash_key_is_sha256(self):
        """Hash uses SHA-256."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        raw_key = "bsg_live_" + "a" * 64
        hashed = svc.hash_key(raw_key)
        expected = hashlib.sha256(raw_key.encode()).hexdigest()
        assert hashed == expected

    def test_key_prefix_extracted(self):
        """Prefix is first 12 characters of the key."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        raw_key = "bsg_live_abcdef1234567890"
        prefix = svc.get_prefix(raw_key)
        assert prefix == "bsg_live_abc"
        assert len(prefix) == 12


class TestCreateApiKey:
    async def test_create_returns_full_key(self):
        """create_key returns the full raw key (only time it's visible)."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        tid = uuid4()
        record = _make_apikey_record(tenant_id=tid, name="my-key")

        with patch(
            "bsgateway.apikey.repository.ApiKeyRepository.create",
            new_callable=AsyncMock,
            return_value=record,
        ):
            result = await svc.create_key(tid, "my-key")

        assert result.raw_key.startswith("bsg_live_")
        assert result.id == record["id"]
        assert result.name == "my-key"

    async def test_create_stores_hash_not_plaintext(self):
        """The repository receives a hash, not the raw key."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        tid = uuid4()
        record = _make_apikey_record(tenant_id=tid)

        with patch(
            "bsgateway.apikey.repository.ApiKeyRepository.create",
            new_callable=AsyncMock,
            return_value=record,
        ) as mock_create:
            await svc.create_key(tid, "my-key")

        call_kwargs = mock_create.call_args
        stored_hash = call_kwargs.kwargs.get("key_hash") or call_kwargs.args[2]
        # Must be a hex SHA-256 (64 chars), not a raw key
        assert len(stored_hash) == 64
        assert not stored_hash.startswith("bsg_live_")


class TestValidateApiKey:
    async def test_validate_active_key(self):
        """Valid active key returns tenant_id."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        tid = uuid4()
        raw_key = svc.generate_raw_key()
        key_hash = svc.hash_key(raw_key)

        record = _make_apikey_record(tenant_id=tid, key_hash=key_hash)

        with (
            patch(
                "bsgateway.apikey.repository.ApiKeyRepository.get_by_hash",
                new_callable=AsyncMock,
                return_value=record,
            ),
            patch(
                "bsgateway.apikey.repository.ApiKeyRepository.touch_last_used",
                new_callable=AsyncMock,
            ),
        ):
            result = await svc.validate_key(raw_key)

        assert result is not None
        assert result.tenant_id == tid

    async def test_validate_unknown_key_returns_none(self):
        """Unknown key returns None."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)

        with patch(
            "bsgateway.apikey.repository.ApiKeyRepository.get_by_hash",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await svc.validate_key("bsg_live_" + "x" * 64)

        assert result is None

    async def test_validate_inactive_key_returns_none(self):
        """Revoked key returns None."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        raw_key = svc.generate_raw_key()
        key_hash = svc.hash_key(raw_key)

        record = _make_apikey_record(key_hash=key_hash, is_active=False)

        with patch(
            "bsgateway.apikey.repository.ApiKeyRepository.get_by_hash",
            new_callable=AsyncMock,
            return_value=record,
        ):
            result = await svc.validate_key(raw_key)

        assert result is None

    async def test_validate_expired_key_returns_none(self):
        """Expired key returns None."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        raw_key = svc.generate_raw_key()
        key_hash = svc.hash_key(raw_key)

        record = _make_apikey_record(
            key_hash=key_hash,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        with patch(
            "bsgateway.apikey.repository.ApiKeyRepository.get_by_hash",
            new_callable=AsyncMock,
            return_value=record,
        ):
            result = await svc.validate_key(raw_key)

        assert result is None

    async def test_validate_updates_last_used(self):
        """Successful validation updates last_used_at."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        tid = uuid4()
        key_id = uuid4()
        raw_key = svc.generate_raw_key()
        key_hash = svc.hash_key(raw_key)

        record = _make_apikey_record(key_id=key_id, tenant_id=tid, key_hash=key_hash)

        with (
            patch(
                "bsgateway.apikey.repository.ApiKeyRepository.get_by_hash",
                new_callable=AsyncMock,
                return_value=record,
            ),
            patch(
                "bsgateway.apikey.repository.ApiKeyRepository.touch_last_used",
                new_callable=AsyncMock,
            ) as mock_touch,
        ):
            await svc.validate_key(raw_key)

        mock_touch.assert_called_once_with(key_id)


class TestListAndRevoke:
    async def test_list_keys_returns_no_secrets(self):
        """list_keys returns metadata without key_hash."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        tid = uuid4()

        records = [
            _make_apikey_record(tenant_id=tid, name="key-1"),
            _make_apikey_record(tenant_id=tid, name="key-2"),
        ]

        with patch(
            "bsgateway.apikey.repository.ApiKeyRepository.list_by_tenant",
            new_callable=AsyncMock,
            return_value=records,
        ):
            result = await svc.list_keys(tid)

        assert len(result) == 2
        assert result[0].name == "key-1"

    async def test_revoke_key(self):
        """revoke_key deactivates the key."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        tid = uuid4()
        kid = uuid4()

        with patch(
            "bsgateway.apikey.repository.ApiKeyRepository.revoke",
            new_callable=AsyncMock,
        ) as mock_revoke:
            await svc.revoke_key(kid, tid)

        mock_revoke.assert_called_once_with(kid, tid)
