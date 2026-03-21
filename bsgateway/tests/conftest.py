"""Shared test fixtures and helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


class MockAcquire:
    """Proper async context manager for mocking pool.acquire()."""

    def __init__(self, conn: AsyncMock) -> None:
        self.conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self.conn

    async def __aexit__(self, *args: object) -> None:
        pass


class MockTransaction:
    """Proper async context manager for mocking conn.transaction()."""

    async def __aenter__(self) -> MockTransaction:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


def make_mock_pool() -> tuple[MagicMock, AsyncMock]:
    """Create a properly mocked asyncpg pool that doesn't trigger RuntimeWarnings.

    Returns:
        Tuple of (pool, conn) where pool is MagicMock and conn is AsyncMock.
    """
    pool = MagicMock()
    pool._closed = False
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=MockTransaction())
    pool.acquire.return_value = MockAcquire(conn)
    return pool, conn


def make_api_key_row(
    tenant_id=None,
    scopes=None,
    key_hash: str = "fakehash",
    key_prefix: str = "bsg_test",
    name: str = "test-key",
    is_active: bool = True,
    expires_at=None,
    tenant_is_active: bool = True,
) -> dict:
    """Build a fake API key row dict for testing auth flows."""
    return {
        "id": uuid4(),
        "tenant_id": tenant_id or uuid4(),
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "name": name,
        "scopes": scopes or ["chat"],
        "is_active": is_active,
        "expires_at": expires_at,
        "last_used_at": None,
        "created_at": datetime.now(UTC),
        "tenant_is_active": tenant_is_active,
    }
