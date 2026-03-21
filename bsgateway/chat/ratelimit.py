from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: int  # Unix timestamp
    degraded: bool = False  # True when Redis is unavailable (fail-open)


class RateLimiter:
    """Redis-backed per-tenant rate limiter using fixed-window counters."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def check(self, tenant_id: str, rpm: int) -> RateLimitResult:
        """Check if a request is allowed under the rate limit.

        Uses a fixed 60-second window keyed by the current minute.
        """
        now = int(time.time())
        window = now // 60
        key = f"ratelimit:{tenant_id}:{window}"
        reset_at = (window + 1) * 60

        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, 120)  # 2-minute TTL for safety

            remaining = max(0, rpm - count)
            allowed = count <= rpm

            return RateLimitResult(
                allowed=allowed,
                limit=rpm,
                remaining=remaining,
                reset_at=reset_at,
            )
        except Exception:
            # Design decision: fail-open to avoid blocking all requests during
            # Redis outages. Operators MUST alert on this log and restore Redis
            # promptly to re-enable rate limiting.
            logger.critical(
                "rate_limit_redis_unavailable",
                tenant_id=tenant_id,
                detail="rate limiting BYPASSED — Redis unreachable",
                exc_info=True,
            )
            return RateLimitResult(
                allowed=True,
                limit=rpm,
                remaining=rpm,
                reset_at=reset_at,
                degraded=True,
            )
