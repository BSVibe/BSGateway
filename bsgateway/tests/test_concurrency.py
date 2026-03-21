"""Tests for concurrent access patterns across RuleEngine, CacheManager, and RateLimiter."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from bsgateway.chat.ratelimit import RateLimiter
from bsgateway.core.cache import CacheManager
from bsgateway.rules.engine import RuleEngine
from bsgateway.rules.models import (
    RoutingRule,
    RuleCondition,
    TenantConfig,
    TenantModel,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tenant_config(num_rules: int = 3) -> TenantConfig:
    """Build a TenantConfig with multiple priority-ordered rules."""
    rules: list[RoutingRule] = []
    for i in range(num_rules):
        rules.append(
            RoutingRule(
                id=f"rule-{i}",
                tenant_id="t-1",
                name=f"rule-{i}",
                priority=i,
                is_active=True,
                is_default=(i == num_rules - 1),
                target_model=f"model-{i}",
                conditions=[
                    RuleCondition(
                        condition_type="token_count",
                        field="estimated_tokens",
                        operator="gt" if i < num_rules - 1 else "gte",
                        value=500 * (num_rules - 1 - i),
                    ),
                ],
            )
        )
    return TenantConfig(
        tenant_id="t-1",
        slug="test",
        models={"gpt-4": TenantModel(model_name="gpt-4", provider="openai", litellm_model="gpt-4")},
        rules=rules,
    )


def _make_request(content: str = "Hello, how are you?") -> dict:
    return {
        "messages": [{"role": "user", "content": content}],
        "model": "auto",
    }


# ---------------------------------------------------------------------------
# 1. Concurrent rule evaluation
# ---------------------------------------------------------------------------


class TestConcurrentRuleEvaluation:
    """Verify that RuleEngine handles concurrent evaluations without errors."""

    @pytest.mark.asyncio
    async def test_concurrent_rule_evaluation(self) -> None:
        engine = RuleEngine()
        tenant_config = _make_tenant_config(num_rules=4)

        requests = [_make_request(f"Request number {i} with some text") for i in range(10)]

        tasks = [engine.evaluate(req, tenant_config) for req in requests]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        for result in results:
            # Every request should match at least the default rule
            assert result is not None
            assert result.target_model is not None
            assert result.rule is not None

    @pytest.mark.asyncio
    async def test_concurrent_rule_evaluation_no_shared_state_corruption(self) -> None:
        """Each concurrent evaluation must produce independent trace lists."""
        engine = RuleEngine()
        tenant_config = _make_tenant_config(num_rules=3)

        tasks = [engine.evaluate(_make_request(f"msg-{i}"), tenant_config) for i in range(10)]
        results = await asyncio.gather(*tasks)

        traces = [r.trace for r in results if r is not None]
        # Each trace should be an independent list — mutating one must not affect others
        for trace in traces:
            assert isinstance(trace, list)
        # Verify no two results share the same trace list object
        trace_ids = [id(t) for t in traces]
        assert len(set(trace_ids)) == len(trace_ids), "Traces must not be shared objects"


# ---------------------------------------------------------------------------
# 2. Concurrent cache operations
# ---------------------------------------------------------------------------


class TestConcurrentCacheOperations:
    """Verify CacheManager handles concurrent get/set/delete without corruption."""

    @pytest.mark.asyncio
    async def test_concurrent_cache_set_and_get(self) -> None:
        store: dict[str, str] = {}

        async def mock_set(key: str, value: str) -> None:
            store[key] = value

        async def mock_setex(key: str, ttl: int, value: str) -> None:
            store[key] = value

        async def mock_get(key: str) -> str | None:
            return store.get(key)

        async def mock_delete(*keys: str) -> None:
            for k in keys:
                store.pop(k, None)

        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(side_effect=mock_get)
        redis_mock.set = AsyncMock(side_effect=mock_set)
        redis_mock.setex = AsyncMock(side_effect=mock_setex)
        redis_mock.delete = AsyncMock(side_effect=mock_delete)

        cache = CacheManager(redis_mock)

        # 20 concurrent operations: 10 sets then 10 gets
        set_tasks = [
            cache.set(f"key-{i}", {"data": i}, ttl=timedelta(minutes=5)) for i in range(10)
        ]
        set_results = await asyncio.gather(*set_tasks)
        assert all(r is True for r in set_results)

        # Now read them back concurrently
        get_tasks = [cache.get(f"key-{i}") for i in range(10)]
        get_results = await asyncio.gather(*get_tasks)

        for i, result in enumerate(get_results):
            assert result == {"data": i}

    @pytest.mark.asyncio
    async def test_concurrent_mixed_operations(self) -> None:
        """Run 20 mixed get/set/delete operations concurrently."""
        store: dict[str, str] = {}

        async def mock_set(key: str, value: str) -> None:
            store[key] = value

        async def mock_setex(key: str, ttl: int, value: str) -> None:
            store[key] = value

        async def mock_get(key: str) -> str | None:
            return store.get(key)

        async def mock_delete(*keys: str) -> None:
            for k in keys:
                store.pop(k, None)

        async def mock_exists(key: str) -> int:
            return 1 if key in store else 0

        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(side_effect=mock_get)
        redis_mock.set = AsyncMock(side_effect=mock_set)
        redis_mock.setex = AsyncMock(side_effect=mock_setex)
        redis_mock.delete = AsyncMock(side_effect=mock_delete)
        redis_mock.exists = AsyncMock(side_effect=mock_exists)

        cache = CacheManager(redis_mock)

        # Pre-populate some keys
        for i in range(5):
            store[f"key-{i}"] = json.dumps({"data": i})

        # Build 20 mixed tasks
        tasks = []
        # 5 gets on existing keys
        for i in range(5):
            tasks.append(cache.get(f"key-{i}"))
        # 5 sets on new keys
        for i in range(5, 10):
            tasks.append(cache.set(f"key-{i}", {"data": i}))
        # 5 deletes on existing keys
        for i in range(5):
            tasks.append(cache.delete(f"key-{i}"))
        # 5 exists checks
        for i in range(10):
            if len(tasks) < 20:
                tasks.append(cache.exists(f"key-{i}"))

        results = await asyncio.gather(*tasks)

        assert len(results) == 20
        # No exceptions raised — all operations completed
        # Verify gets returned valid data (first 5 results)
        for i in range(5):
            assert results[i] == {"data": i}


# ---------------------------------------------------------------------------
# 3. Concurrent rate limit checks
# ---------------------------------------------------------------------------


class TestConcurrentRateLimitChecks:
    """Verify RateLimiter counts correctly under concurrent access."""

    @pytest.mark.asyncio
    async def test_concurrent_rate_limit_total_matches_attempts(self) -> None:
        """Total allowed + denied must equal total concurrent attempts."""
        counter = {"value": 0}

        async def mock_incr(key: str) -> int:
            counter["value"] += 1
            return counter["value"]

        redis_mock = AsyncMock()
        redis_mock.incr = AsyncMock(side_effect=mock_incr)
        redis_mock.expire = AsyncMock()

        limiter = RateLimiter(redis_mock)
        rpm = 5
        num_requests = 10

        tasks = [limiter.check("tenant-1", rpm=rpm) for _ in range(num_requests)]
        results = await asyncio.gather(*tasks)

        allowed_count = sum(1 for r in results if r.allowed)
        denied_count = sum(1 for r in results if not r.allowed)

        assert allowed_count + denied_count == num_requests
        assert allowed_count == rpm
        assert denied_count == num_requests - rpm

    @pytest.mark.asyncio
    async def test_concurrent_rate_limit_multiple_tenants(self) -> None:
        """Concurrent checks across different tenants are independent."""
        counters: dict[str, int] = {}

        async def mock_incr(key: str) -> int:
            counters[key] = counters.get(key, 0) + 1
            return counters[key]

        redis_mock = AsyncMock()
        redis_mock.incr = AsyncMock(side_effect=mock_incr)
        redis_mock.expire = AsyncMock()

        limiter = RateLimiter(redis_mock)
        rpm = 3

        # 5 requests each for 4 tenants = 20 concurrent checks
        tasks = []
        for tenant_idx in range(4):
            for _ in range(5):
                tasks.append(limiter.check(f"tenant-{tenant_idx}", rpm=rpm))

        results = await asyncio.gather(*tasks)

        assert len(results) == 20

        # Group results by tenant
        for tenant_idx in range(4):
            tenant_results = results[tenant_idx * 5 : (tenant_idx + 1) * 5]
            allowed = sum(1 for r in tenant_results if r.allowed)
            denied = sum(1 for r in tenant_results if not r.allowed)
            assert allowed + denied == 5
            assert allowed == rpm  # 3 allowed out of 5

    @pytest.mark.asyncio
    async def test_concurrent_rate_limit_redis_failure_fail_open(self) -> None:
        """When Redis fails, all concurrent checks should fail-open."""
        redis_mock = AsyncMock()
        redis_mock.incr = AsyncMock(side_effect=ConnectionError("Redis down"))

        limiter = RateLimiter(redis_mock)

        tasks = [limiter.check("tenant-1", rpm=10) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        for r in results:
            assert r.allowed is True
            assert r.degraded is True
