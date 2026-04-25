"""Tests for the rate limiter."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.api.deps import get_auth_context
from bsgateway.chat.ratelimit import RateLimiter, RateLimitResult
from bsgateway.tests.conftest import make_gateway_auth_context, make_mock_pool

ENCRYPTION_KEY_HEX = os.urandom(32).hex()
TENANT_ID = uuid4()


class TestRateLimiter:
    """Unit tests for RateLimiter."""

    async def test_under_limit_allowed(self):
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=1)

        limiter = RateLimiter(redis)
        result = await limiter.check("tenant-1", rpm=60)

        assert result.allowed is True
        assert result.remaining == 59
        assert result.limit == 60

    async def test_at_limit_still_allowed(self):
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=60)

        limiter = RateLimiter(redis)
        result = await limiter.check("tenant-1", rpm=60)

        assert result.allowed is True
        assert result.remaining == 0

    async def test_over_limit_denied(self):
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=61)

        limiter = RateLimiter(redis)
        result = await limiter.check("tenant-1", rpm=60)

        assert result.allowed is False
        assert result.remaining == 0
        assert result.limit == 60

    async def test_first_request_sets_expire(self):
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=1)

        limiter = RateLimiter(redis)
        await limiter.check("tenant-1", rpm=60)

        redis.expire.assert_called_once()

    async def test_subsequent_request_no_extra_expire(self):
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=5)

        limiter = RateLimiter(redis)
        await limiter.check("tenant-1", rpm=60)

        # expire should not be called for count > 1
        redis.expire.assert_not_called()

    async def test_redis_error_fails_closed(self):
        """When Redis is unreachable the limiter MUST fail-closed (deny)."""
        redis = AsyncMock()
        redis.incr = AsyncMock(side_effect=ConnectionError("Redis down"))

        limiter = RateLimiter(redis)
        result = await limiter.check("tenant-1", rpm=60)

        assert result.allowed is False  # Fail-closed
        assert result.degraded is True
        assert result.remaining == 0

    async def test_expire_failure_fails_closed(self):
        """If redis.expire() raises after incr succeeds the result MUST be fail-closed."""
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=1)
        redis.expire = AsyncMock(side_effect=ConnectionError("Redis expire failed"))

        limiter = RateLimiter(redis)
        result = await limiter.check("tenant-1", rpm=60)
        assert result.allowed is False
        assert result.degraded is True
        assert result.remaining == 0

    async def test_redis_timeout_fails_closed(self):
        """asyncio.TimeoutError on Redis call must also deny the request."""
        import asyncio

        redis = AsyncMock()
        redis.incr = AsyncMock(side_effect=TimeoutError("redis ping timed out"))

        limiter = RateLimiter(redis)
        result = await asyncio.wait_for(limiter.check("tenant-1", rpm=10), timeout=2.0)
        assert result.allowed is False
        assert result.degraded is True

    async def test_independent_per_tenant(self):
        redis = AsyncMock()
        captured_keys: list[str] = []

        async def mock_incr(key: str) -> int:
            captured_keys.append(key)
            return 1

        redis.incr = mock_incr

        limiter = RateLimiter(redis)
        await limiter.check("tenant-a", rpm=60)
        await limiter.check("tenant-b", rpm=60)

        assert len(captured_keys) == 2
        assert captured_keys[0] != captured_keys[1]
        assert "tenant-a" in captured_keys[0]
        assert "tenant-b" in captured_keys[1]

    async def test_reset_at_is_future_timestamp(self):
        import time

        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=1)

        limiter = RateLimiter(redis)
        now = int(time.time())
        result = await limiter.check("tenant-1", rpm=60)

        assert result.reset_at > now
        assert result.reset_at <= now + 60


class TestRateLimitAPI:
    """Integration tests for rate limiting in the chat endpoint."""

    @pytest.fixture
    def mock_pool(self):
        pool, _conn = make_mock_pool()
        return pool

    @pytest.fixture
    def app(self, mock_pool: AsyncMock):
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = AsyncMock()  # Redis available
        auth_ctx = make_gateway_auth_context(tenant_id=TENANT_ID, is_admin=False)
        app.dependency_overrides[get_auth_context] = lambda: auth_ctx
        return app

    @pytest.fixture
    def client(self, app) -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    def _patch_tenant(self, settings=None):
        from datetime import UTC, datetime

        return patch(
            "bsgateway.tenant.repository.TenantRepository.get_tenant",
            new_callable=AsyncMock,
            return_value={
                "id": TENANT_ID,
                "name": "Test",
                "slug": "test",
                "is_active": True,
                "settings": settings or "{}",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        )

    def test_rate_limited_returns_429(self, client: TestClient):
        with (
            self._patch_tenant('{"rate_limit": {"requests_per_minute": 5}}'),
            patch(
                "bsgateway.chat.ratelimit.RateLimiter.check",
                new_callable=AsyncMock,
                return_value=RateLimitResult(
                    allowed=False,
                    limit=5,
                    remaining=0,
                    reset_at=9999999999,
                ),
            ),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            )

        assert resp.status_code == 429
        data = resp.json()
        assert data["error"]["code"] == "rate_limit_exceeded"
        assert resp.headers.get("X-RateLimit-Limit") == "5"
        assert resp.headers.get("X-RateLimit-Remaining") == "0"

    def test_no_rate_limit_setting_passes_through(self, client: TestClient):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"id": "chatcmpl-1", "choices": []}

        with (
            self._patch_tenant("{}"),
            patch(
                "bsgateway.chat.service.ChatService.complete",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            )

        assert resp.status_code == 200

    def test_redis_outage_fails_closed_at_api(self, client: TestClient):
        """When Redis raises during rate-limit check the API MUST 429 with
        the fail-closed code, not silently proxy the request."""
        with (
            self._patch_tenant('{"rate_limit": {"requests_per_minute": 5}}'),
            patch(
                "bsgateway.chat.ratelimit.RateLimiter.check",
                new_callable=AsyncMock,
                return_value=RateLimitResult(
                    allowed=False,
                    limit=5,
                    remaining=0,
                    reset_at=9999999999,
                    degraded=True,
                ),
            ),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            )

        assert resp.status_code == 429
        body = resp.json()
        assert body["error"]["code"] == "rate_limit_unavailable"

    def test_no_redis_skips_rate_limit(self, mock_pool):
        """When Redis is not available, rate limiting is skipped."""
        app = create_app()
        app.state.db_pool = mock_pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.redis = None  # No Redis
        auth_ctx = make_gateway_auth_context(tenant_id=TENANT_ID, is_admin=False)
        app.dependency_overrides[get_auth_context] = lambda: auth_ctx

        client = TestClient(app, raise_server_exceptions=False)

        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"id": "chatcmpl-1", "choices": []}

        with patch(
            "bsgateway.chat.service.ChatService.complete",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            )

        assert resp.status_code == 200
