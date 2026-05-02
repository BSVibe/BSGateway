"""Tests for CachingClassifier — Redis-backed wrapper around any ClassifierProtocol.

Sprint 3 / S3-3: caches static classifier results in Redis with tenant-scoped
keys, environment-configurable TTL, graceful degradation when Redis is down,
and structured hit/miss metrics.
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from bsgateway.routing.cache_classifier import (
    CACHE_KEY_PREFIX,
    DEFAULT_CACHE_TTL_SECONDS,
    CachingClassifier,
    classifier_cache_ttl,
    fingerprint_request,
    make_cache_key,
)
from bsgateway.routing.classifiers.base import ClassificationResult


@pytest.fixture
def inner_classifier() -> AsyncMock:
    inner = AsyncMock()
    inner.classify = AsyncMock(
        return_value=ClassificationResult(tier="medium", strategy="static", score=42)
    )
    return inner


@pytest.fixture
def cache_manager() -> MagicMock:
    """Mock CacheManager — async get/set/delete."""
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=True)
    cache.delete = AsyncMock(return_value=True)
    return cache


# ---------------------------------------------------------------------------
# fingerprint_request — stable, content-only hash of the prompt + tools
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_same_prompt_same_hash(self) -> None:
        data = {"messages": [{"role": "user", "content": "hello"}]}
        assert fingerprint_request(data) == fingerprint_request(data)

    def test_different_prompt_different_hash(self) -> None:
        a = {"messages": [{"role": "user", "content": "hello"}]}
        b = {"messages": [{"role": "user", "content": "world"}]}
        assert fingerprint_request(a) != fingerprint_request(b)

    def test_ignores_unrelated_metadata(self) -> None:
        a = {"messages": [{"role": "user", "content": "x"}], "metadata": {"trace": "abc"}}
        b = {"messages": [{"role": "user", "content": "x"}], "metadata": {"trace": "def"}}
        assert fingerprint_request(a) == fingerprint_request(b)

    def test_includes_system_prompt(self) -> None:
        a = {"system": "you are helpful", "messages": [{"role": "user", "content": "x"}]}
        b = {"system": "you are sarcastic", "messages": [{"role": "user", "content": "x"}]}
        assert fingerprint_request(a) != fingerprint_request(b)

    def test_includes_tool_names(self) -> None:
        a = {
            "messages": [{"role": "user", "content": "x"}],
            "tools": [{"function": {"name": "search"}}],
        }
        b = {
            "messages": [{"role": "user", "content": "x"}],
            "tools": [{"function": {"name": "calc"}}],
        }
        assert fingerprint_request(a) != fingerprint_request(b)

    def test_returns_hex_string(self) -> None:
        result = fingerprint_request({"messages": []})
        assert isinstance(result, str)
        assert len(result) >= 16
        int(result, 16)  # hex parses

    def test_role_changes_hash(self) -> None:
        a = {"messages": [{"role": "user", "content": "x"}]}
        b = {"messages": [{"role": "assistant", "content": "x"}]}
        assert fingerprint_request(a) != fingerprint_request(b)


# ---------------------------------------------------------------------------
# make_cache_key — tenant scoping, prefix consistency
# ---------------------------------------------------------------------------


class TestMakeCacheKey:
    def test_includes_tenant_id(self) -> None:
        tid = uuid4()
        key = make_cache_key(tid, "abc123")
        assert str(tid) in key

    def test_includes_fingerprint(self) -> None:
        key = make_cache_key(uuid4(), "deadbeef")
        assert "deadbeef" in key

    def test_uses_prefix(self) -> None:
        key = make_cache_key(uuid4(), "f")
        assert key.startswith(CACHE_KEY_PREFIX)

    def test_different_tenants_different_keys(self) -> None:
        a = make_cache_key(uuid4(), "f")
        b = make_cache_key(uuid4(), "f")
        assert a != b

    def test_global_key_when_tenant_none(self) -> None:
        """When tenant_id is None we still produce a key but isolated from tenant rows."""
        key = make_cache_key(None, "f")
        assert key.startswith(CACHE_KEY_PREFIX)
        # Must NOT collide with any real UUID-keyed namespace
        any_tid = uuid4()
        assert key != make_cache_key(any_tid, "f")


# ---------------------------------------------------------------------------
# CachingClassifier — hit/miss/eviction/cross-tenant isolation/fail-soft
# ---------------------------------------------------------------------------


class TestCachingClassifierMissAndStore:
    @pytest.mark.asyncio
    async def test_cache_miss_calls_inner_and_stores(
        self, inner_classifier: AsyncMock, cache_manager: MagicMock
    ) -> None:
        ttl = timedelta(minutes=5)
        clf = CachingClassifier(inner_classifier, cache_manager, ttl=ttl)
        tid = uuid4()
        data = {
            "messages": [{"role": "user", "content": "test"}],
            "metadata": {"tenant_id": str(tid)},
        }

        result = await clf.classify(data)

        assert result.tier == "medium"
        assert result.score == 42
        inner_classifier.classify.assert_awaited_once_with(data)
        cache_manager.set.assert_awaited_once()
        # TTL forwarded
        kwargs = cache_manager.set.await_args.kwargs
        args = cache_manager.set.await_args.args
        # set(key, value, ttl=...) — accept either positional or keyword
        ttl_arg = kwargs.get("ttl") if "ttl" in kwargs else (args[2] if len(args) >= 3 else None)
        assert ttl_arg == ttl

    @pytest.mark.asyncio
    async def test_cache_hit_skips_inner(
        self, inner_classifier: AsyncMock, cache_manager: MagicMock
    ) -> None:
        cached = {"tier": "complex", "strategy": "static", "score": 90, "confidence": None}
        cache_manager.get = AsyncMock(return_value=cached)
        clf = CachingClassifier(inner_classifier, cache_manager, ttl=timedelta(minutes=5))
        data = {
            "messages": [{"role": "user", "content": "test"}],
            "metadata": {"tenant_id": str(uuid4())},
        }

        result = await clf.classify(data)

        assert result.tier == "complex"
        assert result.score == 90
        inner_classifier.classify.assert_not_awaited()
        cache_manager.set.assert_not_awaited()


class TestCachingClassifierTenantIsolation:
    @pytest.mark.asyncio
    async def test_different_tenants_use_different_cache_keys(
        self, inner_classifier: AsyncMock, cache_manager: MagicMock
    ) -> None:
        clf = CachingClassifier(inner_classifier, cache_manager, ttl=timedelta(minutes=5))
        prompt = {"messages": [{"role": "user", "content": "same prompt"}]}
        tid_a, tid_b = uuid4(), uuid4()

        await clf.classify({**prompt, "metadata": {"tenant_id": str(tid_a)}})
        await clf.classify({**prompt, "metadata": {"tenant_id": str(tid_b)}})

        # Two distinct cache.get keys
        keys = [c.args[0] for c in cache_manager.get.await_args_list]
        assert len(set(keys)) == 2
        assert str(tid_a) in keys[0] and str(tid_b) in keys[1]

    @pytest.mark.asyncio
    async def test_tenant_a_cache_does_not_leak_to_tenant_b(
        self, inner_classifier: AsyncMock, cache_manager: MagicMock
    ) -> None:
        """Same prompt, different tenants → independent cache lookups; no leak."""
        # Tenant A is cached complex; Tenant B is cached simple. They must not
        # cross-pollinate even though prompt fingerprint is identical.
        tid_a, tid_b = uuid4(), uuid4()

        store: dict[str, dict] = {}

        async def fake_get(key: str):
            return store.get(key)

        async def fake_set(key: str, value: dict, ttl=None):
            store[key] = value
            return True

        cache_manager.get.side_effect = fake_get
        cache_manager.set.side_effect = fake_set

        # Two inner classifiers — one per tenant — to assert no cross-call.
        results_iter = iter(
            [
                ClassificationResult(tier="complex", strategy="static", score=80),
                ClassificationResult(tier="simple", strategy="static", score=10),
            ]
        )

        async def inner_classify(_):
            return next(results_iter)

        inner = AsyncMock()
        inner.classify = AsyncMock(side_effect=inner_classify)

        clf = CachingClassifier(inner, cache_manager, ttl=timedelta(minutes=5))
        prompt = {"messages": [{"role": "user", "content": "same prompt"}]}

        r_a = await clf.classify({**prompt, "metadata": {"tenant_id": str(tid_a)}})
        r_b = await clf.classify({**prompt, "metadata": {"tenant_id": str(tid_b)}})

        assert r_a.tier == "complex"
        assert r_b.tier == "simple"

        # Tenant A second call hits cache, returns A's complex (NOT B's simple)
        r_a2 = await clf.classify({**prompt, "metadata": {"tenant_id": str(tid_a)}})
        assert r_a2.tier == "complex"
        # And inner was only called twice total (once per tenant on first miss)
        assert inner.classify.await_count == 2


class TestCachingClassifierGracefulDegradation:
    @pytest.mark.asyncio
    async def test_redis_get_failure_falls_back_to_inner(self, inner_classifier: AsyncMock) -> None:
        """When CacheManager.get returns None (its fail-soft path), classify still works."""
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)  # CacheManager treats errors as None
        cache.set = AsyncMock(return_value=False)  # set also fails

        clf = CachingClassifier(inner_classifier, cache, ttl=timedelta(minutes=5))
        data = {
            "messages": [{"role": "user", "content": "x"}],
            "metadata": {"tenant_id": str(uuid4())},
        }

        result = await clf.classify(data)
        assert result.tier == "medium"
        inner_classifier.classify.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_cache_manager_acts_as_passthrough(self, inner_classifier: AsyncMock) -> None:
        """CachingClassifier(cache=None) behaves exactly like the inner classifier."""
        clf = CachingClassifier(inner_classifier, None, ttl=timedelta(minutes=5))
        data = {"messages": [{"role": "user", "content": "x"}]}

        result = await clf.classify(data)
        assert result.tier == "medium"
        inner_classifier.classify.assert_awaited_once_with(data)

    @pytest.mark.asyncio
    async def test_cache_set_failure_does_not_break_classification(
        self, inner_classifier: AsyncMock
    ) -> None:
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock(side_effect=ConnectionError("redis down"))

        clf = CachingClassifier(inner_classifier, cache, ttl=timedelta(minutes=5))
        data = {
            "messages": [{"role": "user", "content": "x"}],
            "metadata": {"tenant_id": str(uuid4())},
        }

        # Must not raise
        result = await clf.classify(data)
        assert result.tier == "medium"

    @pytest.mark.asyncio
    async def test_corrupt_cached_value_falls_back_and_does_not_crash(
        self, inner_classifier: AsyncMock
    ) -> None:
        """Cached payload missing required fields → fallback to inner, do not crash."""
        cache = MagicMock()
        cache.get = AsyncMock(return_value={"unexpected": "payload"})
        cache.set = AsyncMock(return_value=True)
        cache.delete = AsyncMock(return_value=True)

        clf = CachingClassifier(inner_classifier, cache, ttl=timedelta(minutes=5))
        data = {
            "messages": [{"role": "user", "content": "x"}],
            "metadata": {"tenant_id": str(uuid4())},
        }
        result = await clf.classify(data)
        assert result.tier == "medium"
        inner_classifier.classify.assert_awaited_once()


class TestCachingClassifierTTL:
    @pytest.mark.asyncio
    async def test_ttl_forwarded_to_cache_set(
        self, inner_classifier: AsyncMock, cache_manager: MagicMock
    ) -> None:
        ttl = timedelta(minutes=12)
        clf = CachingClassifier(inner_classifier, cache_manager, ttl=ttl)
        await clf.classify(
            {
                "messages": [{"role": "user", "content": "x"}],
                "metadata": {"tenant_id": str(uuid4())},
            }
        )
        kwargs = cache_manager.set.await_args.kwargs
        args = cache_manager.set.await_args.args
        ttl_arg = kwargs.get("ttl") if "ttl" in kwargs else args[2]
        assert ttl_arg == ttl


class TestCachingClassifierMetrics:
    @pytest.mark.asyncio
    async def test_emits_hit_metric_event(
        self, inner_classifier: AsyncMock, cache_manager: MagicMock, caplog
    ) -> None:
        cache_manager.get = AsyncMock(
            return_value={"tier": "simple", "strategy": "static", "score": 5, "confidence": None}
        )
        clf = CachingClassifier(inner_classifier, cache_manager, ttl=timedelta(minutes=5))

        result = await clf.classify(
            {
                "messages": [{"role": "user", "content": "x"}],
                "metadata": {"tenant_id": str(uuid4())},
            }
        )

        assert result.tier == "simple"
        # Verify cache hit counter was incremented
        assert clf.hit_count == 1
        assert clf.miss_count == 0

    @pytest.mark.asyncio
    async def test_emits_miss_metric_event(
        self, inner_classifier: AsyncMock, cache_manager: MagicMock
    ) -> None:
        clf = CachingClassifier(inner_classifier, cache_manager, ttl=timedelta(minutes=5))
        await clf.classify(
            {
                "messages": [{"role": "user", "content": "x"}],
                "metadata": {"tenant_id": str(uuid4())},
            }
        )
        assert clf.hit_count == 0
        assert clf.miss_count == 1

    @pytest.mark.asyncio
    async def test_hit_rate_property(
        self, inner_classifier: AsyncMock, cache_manager: MagicMock
    ) -> None:
        # 1 miss, then 2 hits
        cache_manager.get = AsyncMock(
            side_effect=[
                None,
                {"tier": "medium", "strategy": "static", "score": 50, "confidence": None},
                {"tier": "medium", "strategy": "static", "score": 50, "confidence": None},
            ]
        )
        clf = CachingClassifier(inner_classifier, cache_manager, ttl=timedelta(minutes=5))
        for _ in range(3):
            await clf.classify(
                {
                    "messages": [{"role": "user", "content": "x"}],
                    "metadata": {"tenant_id": str(uuid4())},
                }
            )
        assert clf.hit_count == 2
        assert clf.miss_count == 1
        assert pytest.approx(clf.hit_rate, abs=1e-6) == 2 / 3

    def test_hit_rate_zero_when_no_lookups(self) -> None:
        clf = CachingClassifier(AsyncMock(), None, ttl=timedelta(minutes=5))
        assert clf.hit_rate == 0.0


class TestClassifierCacheTTL:
    """``classifier_cache_ttl`` honours CLASSIFIER_CACHE_TTL_SECONDS env var
    and falls back to the documented default for malformed/non-positive values."""

    def test_default_when_env_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("CLASSIFIER_CACHE_TTL_SECONDS", raising=False)
        assert classifier_cache_ttl() == timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS)

    def test_reads_env_var(self, monkeypatch) -> None:
        monkeypatch.setenv("CLASSIFIER_CACHE_TTL_SECONDS", "120")
        assert classifier_cache_ttl() == timedelta(seconds=120)

    def test_invalid_value_falls_back_to_default(self, monkeypatch) -> None:
        monkeypatch.setenv("CLASSIFIER_CACHE_TTL_SECONDS", "not-a-number")
        assert classifier_cache_ttl() == timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS)

    def test_non_positive_value_falls_back_to_default(self, monkeypatch) -> None:
        monkeypatch.setenv("CLASSIFIER_CACHE_TTL_SECONDS", "0")
        assert classifier_cache_ttl() == timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS)

        monkeypatch.setenv("CLASSIFIER_CACHE_TTL_SECONDS", "-30")
        assert classifier_cache_ttl() == timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS)


class TestFactoryCacheWiring:
    """create_classifier(config, cache=...) should wrap the static classifier
    in a CachingClassifier so the production code path actually benefits from
    Redis-backed memoisation. The llm and ml strategies are intentionally not
    wrapped because their outputs are non-deterministic / already cached."""

    def _config(self, strategy: str = "static"):
        from bsgateway.routing.models import (
            ClassifierConfig,
            ClassifierWeights,
            CollectorConfig,
            LLMClassifierConfig,
            RoutingConfig,
            TierConfig,
        )

        return RoutingConfig(
            tiers=[
                TierConfig(name="simple", score_range=(0, 49), model="local-llm"),
                TierConfig(name="medium", score_range=(50, 79), model="gpt-4o-mini"),
                TierConfig(name="complex", score_range=(80, 100), model="claude-opus"),
            ],
            classifier=ClassifierConfig(
                weights=ClassifierWeights(),
                token_thresholds={"low": 500, "medium": 2000, "high": 8000},
                complex_keywords=[],
                simple_keywords=[],
            ),
            classifier_strategy=strategy,
            llm_classifier=LLMClassifierConfig(api_base="x", model="x", timeout=1.0),
            collector=CollectorConfig(enabled=False),
        )

    def test_static_strategy_wrapped_when_cache_present(self) -> None:
        from bsgateway.routing.cache_classifier import CachingClassifier
        from bsgateway.routing.classifiers import create_classifier

        cache = MagicMock()
        clf = create_classifier(self._config("static"), cache=cache)
        assert isinstance(clf, CachingClassifier)

    def test_static_strategy_unwrapped_when_no_cache(self) -> None:
        from bsgateway.routing.cache_classifier import CachingClassifier
        from bsgateway.routing.classifiers import create_classifier
        from bsgateway.routing.classifiers.static import StaticClassifier

        clf = create_classifier(self._config("static"), cache=None)
        assert isinstance(clf, StaticClassifier)
        assert not isinstance(clf, CachingClassifier)

    def test_llm_strategy_not_wrapped(self) -> None:
        """LLM classifier is non-deterministic — wrapping would poison cache."""
        from bsgateway.routing.cache_classifier import CachingClassifier
        from bsgateway.routing.classifiers import create_classifier

        cache = MagicMock()
        clf = create_classifier(self._config("llm"), cache=cache)
        assert not isinstance(clf, CachingClassifier)


class TestRouterAttachCache:
    """BSGatewayRouter.attach_cache wires Redis into the existing static
    classifier at runtime — used by the FastAPI lifespan after Redis is up."""

    def _router(self):
        from bsgateway.routing.hook import BSGatewayRouter
        from bsgateway.routing.models import (
            ClassifierConfig,
            ClassifierWeights,
            CollectorConfig,
            LLMClassifierConfig,
            RoutingConfig,
            TierConfig,
        )

        config = RoutingConfig(
            tiers=[
                TierConfig(name="medium", score_range=(0, 100), model="gpt-4o-mini"),
            ],
            classifier=ClassifierConfig(
                weights=ClassifierWeights(),
                token_thresholds={"low": 500, "medium": 2000, "high": 8000},
                complex_keywords=[],
                simple_keywords=[],
            ),
            classifier_strategy="static",
            llm_classifier=LLMClassifierConfig(api_base="x", model="x", timeout=1.0),
            collector=CollectorConfig(enabled=False),
        )
        return BSGatewayRouter(config=config)

    def test_attach_cache_wraps_static(self) -> None:
        from bsgateway.routing.cache_classifier import CachingClassifier

        router = self._router()
        cache = MagicMock()
        router.attach_cache(cache)
        assert isinstance(router.classifier, CachingClassifier)

    def test_attach_cache_none_is_noop(self) -> None:
        from bsgateway.routing.cache_classifier import CachingClassifier

        router = self._router()
        before = router.classifier
        router.attach_cache(None)
        assert router.classifier is before
        assert not isinstance(router.classifier, CachingClassifier)

    def test_attach_cache_idempotent(self) -> None:
        from bsgateway.routing.cache_classifier import CachingClassifier

        router = self._router()
        cache = MagicMock()
        router.attach_cache(cache)
        wrapped = router.classifier
        # Second attach must not double-wrap
        router.attach_cache(cache)
        assert router.classifier is wrapped
        assert isinstance(router.classifier, CachingClassifier)


class TestCachingClassifierSerialization:
    @pytest.mark.asyncio
    async def test_classification_result_roundtrip_via_cache(
        self, cache_manager: MagicMock
    ) -> None:
        store: dict = {}

        async def fake_get(key):
            return store.get(key)

        async def fake_set(key, value, ttl=None):
            # Validate the value is JSON-serialisable (CacheManager calls json.dumps)
            json.dumps(value)
            store[key] = value
            return True

        cache_manager.get.side_effect = fake_get
        cache_manager.set.side_effect = fake_set

        inner = AsyncMock()
        inner.classify = AsyncMock(
            return_value=ClassificationResult(
                tier="complex", strategy="static", score=88, confidence=None
            )
        )
        clf = CachingClassifier(inner, cache_manager, ttl=timedelta(minutes=5))
        data = {
            "messages": [{"role": "user", "content": "x"}],
            "metadata": {"tenant_id": str(uuid4())},
        }

        first = await clf.classify(data)
        second = await clf.classify(data)
        assert first.tier == second.tier == "complex"
        assert first.score == second.score == 88
        # First call: miss + set + inner; second: hit, no inner
        assert inner.classify.await_count == 1
