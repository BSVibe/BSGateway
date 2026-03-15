from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


class BudgetTracker:
    """Redis-backed budget and usage tracking per tenant."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    def _daily_key(self, tenant_id: str) -> str:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        return f"tenant:{tenant_id}:cost:daily:{date}"

    def _monthly_key(self, tenant_id: str) -> str:
        month = datetime.now(UTC).strftime("%Y-%m")
        return f"tenant:{tenant_id}:cost:monthly:{month}"

    def _hourly_req_key(self, tenant_id: str) -> str:
        hour = datetime.now(UTC).strftime("%Y-%m-%dT%H")
        return f"tenant:{tenant_id}:requests:hourly:{hour}"

    async def record_cost(self, tenant_id: str, cost: float) -> None:
        """Record a cost for daily and monthly tracking."""
        daily_key = self._daily_key(tenant_id)
        monthly_key = self._monthly_key(tenant_id)

        await self._redis.incrbyfloat(daily_key, cost)
        await self._redis.expire(daily_key, 86400 * 2)  # 2 days TTL

        await self._redis.incrbyfloat(monthly_key, cost)
        await self._redis.expire(monthly_key, 86400 * 35)  # ~35 days TTL

    async def get_daily_cost(self, tenant_id: str) -> float:
        val = await self._redis.get(self._daily_key(tenant_id))
        return float(val.decode() if isinstance(val, bytes) else val) if val else 0.0

    async def get_monthly_cost(self, tenant_id: str) -> float:
        val = await self._redis.get(self._monthly_key(tenant_id))
        return float(val.decode() if isinstance(val, bytes) else val) if val else 0.0

    async def increment_request_count(self, tenant_id: str) -> int:
        key = self._hourly_req_key(tenant_id)
        count = await self._redis.incr(key)
        await self._redis.expire(key, 3600 * 2)  # 2 hours TTL
        return count

    async def get_request_count_hourly(self, tenant_id: str) -> int:
        val = await self._redis.get(self._hourly_req_key(tenant_id))
        return int(val.decode() if isinstance(val, bytes) else val) if val else 0
