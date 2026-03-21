"""Redis-based caching layer with TTL and cache invalidation strategies."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, TypeVar
from uuid import UUID

import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class _CacheEncoder(json.JSONEncoder):
    """JSON encoder that handles UUID and datetime objects."""

    def default(self, o: Any) -> Any:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


class CacheManager:
    """High-level cache manager with auto-serialization and TTL."""

    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client

    async def get(self, key: str) -> Any | None:
        """Get value from cache. Returns None on cache miss."""
        try:
            value = await self._redis.get(key)
            if value is None:
                return None
            return json.loads(value)
        except json.JSONDecodeError:
            logger.warning("cache_deserialization_failed", key=key, exc_info=True)
            # Purge corrupted entry so next read doesn't hit the same error
            await self.delete(key)
            return None
        except (redis.RedisError, ConnectionError, TimeoutError, OSError):
            logger.warning("cache_get_failed", key=key, exc_info=True)
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: timedelta | None = None,
    ) -> bool:
        """Set value in cache with optional TTL."""
        try:
            serialized = json.dumps(value, cls=_CacheEncoder)
            if ttl:
                await self._redis.setex(key, int(ttl.total_seconds()), serialized)
            else:
                await self._redis.set(key, serialized)
            return True
        except (redis.RedisError, ConnectionError, TimeoutError, OSError):
            logger.warning("cache_set_failed", key=key, exc_info=True)
            return False

    async def delete(self, key: str | list[str]) -> bool:
        """Delete key(s) from cache."""
        try:
            keys = [key] if isinstance(key, str) else key
            if keys:
                await self._redis.delete(*keys)
            return True
        except (redis.RedisError, ConnectionError, TimeoutError, OSError):
            logger.warning("cache_delete_failed", exc_info=True)
            return False

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        try:
            return bool(await self._redis.exists(key))
        except (redis.RedisError, ConnectionError, TimeoutError, OSError):
            return False

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], Any],
        ttl: timedelta | None = None,
    ) -> Any:
        """Get from cache or fetch and cache if missing."""
        # Try cache first
        cached = await self.get(key)
        if cached is not None:
            logger.debug("cache_hit", key=key)
            return cached

        # Cache miss — fetch
        logger.debug("cache_miss", key=key)
        value = await fetcher() if inspect.iscoroutinefunction(fetcher) else fetcher()

        # Store in cache
        await self.set(key, value, ttl)
        return value

    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment integer value (for counters)."""
        try:
            return await self._redis.incrby(key, amount)
        except (redis.RedisError, ConnectionError, TimeoutError, OSError):
            logger.warning("cache_increment_failed", key=key, exc_info=True)
            return 0


# Cache key patterns
def cache_key_rules(tenant_id: str) -> str:
    """Cache key for tenant rules."""
    return f"cache:rules:{tenant_id}"


def cache_key_models(tenant_id: str) -> str:
    """Cache key for tenant models."""
    return f"cache:models:{tenant_id}"


def cache_key_usage(tenant_id: str, period: str) -> str:
    """Cache key for usage statistics."""
    return f"cache:usage:{tenant_id}:{period}"


def cache_key_tenant_config(tenant_id: str) -> str:
    """Cache key for tenant config (rules + models)."""
    return f"cache:tenant_config:{tenant_id}"


# Cache TTLs
CACHE_TTL_RULES = timedelta(minutes=15)
CACHE_TTL_MODELS = timedelta(minutes=15)
CACHE_TTL_USAGE = timedelta(minutes=5)
CACHE_TTL_TENANT_CONFIG = timedelta(minutes=10)
