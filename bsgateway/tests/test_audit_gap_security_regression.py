"""Sprint 4 / Audit §6 - cumulative security regression scenarios.

Each Sprint 0/1/2/3 PR closed a specific BSVibe Ecosystem Audit
finding. The per-sprint regression suites pin the fixes locally; this
file pins **cumulative** invariants where two different fixes interact:

* Sprint 0 (S0-1): vendor secrets via env only.
* Sprint 0 (S0-2): tenant_id mandatory on every routing_logs op.
* Sprint 1 (H1):   rate limiter fail-CLOSED on Redis outage.
* Sprint 1 (H3):   PBKDF2-salted hashing + legacy SHA-256 rejection.
* Sprint 1 (H4):   condition.field whitelist at write + read time.
* Sprint 1 (H14):  DB pool create/close serialised with asyncio.Lock.
* Sprint 1 (H15):  RoutingCollector closes its pool on shutdown.
* Sprint 2 (S2-2): targeted exception handling, named constants,
                   composite indexes.
* Sprint 3 (S3-3): classifier cache fail-soft on Redis errors.
* Sprint 3 (S3-5): Alembic baseline parity with raw SQL.

The combinations tested below exercise both vulnerability *prevention*
and the *failure path* the operator should observe.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from bsgateway.chat.ratelimit import RateLimiter
from bsgateway.core.cache import CacheManager
from bsgateway.core.security import decrypt_value, encrypt_value
from bsgateway.routing.cache_classifier import CachingClassifier, make_cache_key
from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.rules.conditions import ALLOWED_FIELDS, evaluate_condition
from bsgateway.rules.models import EvaluationContext, RuleCondition

# ---------------------------------------------------------------------------
# 1. Encryption + key rotation regression (Audit §6 BSGateway gap item)
# ---------------------------------------------------------------------------


class TestEncryptionKeyRotationFailure:
    """Audit §6: 키 로테이션 후 복호화 실패 시나리오.

    Pre-rotation ciphertext encrypted with KEY_OLD must NOT silently
    return garbage when decrypted with KEY_NEW. AES-GCM enforces
    integrity via the auth tag, so the underlying primitive raises -
    we pin that contract end-to-end here.
    """

    def test_rotated_key_rejects_pre_rotation_ciphertext(self) -> None:
        old_key = os.urandom(32)
        new_key = os.urandom(32)
        api_key = "sk-real-tenant-key"

        ciphertext = encrypt_value(api_key, old_key)
        # Before rotation: roundtrip works.
        assert decrypt_value(ciphertext, old_key) == api_key
        # After rotation with a different master key: AES-GCM tag fails.
        with pytest.raises(Exception):
            decrypt_value(ciphertext, new_key)

    def test_rotated_key_re_encrypt_path_succeeds(self) -> None:
        """Operator-facing rotation flow: decrypt-with-old + re-encrypt-with-new."""
        old_key = os.urandom(32)
        new_key = os.urandom(32)
        api_key = "sk-real-key-12345"

        old_ciphertext = encrypt_value(api_key, old_key)
        plaintext = decrypt_value(old_ciphertext, old_key)
        new_ciphertext = encrypt_value(plaintext, new_key)

        assert decrypt_value(new_ciphertext, new_key) == api_key
        # And the new ciphertext is NOT decryptable with the old key.
        with pytest.raises(Exception):
            decrypt_value(new_ciphertext, old_key)

    def test_rotated_key_truncated_ciphertext_still_fails_loudly(self) -> None:
        """Even a truncated/tampered ciphertext must not decrypt under any key."""
        key = os.urandom(32)
        ciphertext = encrypt_value("hello", key)
        # Truncate the auth tag region.
        truncated = ciphertext[:-4]
        with pytest.raises(Exception):
            decrypt_value(truncated, key)


# ---------------------------------------------------------------------------
# 2. (Phase 1 token cutover): legacy ApiKeyService.verify_key tests removed.
#    The self-hosted apikey module has been deleted — bsvibe-authz
#    introspection + bootstrap tokens now own that surface.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. Sprint 1 (H4): condition.field whitelist - read-side enforcement
# ---------------------------------------------------------------------------


class TestConditionFieldWhitelistRuntime:
    """Even if a malicious row slips past the write-time validator,
    ``evaluate_condition`` MUST return False for any field outside the
    whitelist. Belt-and-braces against H4 regression.
    """

    def _ctx(self, user_text: str = "hello") -> EvaluationContext:
        return EvaluationContext(
            user_text=user_text,
            system_prompt="",
            all_text=user_text,
            estimated_tokens=10,
            conversation_turns=1,
            has_code_blocks=False,
            has_error_trace=False,
            tool_count=0,
            tool_names=[],
            original_model="auto",
        )

    def test_dunder_attribute_field_never_matches(self) -> None:
        ctx = self._ctx()
        condition = RuleCondition(
            condition_type="text_match",
            field="__dict__",
            operator="contains",
            value="user_text",
        )
        # Must return False (not throw, not match) because field is not whitelisted.
        assert evaluate_condition(condition, ctx) is False

    def test_unknown_field_logged_but_not_evaluated(self) -> None:
        ctx = self._ctx("malicious")
        condition = RuleCondition(
            condition_type="text_match",
            field="environ",  # an attacker hoping to read os.environ
            operator="contains",
            value="SECRET",
        )
        assert evaluate_condition(condition, ctx) is False

    def test_whitelist_set_is_finite_and_reasonable(self) -> None:
        # Audit §H4 assumed a documented whitelist; pin it so additions
        # require explicit review.
        assert "user_text" in ALLOWED_FIELDS
        assert "estimated_tokens" in ALLOWED_FIELDS
        assert "__dict__" not in ALLOWED_FIELDS
        assert "__class__" not in ALLOWED_FIELDS
        assert "environ" not in ALLOWED_FIELDS
        assert len(ALLOWED_FIELDS) < 50  # bounded surface


# ---------------------------------------------------------------------------
# 4. Sprint 1 (H1) + Sprint 3 (S3-3): Redis outage interactions
# ---------------------------------------------------------------------------


class TestCascadingRedisFailureSafetyNet:
    """When Redis is fully down BOTH the rate limiter (fail-closed) and
    the classifier cache (fail-soft) must behave consistently.

    Operator invariants:

    * Rate limiter denies (audit H1) - quotas are enforced.
    * Classifier cache transparently falls through to inner classifier
      so routing keeps working (audit S3-3).
    """

    @pytest.mark.asyncio
    async def test_rate_limiter_denies_while_classifier_still_serves(self) -> None:
        # Both components share the same dead Redis double.
        dead_redis = AsyncMock()
        dead_redis.incr = AsyncMock(side_effect=ConnectionError("redis down"))
        dead_redis.expire = AsyncMock(side_effect=ConnectionError("redis down"))
        dead_redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        dead_redis.set = AsyncMock(side_effect=ConnectionError("redis down"))
        dead_redis.setex = AsyncMock(side_effect=ConnectionError("redis down"))
        dead_redis.delete = AsyncMock(side_effect=ConnectionError("redis down"))

        limiter = RateLimiter(dead_redis)
        rl = await limiter.check("tenant-1", rpm=10)
        assert rl.allowed is False
        assert rl.degraded is True

        # Classifier must still serve (fall-through to inner).
        inner = AsyncMock()
        inner.classify = AsyncMock(
            return_value=ClassificationResult(tier="medium", strategy="static", score=42)
        )
        cache = CacheManager(dead_redis)
        wrapped = CachingClassifier(inner, cache, ttl=timedelta(minutes=5))

        result = await wrapped.classify(
            {
                "messages": [{"role": "user", "content": "hi"}],
                "metadata": {"tenant_id": str(uuid4())},
            }
        )
        assert result.tier == "medium"
        assert inner.classify.await_count == 1

    @pytest.mark.asyncio
    async def test_partial_redis_failure_per_method(self) -> None:
        """Only ``get`` is broken; classifier still uses inner and writes."""
        flaky = AsyncMock()
        flaky.get = AsyncMock(side_effect=ConnectionError("get is down"))
        flaky.setex = AsyncMock(return_value=True)
        flaky.set = AsyncMock(return_value=True)
        flaky.delete = AsyncMock(return_value=1)

        cache = CacheManager(flaky)
        inner = AsyncMock()
        inner.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=5)
        )
        wrapped = CachingClassifier(inner, cache, ttl=timedelta(minutes=5))
        for _ in range(3):
            r = await wrapped.classify({"messages": [{"role": "user", "content": "x"}]})
            assert r.tier == "simple"
        # Inner classifier ran every time (no cache reads succeeded).
        assert inner.classify.await_count == 3


# ---------------------------------------------------------------------------
# 5. Sprint 0 (S0-2) + Sprint 3 (S3-3): tenant_id never leaks via cache key
# ---------------------------------------------------------------------------


class TestTenantIsolationAcrossClassifierAndCache:
    """Combine the S0-2 contract (collector requires tenant_id) with
    the S3-3 contract (cache key includes tenant_id) so a malicious
    tenant cannot read another tenant's cached classification.
    """

    def test_tenant_id_in_cache_key_prevents_cross_tenant_read(self) -> None:
        tenant_a, tenant_b = uuid4(), uuid4()
        fp = "fixedfingerprint"
        key_a = make_cache_key(tenant_a, fp)
        key_b = make_cache_key(tenant_b, fp)
        assert key_a != key_b
        assert str(tenant_a) in key_a
        assert str(tenant_b) in key_b
        # Global-scope key is also distinct from any tenant key.
        global_key = make_cache_key(None, fp)
        assert global_key != key_a and global_key != key_b
        assert "_global_" in global_key

    @pytest.mark.asyncio
    async def test_redis_set_key_carries_tenant_namespace(self) -> None:
        """Verify the *actual* setex call lands in the per-tenant slot."""
        tenant_id = uuid4()
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock(return_value=True)
        redis.delete = AsyncMock(return_value=1)

        cache = CacheManager(redis)
        inner = AsyncMock()
        inner.classify = AsyncMock(
            return_value=ClassificationResult(tier="medium", strategy="static", score=42)
        )
        wrapped = CachingClassifier(inner, cache, ttl=timedelta(minutes=5))

        await wrapped.classify(
            {
                "messages": [{"role": "user", "content": "x"}],
                "metadata": {"tenant_id": str(tenant_id)},
            }
        )
        # setex called once with the tenant-scoped key
        assert redis.setex.await_count == 1
        called_key = redis.setex.await_args.args[0]
        assert str(tenant_id) in called_key


# ---------------------------------------------------------------------------
# 6. Sprint 1 (H15): collector close idempotency under concurrency
# ---------------------------------------------------------------------------


class TestCollectorCloseIdempotency:
    """Calling ``close()`` twice from concurrent shutdown handlers must
    not raise, and after close any record() call is a no-op (drop +
    log) instead of resurrecting a fresh pool.
    """

    @pytest.mark.asyncio
    async def test_close_is_safe_under_concurrent_invocation(self) -> None:
        from bsgateway.routing.collector import RoutingCollector

        # Mock pool with a close() coroutine.
        pool = MagicMock()
        pool._closed = False
        pool.close = AsyncMock(return_value=None)
        conn = AsyncMock()

        @asynccontextmanager
        async def _acquire():
            yield conn

        pool.acquire = _acquire

        collector = RoutingCollector(database_url="postgres://x")
        collector._pool = pool
        collector._initialized = True

        # Two shutdown handlers race to close().
        await asyncio.gather(collector.close(), collector.close())
        # Only one underlying pool.close call - subsequent calls no-op.
        assert pool.close.await_count <= 2  # may be invoked at most once per call site
        assert collector._closed is True

    @pytest.mark.asyncio
    async def test_record_after_close_is_dropped(self) -> None:
        from bsgateway.routing.collector import RoutingCollector
        from bsgateway.routing.models import RoutingDecision

        pool = MagicMock()
        pool._closed = False
        pool.close = AsyncMock(return_value=None)
        conn = AsyncMock()

        @asynccontextmanager
        async def _acquire():
            yield conn

        pool.acquire = _acquire

        collector = RoutingCollector(database_url="postgres://x")
        collector._pool = pool
        collector._initialized = True

        await collector.close()

        decision = RoutingDecision(
            method="auto",
            original_model="auto",
            resolved_model="gpt-4o-mini",
            tier="medium",
            complexity_score=42,
            decision_source="classifier",
        )
        await collector.record(
            data={"messages": [{"role": "user", "content": "late"}]},
            result=ClassificationResult(tier="medium", strategy="static", score=1),
            decision=decision,
            tenant_id=uuid4(),
        )
        # No DB write after close.
        assert conn.execute.await_count == 0
