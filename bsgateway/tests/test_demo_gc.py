"""Tests for the BSGateway demo tenant GC.

Hourly cron deletes demo tenants whose ``last_active_at`` is older than
the configured TTL (default 2h). All tenant_id-scoped rows cascade-delete
via existing FK ``ON DELETE CASCADE``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from bsgateway.demo.gc import demo_gc, find_expired_tenants


@pytest.fixture
def mock_pool() -> tuple[MagicMock, AsyncMock]:
    from bsgateway.tests.conftest import make_mock_pool

    return make_mock_pool()


class TestFindExpiredTenants:
    @pytest.mark.asyncio
    async def test_queries_demo_tenants_older_than_threshold(
        self, mock_pool: tuple[MagicMock, AsyncMock]
    ) -> None:
        pool, conn = mock_pool
        expired_ids = [uuid4(), uuid4()]
        conn.fetch.return_value = [{"id": t} for t in expired_ids]

        result = await find_expired_tenants(pool, ttl_seconds=7200)

        assert result == expired_ids
        # SQL must filter both is_demo AND last_active_at threshold
        sql_called = conn.fetch.await_args.args[0]
        assert "is_demo" in sql_called
        assert "last_active_at" in sql_called

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_expired(
        self, mock_pool: tuple[MagicMock, AsyncMock]
    ) -> None:
        pool, conn = mock_pool
        conn.fetch.return_value = []

        result = await find_expired_tenants(pool, ttl_seconds=7200)

        assert result == []


class TestDemoGC:
    @pytest.mark.asyncio
    async def test_deletes_each_expired_tenant(
        self, mock_pool: tuple[MagicMock, AsyncMock]
    ) -> None:
        pool, conn = mock_pool
        expired_ids = [uuid4(), uuid4(), uuid4()]
        conn.fetch.return_value = [{"id": t} for t in expired_ids]

        deleted_count = await demo_gc(pool, ttl_seconds=7200)

        assert deleted_count == 3
        # DELETE must be issued (FK cascade handles dependent rows)
        delete_calls = [c for c in conn.execute.await_args_list if "DELETE" in c.args[0].upper()]
        assert len(delete_calls) >= 1

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_expired(
        self, mock_pool: tuple[MagicMock, AsyncMock]
    ) -> None:
        pool, conn = mock_pool
        conn.fetch.return_value = []

        deleted_count = await demo_gc(pool, ttl_seconds=7200)

        assert deleted_count == 0

    @pytest.mark.asyncio
    async def test_only_deletes_demo_tenants_never_prod(
        self, mock_pool: tuple[MagicMock, AsyncMock]
    ) -> None:
        # Defense in depth: the find query MUST filter by is_demo=true
        # Even if last_active_at is missing on a prod tenant (NULL),
        # the demo GC must NOT delete it.
        pool, conn = mock_pool
        conn.fetch.return_value = []

        await demo_gc(pool, ttl_seconds=7200)

        sql_called = conn.fetch.await_args.args[0]
        assert "is_demo" in sql_called
        assert "= 'true'" in sql_called or "= true" in sql_called.lower()
