"""Tests for the development seed data module."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bsgateway.core.seed import DEV_TENANT_SLUG, seed_dev_data
from bsgateway.tests.conftest import MockAcquire, MockTransaction

# Also patch generate_api_key for deterministic tests
_FAKE_KEY = "bsg_test-seed-key-abc12345"
_FAKE_PREFIX = "bsg_test-se"

ENCRYPTION_KEY = bytes.fromhex(os.urandom(32).hex())


class TestSeedDevData:
    """Tests for seed_dev_data()."""

    def _make_pool(self, conn: AsyncMock) -> AsyncMock:
        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=MockAcquire(conn))
        conn.transaction = MagicMock(return_value=MockTransaction())
        return pool

    @pytest.mark.asyncio
    @patch("bsgateway.core.seed.TenantRepository")
    async def test_skips_if_tenant_exists(self, mock_repo_cls):
        repo = AsyncMock()
        repo.get_tenant_by_slug = AsyncMock(return_value={"id": "existing"})
        mock_repo_cls.return_value = repo

        pool = AsyncMock()
        await seed_dev_data(pool, ENCRYPTION_KEY)

        repo.get_tenant_by_slug.assert_awaited_once_with(DEV_TENANT_SLUG)
        pool.acquire.assert_not_called()

    @pytest.mark.asyncio
    @patch("bsgateway.core.seed.generate_api_key", return_value=(_FAKE_KEY, _FAKE_PREFIX))
    @patch("bsgateway.core.seed.encrypt_value", return_value="encrypted")
    @patch("bsgateway.core.seed.hash_api_key", return_value="hashed")
    @patch("bsgateway.core.seed.TenantRepository")
    async def test_creates_tenant_and_models(
        self, mock_repo_cls, mock_hash, mock_encrypt, _mock_genkey
    ):
        repo = AsyncMock()
        repo.get_tenant_by_slug = AsyncMock(return_value=None)
        mock_repo_cls.return_value = repo

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": "new-tenant-id"})
        conn.execute = AsyncMock()
        pool = self._make_pool(conn)

        await seed_dev_data(pool, ENCRYPTION_KEY)

        # Tenant created
        assert conn.fetchrow.await_count == 1
        # API key + 3 models + 1 rule = 5 executions
        assert conn.execute.await_count == 5

    @pytest.mark.asyncio
    @patch("bsgateway.core.seed.generate_api_key", return_value=(_FAKE_KEY, _FAKE_PREFIX))
    @patch("bsgateway.core.seed.encrypt_value", return_value="encrypted")
    @patch("bsgateway.core.seed.hash_api_key", return_value="hashed")
    @patch("bsgateway.core.seed.TenantRepository")
    async def test_skips_encryption_if_no_key(
        self, mock_repo_cls, mock_hash, mock_encrypt, _mock_genkey
    ):
        repo = AsyncMock()
        repo.get_tenant_by_slug = AsyncMock(return_value=None)
        mock_repo_cls.return_value = repo

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": "new-tenant-id"})
        conn.execute = AsyncMock()
        pool = self._make_pool(conn)

        await seed_dev_data(pool, b"")

        mock_encrypt.assert_not_called()

    @pytest.mark.asyncio
    @patch("bsgateway.core.seed.generate_api_key", return_value=(_FAKE_KEY, _FAKE_PREFIX))
    @patch("bsgateway.core.seed.encrypt_value", return_value="encrypted")
    @patch("bsgateway.core.seed.hash_api_key", return_value="hashed")
    @patch("bsgateway.core.seed.TenantRepository")
    async def test_logs_prefix_only_no_full_key(
        self, mock_repo_cls, mock_hash, mock_encrypt, _mock_genkey
    ):
        """Full API key must NOT appear in structured logs; only prefix is logged."""
        repo = AsyncMock()
        repo.get_tenant_by_slug = AsyncMock(return_value=None)
        mock_repo_cls.return_value = repo

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": "new-tenant-id"})
        conn.execute = AsyncMock()
        pool = self._make_pool(conn)

        with patch("bsgateway.core.seed.logger") as mock_logger:
            await seed_dev_data(pool, ENCRYPTION_KEY)

            # Full API key must NOT appear in any log kwargs
            for call in mock_logger.info.call_args_list:
                for v in call.kwargs.values():
                    assert v != _FAKE_KEY, "Full API key must not be logged"

            # Prefix logged via structlog info
            info_kwargs = mock_logger.info.call_args_list[-1].kwargs
            assert info_kwargs["api_key_prefix"] == _FAKE_PREFIX
