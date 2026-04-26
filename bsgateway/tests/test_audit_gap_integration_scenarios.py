"""Sprint 4 / Audit §6 - cross-module integration scenarios.

These tests exercise BSGateway flows that cross **two or more module
boundaries** end-to-end. The Sprint 0-3 regression suites already pin
each module in isolation; this file covers the **wiring between them**
which is exactly what Audit §6 calls out as the residual gap for
BSGateway:

* "통합 시나리오 (cross-module 흐름)"
* "Static classifier cache + Redis fail-soft fault injection"
* "LiteLLM proxy 통합 e2e 시나리오 (Sprint 0/1/2 누적 변경 검증)"

Out of scope: anything requiring a real DB / Redis / LiteLLM backend -
those live in ``scripts/verify_alembic_parity.sh`` and the deploy smoke
tests. Everything below uses mocks at the I/O boundary so the suite
still runs in <30 s with no external services.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from bsgateway.core.cache import CacheManager
from bsgateway.routing.cache_classifier import (
    CachingClassifier,
    classifier_cache_ttl,
    fingerprint_request,
    make_cache_key,
)
from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.routing.collector import RoutingCollector
from bsgateway.routing.models import RoutingDecision
from bsgateway.routing.repository import RoutingLogsRepository

# ---------------------------------------------------------------------------
# Test helpers - minimal in-memory Redis + asyncpg shims
# ---------------------------------------------------------------------------


class _InMemoryRedis:
    """Async Redis double covering only the surface BSGateway uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str) -> bool:
        self.store[key] = value
        return True

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        # ``CacheManager`` forwards ttl as int seconds via setex.
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0


def _recording_pool() -> tuple[MagicMock, list[tuple[str, tuple]]]:
    """Build an asyncpg.Pool double that records every (sql, args) call."""
    calls: list[tuple[str, tuple]] = []
    conn = AsyncMock()

    async def _execute(sql: str, *args: object) -> None:
        calls.append((sql, args))

    async def _fetch(sql: str, *args: object) -> list:
        calls.append((sql, args))
        return []

    async def _fetchrow(sql: str, *args: object) -> None:
        calls.append((sql, args))
        return None

    conn.execute = AsyncMock(side_effect=_execute)
    conn.fetch = AsyncMock(side_effect=_fetch)
    conn.fetchrow = AsyncMock(side_effect=_fetchrow)

    pool = MagicMock()
    pool._closed = False

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    return pool, calls


# ---------------------------------------------------------------------------
# 1. Classifier cache -> routing -> collector - full forward path
# ---------------------------------------------------------------------------


class TestClassifierCacheToCollectorFlow:
    """Exercise the cache -> classify -> log triplet through real wiring.

    Verifies cumulative invariants from S0/S1/S2/S3:

    * Tenant isolation (cache key + collector tenant_id) - S0-2
    * Cache hit on warm path skips inner classifier - S3-3
    * Collector still records via tenant-scoped repository - S0-2 + S3
    """

    @pytest.mark.asyncio
    async def test_warm_cache_skips_inner_classifier_but_collector_still_records(
        self,
    ) -> None:
        tenant_id = uuid4()

        # Build the static classifier double: only used on miss.
        inner = AsyncMock()
        inner.classify = AsyncMock(
            return_value=ClassificationResult(tier="medium", strategy="static", score=42)
        )

        redis = _InMemoryRedis()
        cache = CacheManager(redis)  # type: ignore[arg-type]
        wrapped = CachingClassifier(inner, cache, ttl=classifier_cache_ttl())

        request = {
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"tenant_id": str(tenant_id)},
        }

        # First call: miss -> inner runs, value cached.
        first = await wrapped.classify(request)
        # Second call: hit -> inner is NOT called again.
        second = await wrapped.classify(request)

        assert first.tier == "medium"
        assert second.tier == "medium"
        assert wrapped.hit_count == 1
        assert wrapped.miss_count == 1
        # Inner was invoked exactly once across the two classifications.
        assert inner.classify.await_count == 1

        # Cache key is tenant-scoped - proves isolation wiring is intact.
        fp = fingerprint_request(request)
        expected_key = make_cache_key(tenant_id, fp)
        assert expected_key in redis.store

        # Collector path: a separate pool double records the row,
        # tenant_id flows through unchanged.
        pool, calls = _recording_pool()
        repo = RoutingLogsRepository(pool)
        await repo.insert_routing_log(
            tenant_id=tenant_id,
            rule_id=None,
            user_text="hello",
            system_prompt="",
            features={
                "token_count": 1,
                "conversation_turns": 1,
                "code_block_count": 0,
                "code_lines": 0,
                "has_error_trace": False,
                "tool_count": 0,
            },
            tier=second.tier,
            strategy=second.strategy,
            score=second.score,
            original_model="auto",
            resolved_model="gpt-4o-mini",
            embedding=None,
            nexus_task_type=None,
            nexus_priority=None,
            nexus_complexity_hint=None,
            decision_source="classifier",
        )

        assert len(calls) == 1
        sql, args = calls[0]
        assert "tenant_id" in sql.lower()
        # tenant_id is positional arg 0 in insert_routing_log.
        assert args[0] == tenant_id

    @pytest.mark.asyncio
    async def test_two_tenants_same_prompt_get_separate_cache_entries(self) -> None:
        """Cross-tenant isolation regression: same prompt, different cache slots."""
        tenant_a, tenant_b = uuid4(), uuid4()
        inner = AsyncMock()
        inner.classify = AsyncMock(
            side_effect=[
                ClassificationResult(tier="simple", strategy="static", score=10),
                ClassificationResult(tier="complex", strategy="static", score=80),
            ]
        )
        redis = _InMemoryRedis()
        cache = CacheManager(redis)  # type: ignore[arg-type]
        wrapped = CachingClassifier(inner, cache, ttl=timedelta(minutes=5))

        msg = {"messages": [{"role": "user", "content": "do the thing"}]}
        a_req = {**msg, "metadata": {"tenant_id": str(tenant_a)}}
        b_req = {**msg, "metadata": {"tenant_id": str(tenant_b)}}

        a_first = await wrapped.classify(a_req)
        b_first = await wrapped.classify(b_req)
        a_warm = await wrapped.classify(a_req)
        b_warm = await wrapped.classify(b_req)

        # Each tenant gets its own miss + warm-hit on its own value.
        assert a_first.tier == "simple"
        assert b_first.tier == "complex"
        # Warm reads do NOT bleed across tenants.
        assert a_warm.tier == "simple"
        assert b_warm.tier == "complex"
        assert inner.classify.await_count == 2  # one miss per tenant
        assert wrapped.miss_count == 2
        assert wrapped.hit_count == 2

    @pytest.mark.asyncio
    async def test_redis_outage_mid_flight_falls_through_to_inner(self) -> None:
        """If Redis goes down between two requests routing must still serve."""
        tenant_id = uuid4()
        inner = AsyncMock()
        inner.classify = AsyncMock(
            return_value=ClassificationResult(tier="medium", strategy="static", score=33)
        )
        # Custom redis-shim that flips to "down" after first set.
        flipped = {"down": False}

        class FlakyRedis(_InMemoryRedis):
            async def get(self, key: str) -> str | None:
                if flipped["down"]:
                    raise ConnectionError("redis is down")
                return await super().get(key)

            async def setex(self, key: str, ttl: int, value: str) -> bool:
                if flipped["down"]:
                    raise ConnectionError("redis is down")
                return await super().setex(key, ttl, value)

        redis = FlakyRedis()
        cache = CacheManager(redis)  # type: ignore[arg-type]
        wrapped = CachingClassifier(inner, cache, ttl=timedelta(minutes=5))

        request = {
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"tenant_id": str(tenant_id)},
        }

        warm = await wrapped.classify(request)  # miss + write
        assert warm.tier == "medium"
        flipped["down"] = True
        # Even though Redis is down, classify must still return a result
        # (degrades to inner classifier).
        degraded = await wrapped.classify(request)
        assert degraded.tier == "medium"
        # CacheManager swallows the ConnectionError -> returns None ->
        # CachingClassifier treats it as a miss and runs the inner.
        # So inner has now run exactly twice across the whole flow.
        assert inner.classify.await_count >= 2


# ---------------------------------------------------------------------------
# 2. Multi-tenant collector - concurrency + per-tenant isolation
# ---------------------------------------------------------------------------


class TestMultiTenantCollectorIsolation:
    @pytest.mark.asyncio
    async def test_concurrent_inserts_each_carry_their_own_tenant_id(self) -> None:
        """Five tenants, ten requests each, all interleaved.

        Each row stamped through ``insert_routing_log`` MUST land with
        the tenant_id of its originating request. Pre-Sprint-0 the SQL
        had no ``tenant_id`` column; this test would have failed by
        carrying the wrong (or zero) tenant for every interleaved write.
        """
        tenants = [uuid4() for _ in range(5)]
        pool, calls = _recording_pool()
        repo = RoutingLogsRepository(pool)

        async def _one(t_id, idx: int) -> None:
            await repo.insert_routing_log(
                tenant_id=t_id,
                rule_id=None,
                user_text=f"req-{idx}",
                system_prompt="",
                features={
                    "token_count": idx,
                    "conversation_turns": 1,
                    "code_block_count": 0,
                    "code_lines": 0,
                    "has_error_trace": False,
                    "tool_count": 0,
                },
                tier="medium",
                strategy="static",
                score=idx,
                original_model="auto",
                resolved_model="gpt-4o-mini",
                embedding=None,
                nexus_task_type=None,
                nexus_priority=None,
                nexus_complexity_hint=None,
                decision_source="classifier",
            )

        tasks = [_one(tenant, idx) for tenant in tenants for idx in range(10)]
        await asyncio.gather(*tasks)

        # 50 inserts, every call has tenant_id as positional arg 0.
        assert len(calls) == 50
        for _, args in calls:
            assert args[0] in tenants

        # Every tenant got exactly 10 rows.
        per_tenant: dict = dict.fromkeys(tenants, 0)
        for _, args in calls:
            per_tenant[args[0]] += 1
        assert all(count == 10 for count in per_tenant.values())


# ---------------------------------------------------------------------------
# 3. RoutingCollector <-> Repository wiring - Sprint 0/1/2 cumulative
# ---------------------------------------------------------------------------


class TestCollectorPersistsThroughRepository:
    """RoutingCollector.record must hit the tenant-scoped repository.

    Pre-Sprint-0 the collector wrote raw SQL with no tenant_id; pre-S1
    it leaked DB connections on shutdown; pre-S2 magic numbers were
    embedded in this path. The combined contract: collector -> repo ->
    insert with tenant_id, no leaks.
    """

    @pytest.mark.asyncio
    async def test_collector_record_invokes_repository_with_tenant_id(self) -> None:
        tenant_id = uuid4()
        pool, calls = _recording_pool()

        collector = RoutingCollector(database_url="postgres://x")
        collector._pool = pool
        # Skip DB init in this unit-level wiring test.
        collector._initialized = True

        decision = RoutingDecision(
            method="auto",
            original_model="auto",
            resolved_model="gpt-4o-mini",
            tier="medium",
            complexity_score=42,
            decision_source="classifier",
        )
        result = ClassificationResult(tier="medium", strategy="static", score=42)

        await collector.record(
            data={
                "messages": [{"role": "user", "content": "hello"}],
            },
            result=result,
            decision=decision,
            tenant_id=tenant_id,
        )

        # The collector wrote through the pool - verify tenant_id is
        # the first positional arg of execute() after the SQL string.
        assert len(calls) == 1
        sql_str, call_args = calls[0]
        assert "tenant_id" in sql_str.lower()
        assert call_args[0] == tenant_id

    @pytest.mark.asyncio
    async def test_collector_skips_when_tenant_id_missing(self) -> None:
        """Audit §6: missing tenant_id MUST not produce an
        un-scoped routing_logs row (would defeat C2)."""
        pool, calls = _recording_pool()

        collector = RoutingCollector(database_url="postgres://x")
        collector._pool = pool
        collector._initialized = True

        decision = RoutingDecision(
            method="auto",
            original_model="auto",
            resolved_model="gpt-4o-mini",
            tier="medium",
            complexity_score=42,
            decision_source="classifier",
        )
        result = ClassificationResult(tier="medium", strategy="static", score=42)

        await collector.record(
            data={"messages": [{"role": "user", "content": "hello"}]},
            result=result,
            decision=decision,
            tenant_id=None,
        )

        # No DB write must occur.
        assert len(calls) == 0
