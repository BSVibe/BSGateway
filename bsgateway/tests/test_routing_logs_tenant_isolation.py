"""Cross-tenant isolation regression tests for ``routing_logs``.

These guard against the C2 critical issue from the BSVibe Ecosystem Audit
(`Docs/BSVibe_Ecosystem_Audit.md` §5.1) — every read/write of
``routing_logs`` MUST be scoped by ``tenant_id``. Tests below pin both
the repository contract (mandatory tenant_id parameter) and the actual
SQL string (every statement carries ``tenant_id`` either as a column
or as a ``WHERE tenant_id = $N`` clause).

Pre-fix this module fails because:

1. ``insert_routing_log`` did not include ``tenant_id`` in its column list.
2. ``RoutingCollector.record`` accepted no ``tenant_id`` — the hook
   path silently dropped the requesting tenant, allowing a tenant's
   activity to be co-mingled with other tenants in shared queries.
3. There was no repository layer; raw SQL was scattered across modules.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.routing.collector import RoutingCollector, SqlLoader
from bsgateway.routing.models import RoutingDecision
from bsgateway.routing.repository import RoutingLogsRepository


@pytest.fixture
def mock_pool_with_conn() -> tuple[MagicMock, AsyncMock]:
    pool = MagicMock()
    conn = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    return pool, conn


class TestSqlContractsRequireTenantId:
    """All routing_logs SQL statements MUST mention tenant_id."""

    def test_insert_routing_log_includes_tenant_id_column(self) -> None:
        loader = SqlLoader()
        query = loader.query("insert_routing_log")
        assert "tenant_id" in query.lower(), (
            "insert_routing_log must include tenant_id column "
            "(otherwise rows are written without tenant scoping — see C2)"
        )

    def test_select_queries_filter_by_tenant_id(self) -> None:
        loader = SqlLoader()
        for name in ("usage_total", "usage_by_model", "usage_by_rule"):
            query = loader.query(name).lower()
            assert "tenant_id" in query, f"{name} must filter by tenant_id (cross-tenant leak risk)"
            assert "where" in query and "tenant_id =" in query, (
                f"{name} must have a WHERE tenant_id = $N clause"
            )

    def test_no_legacy_insert_without_tenant_remains(self) -> None:
        """The legacy ``insert_routing_log_with_tenant`` alias must be gone.

        Two parallel insert queries (with/without tenant) is exactly the
        bug. Unify on a single query that always includes tenant_id.
        """
        loader = SqlLoader()
        with pytest.raises(KeyError):
            loader.query("insert_routing_log_with_tenant")


class TestRoutingLogsRepositoryEnforcesTenantId:
    """RoutingLogsRepository methods refuse to run without a tenant_id."""

    @pytest.mark.asyncio
    async def test_insert_requires_tenant_id_first_arg(
        self, mock_pool_with_conn: tuple[MagicMock, AsyncMock]
    ) -> None:
        pool, conn = mock_pool_with_conn
        repo = RoutingLogsRepository(pool)
        tenant_id = uuid4()

        await repo.insert_routing_log(
            tenant_id=tenant_id,
            rule_id=None,
            user_text="hi",
            system_prompt="",
            features={
                "token_count": 1,
                "conversation_turns": 1,
                "code_block_count": 0,
                "code_lines": 0,
                "has_error_trace": False,
                "tool_count": 0,
            },
            tier="medium",
            strategy="static",
            score=50,
            original_model="auto",
            resolved_model="gpt-4o-mini",
            embedding=None,
            nexus_task_type=None,
            nexus_priority=None,
            nexus_complexity_hint=None,
            decision_source="classifier",
        )
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args[0]
        # First positional arg after the SQL must be tenant_id.
        assert call_args[1] == tenant_id

    @pytest.mark.asyncio
    async def test_usage_total_filters_by_tenant_id(
        self, mock_pool_with_conn: tuple[MagicMock, AsyncMock]
    ) -> None:
        pool, conn = mock_pool_with_conn
        conn.fetchrow = AsyncMock(return_value={"total_requests": 0, "total_tokens": 0})
        repo = RoutingLogsRepository(pool)

        tenant_id = uuid4()
        start = datetime.now(UTC) - timedelta(days=1)
        end = datetime.now(UTC)

        await repo.usage_total(tenant_id, start, end)

        call_args = conn.fetchrow.call_args[0]
        assert tenant_id in call_args, "usage_total must pass tenant_id as a query parameter"

    @pytest.mark.asyncio
    async def test_usage_by_model_filters_by_tenant_id(
        self, mock_pool_with_conn: tuple[MagicMock, AsyncMock]
    ) -> None:
        pool, conn = mock_pool_with_conn
        conn.fetch = AsyncMock(return_value=[])
        repo = RoutingLogsRepository(pool)

        tenant_id = uuid4()
        start = datetime.now(UTC) - timedelta(days=1)
        end = datetime.now(UTC)

        await repo.usage_by_model(tenant_id, start, end)

        call_args = conn.fetch.call_args[0]
        assert tenant_id in call_args

    @pytest.mark.asyncio
    async def test_usage_by_rule_filters_by_tenant_id(
        self, mock_pool_with_conn: tuple[MagicMock, AsyncMock]
    ) -> None:
        pool, conn = mock_pool_with_conn
        conn.fetch = AsyncMock(return_value=[])
        repo = RoutingLogsRepository(pool)

        tenant_id = uuid4()
        start = datetime.now(UTC) - timedelta(days=1)
        end = datetime.now(UTC)

        await repo.usage_by_rule(tenant_id, start, end)

        call_args = conn.fetch.call_args[0]
        assert tenant_id in call_args


class TestCrossTenantLeakRegression:
    """End-to-end regression: tenant A's writes never surface for tenant B."""

    @pytest.mark.asyncio
    async def test_tenant_b_query_does_not_see_tenant_a_rows(
        self, mock_pool_with_conn: tuple[MagicMock, AsyncMock]
    ) -> None:
        """The repository receives a tenant_id and forwards it to SQL.

        We can't run real Postgres here, but we can pin that the
        repository never executes a usage query that omits the
        scoping parameter — historically the leak was that the SQL
        itself had no WHERE clause, so nothing the caller did could
        prevent the cross-tenant view.
        """
        pool, conn = mock_pool_with_conn
        conn.fetchrow = AsyncMock(return_value={"total_requests": 7, "total_tokens": 700})
        repo = RoutingLogsRepository(pool)

        tenant_a = uuid4()
        tenant_b = uuid4()
        start = datetime.now(UTC) - timedelta(days=1)
        end = datetime.now(UTC)

        await repo.usage_total(tenant_a, start, end)
        first_call = conn.fetchrow.call_args[0]

        await repo.usage_total(tenant_b, start, end)
        second_call = conn.fetchrow.call_args[0]

        # Both calls must scope by their own tenant — never the other.
        assert tenant_a in first_call and tenant_b not in first_call
        assert tenant_b in second_call and tenant_a not in second_call

        # And the SQL itself must contain the tenant_id WHERE clause.
        for sql_text in (first_call[0], second_call[0]):
            assert "tenant_id" in sql_text.lower()


class TestCollectorRequiresTenantId:
    """RoutingCollector.record refuses to record without a tenant_id."""

    @pytest.fixture
    def sample_data(self) -> dict:
        return {
            "messages": [{"role": "user", "content": "hi"}],
            "system": "",
        }

    @pytest.fixture
    def sample_result(self) -> ClassificationResult:
        return ClassificationResult(tier="medium", strategy="static", score=50)

    @pytest.fixture
    def sample_decision(self) -> RoutingDecision:
        return RoutingDecision(
            method="auto",
            original_model="auto",
            resolved_model="gpt-4o-mini",
            tier="medium",
        )

    @pytest.mark.asyncio
    async def test_record_passes_tenant_id_to_repository(
        self,
        mock_pool_with_conn: tuple[MagicMock, AsyncMock],
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        pool, conn = mock_pool_with_conn
        collector = RoutingCollector(database_url="postgresql://test/test")
        collector._pool = pool
        collector._initialized = True

        tenant_id = uuid4()
        await collector.record(sample_data, sample_result, sample_decision, tenant_id=tenant_id)

        conn.execute.assert_called_once()
        call_args = conn.execute.call_args[0]
        # The tenant_id must be the first parameter after the SQL.
        assert call_args[1] == tenant_id

    @pytest.mark.asyncio
    async def test_record_skips_when_tenant_id_missing(
        self,
        mock_pool_with_conn: tuple[MagicMock, AsyncMock],
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        """Without a tenant_id we MUST NOT write to routing_logs.

        The previous behavior was to silently insert with NULL tenant
        — a row that any tenant's query could later sweep up.
        """
        pool, conn = mock_pool_with_conn
        collector = RoutingCollector(database_url="postgresql://test/test")
        collector._pool = pool
        collector._initialized = True

        await collector.record(sample_data, sample_result, sample_decision, tenant_id=None)
        conn.execute.assert_not_called()
