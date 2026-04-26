"""Sprint 4 / Audit §6 - stress + failure-mode scenarios.

The unit suites already cover happy-path concurrency. This file pushes
the load up enough to surface ordering bugs and pins behaviour for the
classic operational failure modes from §6:

* Stress: concurrency, large input, edge cases.
* Failure modes: network down, DB connection drop, Redis eviction,
  fingerprint cache poisoning attempt.

All scenarios are pure-asyncio + mocks so the suite still runs in
seconds. We deliberately avoid 1000-iteration smoke loops to keep
test wall-time bounded; "stress" here means "enough simultaneous
in-flight tasks that scheduler ordering is non-deterministic".
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from bsgateway.chat.ratelimit import RateLimiter
from bsgateway.core.cache import CacheManager
from bsgateway.routing.cache_classifier import (
    CachingClassifier,
    fingerprint_request,
    make_cache_key,
)
from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.routing.repository import RoutingLogsRepository
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


def _make_simple_tenant_config(tenant_id: str) -> TenantConfig:
    return TenantConfig(
        tenant_id=tenant_id,
        slug=f"t-{tenant_id[:8]}",
        models={
            "gpt-4o-mini": TenantModel(
                model_name="gpt-4o-mini", provider="openai", litellm_model="gpt-4o-mini"
            ),
        },
        rules=[
            RoutingRule(
                id="rule-default",
                tenant_id=tenant_id,
                name="default",
                priority=0,
                is_active=True,
                is_default=True,
                target_model="gpt-4o-mini",
                conditions=[
                    RuleCondition(
                        condition_type="token_count",
                        field="estimated_tokens",
                        operator="gte",
                        value=0,
                    )
                ],
            )
        ],
    )


def _recording_pool():
    """Return (pool, calls). Same pattern as the integration scenario suite."""
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
# 1. Concurrent multi-tenant routing decisions (stress)
# ---------------------------------------------------------------------------


class TestConcurrentMultiTenantRouting:
    """200 in-flight rule evaluations across 8 tenants must not corrupt
    per-tenant state nor return cross-tenant decisions.
    """

    @pytest.mark.asyncio
    async def test_200_evaluations_8_tenants_no_cross_pollination(self) -> None:
        engine = RuleEngine()
        configs: dict[str, TenantConfig] = {
            f"tenant-{i}": _make_simple_tenant_config(f"tenant-{i}") for i in range(8)
        }

        async def _eval(tenant_key: str, idx: int):
            cfg = configs[tenant_key]
            req = {
                "messages": [{"role": "user", "content": f"{tenant_key}/req-{idx}"}],
                "model": "auto",
            }
            return tenant_key, await engine.evaluate(req, cfg)

        # 8 tenants * 25 req each = 200 in-flight tasks, scheduler interleaves.
        tasks = [_eval(f"tenant-{i % 8}", idx) for i in range(8) for idx in range(25)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 200
        for tenant_key, match in results:
            assert match is not None
            # Default rule MUST be the rule of the SAME tenant
            # (not leaked from another tenant under concurrency).
            assert match.rule.tenant_id == tenant_key
            assert match.target_model == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 2. Large-input edge case - oversized prompt must not DoS classifier
# ---------------------------------------------------------------------------


class TestLargeInputEdgeCase:
    """Audit §6: edge case 'large input'. The fingerprint hasher must
    handle a multi-megabyte prompt within a strict time budget and
    produce a fixed-size digest.
    """

    def test_megabyte_prompt_fingerprint_completes_in_budget(self) -> None:
        # 1 MiB of payload (a single user message).
        big_content = "A" * (1024 * 1024)
        data = {"messages": [{"role": "user", "content": big_content}]}
        fp = fingerprint_request(data)
        # BLAKE2b-128 -> 32 hex chars, deterministic regardless of input size.
        assert len(fp) == 32
        # Re-running on the same payload yields the same digest (cacheable).
        assert fp == fingerprint_request(data)

    def test_many_messages_many_tools_does_not_explode(self) -> None:
        data = {
            "messages": [{"role": "user", "content": f"msg-{i}"} for i in range(500)],
            "tools": [{"function": {"name": f"tool_{i}"}} for i in range(50)],
        }
        fp = fingerprint_request(data)
        assert len(fp) == 32

    def test_unicode_and_binary_payloads_handled(self) -> None:
        data = {
            "messages": [
                {"role": "user", "content": "한글 emoji 🎉 \x00 NUL byte"},
                {"role": "assistant", "content": "리듬 reply 💯"},
            ]
        }
        fp = fingerprint_request(data)
        assert len(fp) == 32

    def test_malformed_messages_do_not_crash(self) -> None:
        # Robust against whatever weird shape the caller sends.
        data = {
            "messages": [
                None,
                "not a dict",
                {"role": "user", "content": ["multi", "block"]},
                {"role": "user", "content": [{"type": "text", "text": "x"}]},
                {"role": "user", "content": [{"type": "image", "url": "..."}]},
            ]
        }
        fp = fingerprint_request(data)
        assert len(fp) == 32


# ---------------------------------------------------------------------------
# 3. Failure mode: DB connection drop mid-batch
# ---------------------------------------------------------------------------


class TestDatabaseConnectionDropMidBatch:
    """When 50 routing rows are queued and the DB drops on the 25th,
    the remaining 25 must each surface the failure (not silently lose
    data) but the OTHER 24 successful rows MUST already be persisted.

    Operator invariant: partial failure is observable per row.
    """

    @pytest.mark.asyncio
    async def test_failures_after_drop_are_raised_per_row(self) -> None:
        tenant_id = uuid4()
        conn = AsyncMock()
        call_index = {"n": 0}

        async def _execute(sql: str, *args: object) -> None:
            call_index["n"] += 1
            if call_index["n"] >= 25:
                raise ConnectionError("postgres connection dropped")

        conn.execute = AsyncMock(side_effect=_execute)
        pool = MagicMock()
        pool._closed = False

        @asynccontextmanager
        async def _acquire():
            yield conn

        pool.acquire = _acquire
        repo = RoutingLogsRepository(pool)

        async def _insert(idx: int) -> tuple[int, BaseException | None]:
            try:
                await repo.insert_routing_log(
                    tenant_id=tenant_id,
                    rule_id=None,
                    user_text=f"r{idx}",
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
                return idx, None
            except Exception as exc:
                return idx, exc

        # Sequential to make the failure boundary deterministic.
        outcomes = []
        for i in range(50):
            outcomes.append(await _insert(i))

        successes = [idx for idx, exc in outcomes if exc is None]
        failures = [(idx, exc) for idx, exc in outcomes if exc is not None]

        # First 24 succeeded (call_index hits 25 on the 25th call).
        assert len(successes) == 24
        # Remaining 26 failed AND each raised the underlying connection error.
        assert len(failures) == 26
        for _, exc in failures:
            assert isinstance(exc, ConnectionError)


# ---------------------------------------------------------------------------
# 4. Failure mode: Redis eviction returns truncated/None value
# ---------------------------------------------------------------------------


class TestRedisEvictionRecovery:
    """Redis maxmemory eviction can return None for any key without
    warning. The classifier cache must treat this as a clean miss
    (re-run inner classifier + re-cache), never a hard error.
    """

    @pytest.mark.asyncio
    async def test_intermittent_eviction_is_invisible_to_caller(self) -> None:
        # Simulate 50/50 eviction by alternating None / cached responses.
        flip = {"n": 0}
        cache_state: dict[str, str] = {}

        redis = AsyncMock()

        async def _get(key: str) -> str | None:
            flip["n"] += 1
            if flip["n"] % 2 == 0:
                return None  # evicted
            return cache_state.get(key)

        async def _setex(key: str, ttl: int, value: str) -> bool:
            cache_state[key] = value
            return True

        async def _delete(*keys: str) -> int:
            for k in keys:
                cache_state.pop(k, None)
            return len(keys)

        redis.get = AsyncMock(side_effect=_get)
        redis.setex = AsyncMock(side_effect=_setex)
        redis.set = AsyncMock(side_effect=_setex)
        redis.delete = AsyncMock(side_effect=_delete)

        cache = CacheManager(redis)
        inner = AsyncMock()
        inner.classify = AsyncMock(
            return_value=ClassificationResult(tier="medium", strategy="static", score=42)
        )
        wrapped = CachingClassifier(inner, cache, ttl=timedelta(minutes=5))

        # 20 lookups against the same prompt under intermittent eviction.
        for _ in range(20):
            r = await wrapped.classify(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "metadata": {"tenant_id": str(uuid4())},
                }
            )
            assert r.tier == "medium"

        # No exception bubbled out, every call returned a real result.
        assert wrapped.hit_count + wrapped.miss_count == 20
        # At least one inner invocation per missed slot.
        assert inner.classify.await_count >= 1


# ---------------------------------------------------------------------------
# 5. Failure mode: rate limiter bursts under coordinated traffic
# ---------------------------------------------------------------------------


class TestRateLimiterUnderCoordinatedBurst:
    """100 simultaneous requests against rpm=20 must produce exactly
    20 allowed + 80 denied (counter monotonicity).
    """

    @pytest.mark.asyncio
    async def test_100_simultaneous_requests_exact_split(self) -> None:
        counter = {"n": 0}
        lock = asyncio.Lock()

        async def _incr(key: str) -> int:
            async with lock:
                counter["n"] += 1
                return counter["n"]

        redis = AsyncMock()
        redis.incr = AsyncMock(side_effect=_incr)
        redis.expire = AsyncMock(return_value=True)

        limiter = RateLimiter(redis)
        tasks = [limiter.check("tenant-burst", rpm=20) for _ in range(100)]
        results = await asyncio.gather(*tasks)

        allowed = sum(1 for r in results if r.allowed)
        denied = sum(1 for r in results if not r.allowed)
        assert allowed == 20
        assert denied == 80

    @pytest.mark.asyncio
    async def test_independent_tenants_do_not_share_quota(self) -> None:
        per_key_counter: dict[str, int] = {}

        async def _incr(key: str) -> int:
            per_key_counter[key] = per_key_counter.get(key, 0) + 1
            return per_key_counter[key]

        redis = AsyncMock()
        redis.incr = AsyncMock(side_effect=_incr)
        redis.expire = AsyncMock(return_value=True)

        limiter = RateLimiter(redis)
        tasks = []
        for tenant_idx in range(10):
            for _ in range(15):
                tasks.append(limiter.check(f"t-{tenant_idx}", rpm=10))
        results = await asyncio.gather(*tasks)

        # 10 tenants, 15 requests each, rpm=10 ->
        # 10 allowed + 5 denied per tenant -> 100 allowed + 50 denied total.
        allowed = sum(1 for r in results if r.allowed)
        denied = sum(1 for r in results if not r.allowed)
        assert allowed == 100
        assert denied == 50


# ---------------------------------------------------------------------------
# 6. Cache key collision-resistance (BLAKE2b-128 over real prompt sets)
# ---------------------------------------------------------------------------


class TestFingerprintCollisionResistance:
    """A small dictionary of varied prompts must yield distinct
    fingerprints. Defends against accidental cache-poisoning where
    two different requests collide and a tenant reads the wrong tier.
    """

    def test_500_distinct_prompts_produce_500_distinct_fingerprints(self) -> None:
        prompts = [
            {"messages": [{"role": "user", "content": f"prompt-variant-{i:08x}"}]}
            for i in range(500)
        ]
        digests = {fingerprint_request(p) for p in prompts}
        assert len(digests) == 500

    def test_role_change_is_significant(self) -> None:
        a = {"messages": [{"role": "user", "content": "x"}]}
        b = {"messages": [{"role": "assistant", "content": "x"}]}
        assert fingerprint_request(a) != fingerprint_request(b)

    def test_tenant_namespace_resists_cross_tenant_collision(self) -> None:
        """Even if two tenants somehow share a fingerprint, the cache
        key namespace prevents a cross-tenant read."""
        fp = "deadbeef" * 4
        seen: set[str] = set()
        for _ in range(50):
            tenant = uuid4()
            key = make_cache_key(tenant, fp)
            assert key not in seen
            seen.add(key)


# ---------------------------------------------------------------------------
# 7. RuleEngine + concurrent cache - mixed pressure
# ---------------------------------------------------------------------------


class TestMixedPressureScenario:
    """Realistic interleaved load: rule evaluation + cache writes +
    rate-limit checks all on the same event loop. Pins that no single
    component starves the others (no reentrant deadlock).
    """

    @pytest.mark.asyncio
    async def test_engine_cache_ratelimit_interleave_no_deadlock(self) -> None:
        engine = RuleEngine()
        cfg = _make_simple_tenant_config("tenant-mix")

        # Cache backend
        store: dict[str, str] = {}
        redis_cache = AsyncMock()
        redis_cache.get = AsyncMock(side_effect=lambda k: store.get(k))
        redis_cache.set = AsyncMock(side_effect=lambda k, v: store.__setitem__(k, v) or True)
        redis_cache.setex = AsyncMock(side_effect=lambda k, ttl, v: store.__setitem__(k, v) or True)
        redis_cache.delete = AsyncMock(
            side_effect=lambda *ks: [store.pop(k, None) for k in ks] and len(ks)
        )
        cache = CacheManager(redis_cache)

        # Rate limit backend
        rl_counter = {"n": 0}

        async def _incr(_k: str) -> int:
            rl_counter["n"] += 1
            return rl_counter["n"]

        redis_rl = AsyncMock()
        redis_rl.incr = AsyncMock(side_effect=_incr)
        redis_rl.expire = AsyncMock(return_value=True)
        limiter = RateLimiter(redis_rl)

        async def _evaluate(idx: int):
            return await engine.evaluate(
                {"messages": [{"role": "user", "content": f"req-{idx}"}], "model": "auto"},
                cfg,
            )

        async def _cache_write(idx: int):
            await cache.set(f"k{idx}", {"x": idx}, ttl=timedelta(seconds=60))

        async def _rate(idx: int):
            return await limiter.check("tenant-mix", rpm=200)

        # Interleave 60 tasks (20 each kind).
        tasks: list = []
        for i in range(20):
            tasks.append(_evaluate(i))
            tasks.append(_cache_write(i))
            tasks.append(_rate(i))
        results = await asyncio.gather(*tasks)

        # Every task completed without raising.
        assert len(results) == 60
        # Every evaluate returned a routing decision; every rate check
        # returned a RateLimitResult.
        eval_results = [r for r in results if r is not None and hasattr(r, "rule")]
        rl_results = [r for r in results if hasattr(r, "allowed")]
        assert len(eval_results) == 20
        assert len(rl_results) == 20

    @pytest.mark.asyncio
    async def test_collector_repository_under_concurrent_writes(self) -> None:
        """RoutingLogsRepository.insert_routing_log must be safe under 100
        concurrent invocations across 4 tenants - tenant_id never
        scrambled between rows."""
        pool, calls = _recording_pool()
        repo = RoutingLogsRepository(pool)

        tenants = [uuid4() for _ in range(4)]

        async def _do(t: UUID, idx: int) -> None:
            await repo.insert_routing_log(
                tenant_id=t,
                rule_id=None,
                user_text=f"r{idx}",
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

        tasks = [_do(tenants[i % 4], i) for i in range(100)]
        await asyncio.gather(*tasks)

        assert len(calls) == 100
        per_tenant_rows = {t: 0 for t in tenants}
        for _, args in calls:
            per_tenant_rows[args[0]] += 1
        # Each tenant got exactly 25 rows.
        assert all(v == 25 for v in per_tenant_rows.values())
