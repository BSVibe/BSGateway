"""Tests for the BSGateway demo session module.

Demo backend issues per-visitor JWTs signed with DEMO_JWT_SECRET (separate
from prod auth.bsvibe.dev). Each session creates a fresh tenant_id and
seeds demo data scoped to that tenant.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import jwt
import pytest

from bsgateway.demo.jwt import DemoJWTError, decode_demo_jwt, mint_demo_jwt
from bsgateway.demo.session import DemoSessionService


class TestDemoJWT:
    """The demo JWT carries tenant_id + is_demo + last_active claims."""

    def test_mint_returns_jwt_with_tenant_and_is_demo_claims(self) -> None:
        secret = "a" * 64
        tenant_id = uuid4()

        token = mint_demo_jwt(tenant_id, secret=secret, ttl_seconds=7200)

        decoded = jwt.decode(token, secret, algorithms=["HS256"])
        assert decoded["tenant_id"] == str(tenant_id)
        assert decoded["is_demo"] is True
        assert "exp" in decoded
        assert "iat" in decoded

    def test_mint_exp_respects_ttl(self) -> None:
        secret = "b" * 64
        before = time.time()
        token = mint_demo_jwt(uuid4(), secret=secret, ttl_seconds=60)
        decoded = jwt.decode(token, secret, algorithms=["HS256"])
        # exp must be ~60s after iat (allow 5s test fudge)
        assert before + 55 <= decoded["exp"] <= before + 65

    def test_decode_rejects_wrong_secret(self) -> None:
        token = mint_demo_jwt(uuid4(), secret="c" * 64, ttl_seconds=60)
        with pytest.raises(DemoJWTError):
            decode_demo_jwt(token, secret="d" * 64)

    def test_decode_rejects_expired_token(self) -> None:
        token = mint_demo_jwt(uuid4(), secret="g" * 64, ttl_seconds=-10)
        with pytest.raises(DemoJWTError):
            decode_demo_jwt(token, secret="g" * 64)

    def test_decode_rejects_token_without_is_demo(self) -> None:
        # A prod-style JWT lacking is_demo must NOT be accepted by demo decoder.
        token = jwt.encode(
            {"tenant_id": str(uuid4()), "exp": time.time() + 60},
            "f" * 64,
            algorithm="HS256",
        )
        with pytest.raises(DemoJWTError):
            decode_demo_jwt(token, secret="f" * 64)

    def test_decode_returns_tenant_uuid_and_metadata(self) -> None:
        secret = "f" * 64
        tid = uuid4()
        token = mint_demo_jwt(tid, secret=secret, ttl_seconds=60)
        claims = decode_demo_jwt(token, secret=secret)
        assert claims.tenant_id == tid
        assert claims.is_demo is True


class TestDemoSessionService:
    """The demo session service creates ephemeral tenants and seeds them."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        from bsgateway.tests.conftest import make_mock_pool

        pool, _ = make_mock_pool()
        return pool

    @pytest.fixture
    def service(self, mock_pool: MagicMock) -> DemoSessionService:
        seed_fn = AsyncMock()
        return DemoSessionService(
            pool=mock_pool,
            jwt_secret="e" * 64,
            session_ttl_seconds=7200,
            seed_fn=seed_fn,
        )

    @pytest.mark.asyncio
    async def test_create_session_returns_token_and_tenant_id(
        self,
        service: DemoSessionService,
        mock_pool: MagicMock,
    ) -> None:
        # mock_pool.acquire returns conn; conn.fetchrow returns the inserted tenant
        result = await service.create_session()

        assert result.token  # non-empty JWT string
        assert isinstance(result.tenant_id, UUID)

        # Verify token decodes with the service's secret
        claims = decode_demo_jwt(result.token, secret="e" * 64)
        assert claims.tenant_id == result.tenant_id
        assert claims.is_demo is True

    @pytest.mark.asyncio
    async def test_create_session_invokes_seed_for_new_tenant(
        self,
        service: DemoSessionService,
    ) -> None:
        await service.create_session()
        service._seed_fn.assert_awaited_once()  # type: ignore[attr-defined]
        call_kwargs = service._seed_fn.await_args.kwargs  # type: ignore[attr-defined]
        assert "tenant_id" in call_kwargs
        assert isinstance(call_kwargs["tenant_id"], UUID)

    @pytest.mark.asyncio
    async def test_refresh_session_extends_last_active(
        self,
        service: DemoSessionService,
        mock_pool: MagicMock,
    ) -> None:
        tid = uuid4()
        await service.touch_last_active(tid)
        # Verify the conn was used to UPDATE tenants.last_active_at
        async with mock_pool.acquire() as conn:
            assert conn.execute.await_count >= 1
