"""Shared test fixtures and helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from bsvibe_auth import BSVibeUser

from bsgateway.api.deps import AuthIdentity, GatewayAuthContext


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


def make_bsvibe_user(
    tenant_id: UUID | None = None,
    role: str = "member",
    email: str = "test@test.com",
    user_id: str | None = None,
) -> BSVibeUser:
    """Build a fake BSVibeUser for testing."""
    return BSVibeUser(
        id=user_id or str(uuid4()),
        email=email,
        role="authenticated",
        app_metadata={"tenant_id": str(tenant_id or uuid4()), "role": role},
        user_metadata={},
    )


def make_gateway_auth_context(
    tenant_id: UUID | None = None,
    is_admin: bool = False,
    email: str = "test@test.com",
    user_id: str | None = None,
) -> GatewayAuthContext:
    """Build a fake GatewayAuthContext for testing via dependency_overrides."""
    tid = tenant_id or uuid4()
    return GatewayAuthContext(
        identity=AuthIdentity(
            kind="user",
            id=user_id or str(uuid4()),
            email=email,
        ),
        tenant_id=tid,
        is_admin=is_admin,
    )
