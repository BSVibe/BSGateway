"""Tests for bsgateway.tenant.repository — TenantRepository CRUD + caching."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import asyncpg
import pytest

from bsgateway.core.exceptions import DuplicateError
from bsgateway.tenant.repository import TenantRepository
from bsgateway.tests.conftest import MockAcquire, MockTransaction

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_conn() -> AsyncMock:
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=MockTransaction())
    return conn


@pytest.fixture
def mock_pool(mock_conn: AsyncMock) -> MagicMock:
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=MockAcquire(mock_conn))
    return pool


@pytest.fixture
def mock_cache() -> AsyncMock:
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=True)
    cache.delete = AsyncMock(return_value=True)
    return cache


@pytest.fixture
def repo(mock_pool: MagicMock) -> TenantRepository:
    with patch("bsgateway.tenant.repository.sql") as mock_sql:
        mock_sql.schema.return_value = "CREATE TABLE t (id int)"
        mock_sql.query.return_value = "SELECT 1"
        r = TenantRepository(mock_pool)
        r._sql_mock = mock_sql  # stash for assertions
        yield r


@pytest.fixture
def repo_cached(mock_pool: MagicMock, mock_cache: AsyncMock) -> TenantRepository:
    with patch("bsgateway.tenant.repository.sql") as mock_sql:
        mock_sql.schema.return_value = "CREATE TABLE t (id int)"
        mock_sql.query.return_value = "SELECT 1"
        r = TenantRepository(mock_pool, cache=mock_cache)
        r._sql_mock = mock_sql
        yield r


# ---------------------------------------------------------------------------
# Init Schema
# ---------------------------------------------------------------------------


class TestInitSchema:
    async def test_executes_statements_in_transaction(
        self, repo: TenantRepository, mock_conn: AsyncMock
    ):
        with patch("bsgateway.tenant.repository.sql") as mock_sql:
            mock_sql.schema.return_value = "CREATE TABLE a (id int); CREATE TABLE b (id int)"
            await repo.init_schema()
        assert mock_conn.execute.await_count >= 2


# ---------------------------------------------------------------------------
# Tenant CRUD
# ---------------------------------------------------------------------------


class TestTenantCRUD:
    async def test_create_tenant(self, repo: TenantRepository, mock_conn: AsyncMock):
        expected = {"id": uuid4(), "name": "Acme", "slug": "acme"}
        mock_conn.fetchrow.return_value = expected
        result = await repo.create_tenant("Acme", "acme", {"rpm": 100})
        assert result == expected
        mock_conn.fetchrow.assert_awaited_once()

    async def test_create_tenant_duplicate_raises(
        self, repo: TenantRepository, mock_conn: AsyncMock
    ):
        mock_conn.fetchrow.side_effect = asyncpg.UniqueViolationError("")
        with pytest.raises(DuplicateError, match="already exists"):
            await repo.create_tenant("Acme", "acme")

    async def test_get_tenant(self, repo: TenantRepository, mock_conn: AsyncMock):
        tid = uuid4()
        expected = {"id": tid, "name": "Acme"}
        mock_conn.fetchrow.return_value = expected
        result = await repo.get_tenant(tid)
        assert result == expected

    async def test_get_tenant_not_found(self, repo: TenantRepository, mock_conn: AsyncMock):
        mock_conn.fetchrow.return_value = None
        result = await repo.get_tenant(uuid4())
        assert result is None

    async def test_get_tenant_by_slug(self, repo: TenantRepository, mock_conn: AsyncMock):
        expected = {"id": uuid4(), "slug": "acme"}
        mock_conn.fetchrow.return_value = expected
        result = await repo.get_tenant_by_slug("acme")
        assert result == expected

    async def test_list_tenants(self, repo: TenantRepository, mock_conn: AsyncMock):
        rows = [{"id": uuid4()}, {"id": uuid4()}]
        mock_conn.fetch.return_value = rows
        result = await repo.list_tenants(limit=10, offset=0)
        assert result == rows

    async def test_update_tenant(self, repo: TenantRepository, mock_conn: AsyncMock):
        tid = uuid4()
        updated = {"id": tid, "name": "New Name"}
        mock_conn.fetchrow.return_value = updated
        result = await repo.update_tenant(tid, "New Name", "new-name", {})
        assert result == updated

    async def test_deactivate_tenant(self, repo: TenantRepository, mock_conn: AsyncMock):
        tid = uuid4()
        await repo.deactivate_tenant(tid)
        mock_conn.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Model CRUD
# ---------------------------------------------------------------------------


class TestModelCRUD:
    async def test_create_model(self, repo: TenantRepository, mock_conn: AsyncMock):
        expected = {"id": uuid4(), "model_name": "gpt-4o"}
        mock_conn.fetchrow.return_value = expected
        result = await repo.create_model(
            uuid4(), "gpt-4o", "openai", "openai/gpt-4o", "enc_key", None, {}
        )
        assert result == expected

    async def test_create_model_duplicate_raises(
        self, repo: TenantRepository, mock_conn: AsyncMock
    ):
        mock_conn.fetchrow.side_effect = asyncpg.UniqueViolationError("")
        with pytest.raises(DuplicateError, match="already exists"):
            await repo.create_model(uuid4(), "gpt-4o", "openai", "openai/gpt-4o")

    async def test_get_model(self, repo: TenantRepository, mock_conn: AsyncMock):
        expected = {"id": uuid4(), "model_name": "gpt-4o"}
        mock_conn.fetchrow.return_value = expected
        result = await repo.get_model(uuid4(), uuid4())
        assert result == expected

    async def test_get_model_by_name(self, repo: TenantRepository, mock_conn: AsyncMock):
        expected = {"model_name": "gpt-4o"}
        mock_conn.fetchrow.return_value = expected
        result = await repo.get_model_by_name(uuid4(), "gpt-4o")
        assert result == expected

    async def test_list_models(self, repo: TenantRepository, mock_conn: AsyncMock):
        rows = [{"id": uuid4(), "model_name": "gpt-4o"}]
        mock_conn.fetch.return_value = rows
        result = await repo.list_models(uuid4())
        assert len(result) == 1

    async def test_update_model(self, repo: TenantRepository, mock_conn: AsyncMock):
        expected = {"id": uuid4(), "model_name": "updated"}
        mock_conn.fetchrow.return_value = expected
        result = await repo.update_model(
            uuid4(), uuid4(), "updated", "openai", "openai/gpt-4o", None, None, {}
        )
        assert result == expected

    async def test_delete_model(self, repo: TenantRepository, mock_conn: AsyncMock):
        await repo.delete_model(uuid4(), uuid4())
        mock_conn.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Model Caching
# ---------------------------------------------------------------------------


class TestModelCaching:
    async def test_list_models_cache_hit(
        self, repo_cached: TenantRepository, mock_cache: AsyncMock, mock_conn: AsyncMock
    ):
        tid = uuid4()
        cached_data = [{"id": str(uuid4()), "model_name": "cached"}]
        mock_cache.get.return_value = cached_data

        result = await repo_cached.list_models(tid)
        assert len(result) == 1
        assert result[0]["model_name"] == "cached"
        mock_conn.fetch.assert_not_awaited()

    async def test_list_models_cache_miss(
        self, repo_cached: TenantRepository, mock_cache: AsyncMock, mock_conn: AsyncMock
    ):
        tid = uuid4()
        mock_cache.get.return_value = None
        db_rows = [MagicMock()]
        db_rows[0].__iter__ = MagicMock(return_value=iter([("id", uuid4())]))
        # Simulate dict(row)
        db_rows[0].keys = MagicMock(return_value=["id", "model_name"])
        row_data = {"id": "x", "model_name": "gpt"}
        db_rows[0].__getitem__ = MagicMock(side_effect=row_data.__getitem__)
        mock_conn.fetch.return_value = db_rows

        result = await repo_cached.list_models(tid)
        assert len(result) == 1
        mock_cache.set.assert_awaited_once()

    async def test_list_models_empty_not_cached(
        self, repo_cached: TenantRepository, mock_cache: AsyncMock, mock_conn: AsyncMock
    ):
        mock_cache.get.return_value = None
        mock_conn.fetch.return_value = []
        await repo_cached.list_models(uuid4())
        mock_cache.set.assert_not_awaited()

    async def test_create_model_invalidates_cache(
        self, repo_cached: TenantRepository, mock_cache: AsyncMock, mock_conn: AsyncMock
    ):
        tid = uuid4()
        mock_conn.fetchrow.return_value = {"id": uuid4()}
        await repo_cached.create_model(tid, "m", "openai", "openai/gpt-4o")
        mock_cache.delete.assert_awaited_once()

    async def test_update_model_invalidates_cache(
        self, repo_cached: TenantRepository, mock_cache: AsyncMock, mock_conn: AsyncMock
    ):
        tid = uuid4()
        mock_conn.fetchrow.return_value = {"id": uuid4()}
        await repo_cached.update_model(uuid4(), tid, "m", "openai", "openai/gpt-4o", None, None, {})
        mock_cache.delete.assert_awaited_once()

    async def test_delete_model_invalidates_cache(
        self, repo_cached: TenantRepository, mock_cache: AsyncMock, mock_conn: AsyncMock
    ):
        tid = uuid4()
        await repo_cached.delete_model(uuid4(), tid)
        mock_cache.delete.assert_awaited_once()

    async def test_no_cache_always_hits_db(self, repo: TenantRepository, mock_conn: AsyncMock):
        mock_conn.fetch.return_value = []
        await repo.list_models(uuid4())
        mock_conn.fetch.assert_awaited_once()
