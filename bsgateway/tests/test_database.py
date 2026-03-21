from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bsgateway.core.database as db_module
from bsgateway.core.database import close_pool, execute_schema, get_pool


@pytest.fixture(autouse=True)
def reset_pool():
    """Reset the module-level _pool before and after each test."""
    db_module._pool = None
    yield
    db_module._pool = None


def _make_pool_mock(*, is_closing: bool = False) -> MagicMock:
    """Create a MagicMock that behaves like an asyncpg.Pool.

    Uses MagicMock as the base so that synchronous methods like
    ``is_closing()`` return plain values (not coroutines).  The
    ``close()`` method is explicitly set to an AsyncMock so it can
    be awaited.
    """
    pool = MagicMock()
    pool.is_closing.return_value = is_closing
    pool.close = AsyncMock()
    return pool


# -- get_pool -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pool_creates_when_none():
    """get_pool creates a new pool when _pool is None."""
    mock_pool = _make_pool_mock()

    with patch(
        "bsgateway.core.database.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ) as create:
        result = await get_pool("postgresql://localhost/test", min_size=1, max_size=5)

    create.assert_awaited_once_with("postgresql://localhost/test", min_size=1, max_size=5)
    assert result is mock_pool
    assert db_module._pool is mock_pool


@pytest.mark.asyncio
async def test_get_pool_reuses_existing_pool():
    """get_pool returns the existing pool when it is not closing."""
    existing_pool = _make_pool_mock(is_closing=False)
    db_module._pool = existing_pool

    with patch(
        "bsgateway.core.database.asyncpg.create_pool",
        new_callable=AsyncMock,
    ) as create:
        result = await get_pool("postgresql://localhost/test")

    create.assert_not_awaited()
    assert result is existing_pool


@pytest.mark.asyncio
async def test_get_pool_creates_new_when_closing():
    """get_pool creates a new pool when the existing one is closing."""
    closing_pool = _make_pool_mock(is_closing=True)
    db_module._pool = closing_pool

    new_pool = _make_pool_mock()

    with patch(
        "bsgateway.core.database.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=new_pool,
    ) as create:
        result = await get_pool("postgresql://localhost/test", min_size=3, max_size=20)

    create.assert_awaited_once_with("postgresql://localhost/test", min_size=3, max_size=20)
    assert result is new_pool
    assert db_module._pool is new_pool


# -- close_pool ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_pool_closes_and_clears():
    """close_pool closes the pool and sets _pool to None."""
    mock_pool = _make_pool_mock(is_closing=False)
    db_module._pool = mock_pool

    await close_pool()

    mock_pool.close.assert_awaited_once()
    assert db_module._pool is None


@pytest.mark.asyncio
async def test_close_pool_noop_when_none():
    """close_pool does nothing when _pool is None."""
    assert db_module._pool is None
    await close_pool()
    assert db_module._pool is None


@pytest.mark.asyncio
async def test_close_pool_noop_when_already_closing():
    """close_pool does nothing when the pool is already closing."""
    mock_pool = _make_pool_mock(is_closing=True)
    db_module._pool = mock_pool

    await close_pool()

    mock_pool.close.assert_not_awaited()
    # _pool is NOT set to None because the branch is skipped
    assert db_module._pool is mock_pool


# -- execute_schema -----------------------------------------------------------


def _make_execute_schema_mocks() -> tuple[MagicMock, AsyncMock]:
    """Return (pool, conn) mocks suitable for execute_schema tests.

    ``pool.acquire()`` is a sync call that returns an async context
    manager yielding ``conn``.
    """
    conn = AsyncMock()
    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


@pytest.mark.asyncio
async def test_execute_schema_splits_and_executes():
    """execute_schema splits SQL by semicolons and executes non-empty statements."""
    pool, conn = _make_execute_schema_mocks()

    schema_sql = "CREATE TABLE a (id INT); CREATE TABLE b (id INT);  ; "

    await execute_schema(pool, schema_sql)

    assert conn.execute.await_count == 2
    conn.execute.assert_any_await("CREATE TABLE a (id INT)")
    conn.execute.assert_any_await("CREATE TABLE b (id INT)")


@pytest.mark.asyncio
async def test_execute_schema_empty_string():
    """execute_schema does nothing for an empty SQL string."""
    pool, conn = _make_execute_schema_mocks()

    await execute_schema(pool, "")

    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_schema_single_statement():
    """execute_schema handles a single statement without trailing semicolon."""
    pool, conn = _make_execute_schema_mocks()

    await execute_schema(pool, "CREATE TABLE c (id INT)")

    conn.execute.assert_awaited_once_with("CREATE TABLE c (id INT)")
