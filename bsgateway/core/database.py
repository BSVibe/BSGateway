from __future__ import annotations

import asyncio

import asyncpg
import structlog

logger = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None
# Guards _pool create/close. asyncpg.create_pool is awaitable and can
# yield to the event loop, so concurrent first-time callers (or a
# parallel create + close) could race and produce multiple pools / leak
# connections (audit issue H14). The lock is bound lazily to whichever
# loop is running so test suites that spin up multiple event loops do
# not trip "lock bound to a different event loop".
_pool_lock: asyncio.Lock | None = None
_pool_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_pool_lock() -> asyncio.Lock:
    """Return an asyncio.Lock bound to the current running loop.

    Creates a fresh lock on first call (or when the running loop has
    changed since the last call). Every coroutine that mutates ``_pool``
    must funnel through this lock.
    """
    global _pool_lock, _pool_lock_loop
    loop = asyncio.get_running_loop()
    if _pool_lock is None or _pool_lock_loop is not loop:
        _pool_lock = asyncio.Lock()
        _pool_lock_loop = loop
    return _pool_lock


async def get_pool(database_url: str, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    """Get or create the shared asyncpg connection pool.

    Reuses a single pool across the application. Call :func:`close_pool`
    during shutdown to release connections.

    Concurrent callers funnel through ``_pool_lock`` so the pool is created
    at most once even when N coroutines hit a cold module simultaneously
    (audit issue H14).

    TODO: register a connection-level jsonb codec (``conn.set_type_codec(
    'jsonb', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')``
    via ``init=`` callback) so asyncpg returns JSONB columns as Python
    dicts/lists directly. Removes per-query Python-side decoding scattered
    across the codebase (see routers/workers.py list_workers).
    """
    global _pool
    # Fast path: pool already healthy. Avoids lock contention on hot path.
    if _pool is not None and not _pool.is_closing():
        return _pool

    async with _get_pool_lock():
        # Re-check inside the lock — another coroutine may have created it
        # while we were waiting.
        if _pool is None or _pool.is_closing():
            _pool = await asyncpg.create_pool(database_url, min_size=min_size, max_size=max_size)
            logger.info("database_pool_created", min_size=min_size, max_size=max_size)
        return _pool


async def close_pool() -> None:
    """Close the shared connection pool.

    Serialised with :func:`get_pool` via ``_pool_lock`` so a shutdown
    cannot race a cold first request and leave an orphaned pool behind.
    """
    global _pool
    async with _get_pool_lock():
        if _pool is not None and not _pool.is_closing():
            await _pool.close()
            _pool = None
            logger.info("database_pool_closed")


async def execute_schema(pool: asyncpg.Pool, schema_sql: str) -> None:
    """Execute a schema SQL string (multiple statements separated by semicolons)."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            for statement in schema_sql.split(";"):
                statement = statement.strip()
                if statement:
                    await conn.execute(statement)
