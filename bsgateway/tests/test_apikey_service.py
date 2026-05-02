"""Tests for API key service (generation, hashing, validation)."""

from __future__ import annotations

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

    def test_hash_key_is_pbkdf2(self):
        """hash_key produces a salted PBKDF2-SHA256 string, not raw SHA-256."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        raw_key = "bsg_live_" + "a" * 64
        hashed = svc.hash_key(raw_key)
        # Format: pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>
        assert hashed.startswith("pbkdf2_sha256$")
        parts = hashed.split("$")
        assert len(parts) == 4
        assert parts[1].isdigit()
        # Iterations must meet OWASP minimum (>= 600_000 for SHA-256)
        assert int(parts[1]) >= 600_000

    def test_hash_key_is_salted(self):
        """Two hashes of the same key MUST differ (random salt)."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        raw_key = "bsg_live_" + "a" * 64
        h1 = svc.hash_key(raw_key)
        h2 = svc.hash_key(raw_key)
        assert h1 != h2

    def test_verify_key_against_hash(self):
        """verify_key returns True for the original key, False otherwise."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        raw_key = "bsg_live_" + "b" * 64
        stored_hash = svc.hash_key(raw_key)

        assert svc.verify_key(raw_key, stored_hash) is True
        assert svc.verify_key(raw_key + "x", stored_hash) is False
        assert svc.verify_key("totally-different", stored_hash) is False

    def test_verify_legacy_sha256_hash_rejected(self):
        """Legacy SHA-256 hashes are no longer accepted (audit decision #2)."""
        import hashlib

        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        raw_key = "bsg_live_" + "c" * 64
        legacy = hashlib.sha256(raw_key.encode()).hexdigest()
        assert svc.verify_key(raw_key, legacy) is False

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
        """The repository receives a PBKDF2 hash, never the raw key."""
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
        assert stored_hash.startswith("pbkdf2_sha256$")
        assert "bsg_live_" not in stored_hash


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
                "bsgateway.apikey.repository.ApiKeyRepository.list_active_by_prefix",
                new_callable=AsyncMock,
                return_value=[record],
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
            "bsgateway.apikey.repository.ApiKeyRepository.list_active_by_prefix",
            new_callable=AsyncMock,
            return_value=[],
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
            "bsgateway.apikey.repository.ApiKeyRepository.list_active_by_prefix",
            new_callable=AsyncMock,
            return_value=[record],
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
            "bsgateway.apikey.repository.ApiKeyRepository.list_active_by_prefix",
            new_callable=AsyncMock,
            return_value=[record],
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
                "bsgateway.apikey.repository.ApiKeyRepository.list_active_by_prefix",
                new_callable=AsyncMock,
                return_value=[record],
            ),
            patch(
                "bsgateway.apikey.repository.ApiKeyRepository.touch_last_used",
                new_callable=AsyncMock,
            ) as mock_touch,
        ):
            await svc.validate_key(raw_key)

        mock_touch.assert_called_once_with(key_id)

    async def test_validate_prefix_collision_only_matching_returned(self):
        """If two records share a prefix only the verifying one is returned."""
        from bsgateway.apikey.service import ApiKeyService

        pool, _ = make_mock_pool()
        svc = ApiKeyService(pool)
        tid_a = uuid4()
        tid_b = uuid4()
        raw_a = svc.generate_raw_key()
        raw_b = svc.generate_raw_key()
        rec_a = _make_apikey_record(tenant_id=tid_a, key_hash=svc.hash_key(raw_a))
        rec_b = _make_apikey_record(tenant_id=tid_b, key_hash=svc.hash_key(raw_b))

        with (
            patch(
                "bsgateway.apikey.repository.ApiKeyRepository.list_active_by_prefix",
                new_callable=AsyncMock,
                return_value=[rec_a, rec_b],  # both match prefix
            ),
            patch(
                "bsgateway.apikey.repository.ApiKeyRepository.touch_last_used",
                new_callable=AsyncMock,
            ),
        ):
            result = await svc.validate_key(raw_b)

        assert result is not None
        assert result.tenant_id == tid_b


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
