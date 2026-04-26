"""Phase 0 P0.7 — BSGateway service token minter for BSupervisor.

BSGateway needs to call BSupervisor's ``POST /api/events`` with a service
JWT (aud=bsupervisor, scope=bsupervisor.events). The minter:

- Reads a long-lived BSVibe-Auth user access token + tenant_id from
  configuration (service account credential pattern).
- Calls ``POST {auth_url}/api/service-tokens/issue`` to mint a short-lived
  service JWT.
- Caches the token until ``exp - safety_margin``; refreshes on demand.
- Is asyncio-safe (single in-flight refresh).

Lockin §3 decision #16, Auth_Design §6.4, Auth-PR3 contract.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bsgateway.supervisor.service_token import (
    ServiceTokenMinter,
    ServiceTokenMinterError,
)


def _good_response(token: str, expires_in: int = 3600) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json = MagicMock(
        return_value={
            "access_token": token,
            "expires_in": expires_in,
            "token_type": "service",
        }
    )
    resp.raise_for_status = MagicMock(return_value=None)
    return resp


def _bad_response(status: int) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    err = httpx.HTTPStatusError(
        f"http {status}",
        request=MagicMock(),
        response=resp,
    )
    resp.raise_for_status = MagicMock(side_effect=err)
    return resp


@pytest.mark.asyncio
class TestServiceTokenMinter:
    async def test_mints_token_via_auth_endpoint(self) -> None:
        minter = ServiceTokenMinter(
            auth_url="https://auth.bsvibe.dev",
            service_account_token="bootstrap-user-jwt",
            service_account_tenant_id="00000000-0000-0000-0000-000000000abc",
            audience="bsupervisor",
            scope=["bsupervisor.events"],
        )

        post = AsyncMock(return_value=_good_response("svc.jwt.v1"))
        with patch("httpx.AsyncClient.post", new=post):
            tok = await minter.get_token()

        assert tok == "svc.jwt.v1"
        post.assert_awaited_once()
        # Verify request shape matches BSVibe-Auth /api/service-tokens/issue.
        call = post.await_args_list[0]
        assert call.kwargs["url"].endswith("/api/service-tokens/issue")
        body = call.kwargs["json"]
        assert body["audience"] == "bsupervisor"
        assert body["scope"] == ["bsupervisor.events"]
        assert body["tenant_id"] == "00000000-0000-0000-0000-000000000abc"
        headers = call.kwargs["headers"]
        assert headers["Authorization"] == "Bearer bootstrap-user-jwt"

    async def test_caches_until_expiry_with_safety_margin(self) -> None:
        minter = ServiceTokenMinter(
            auth_url="https://auth.bsvibe.dev",
            service_account_token="boot",
            service_account_tenant_id="t1",
            audience="bsupervisor",
            scope=["bsupervisor.events"],
            safety_margin_s=60,
        )

        post = AsyncMock(return_value=_good_response("v1", expires_in=3600))
        with patch("httpx.AsyncClient.post", new=post):
            t1 = await minter.get_token()
            t2 = await minter.get_token()

        assert t1 == t2 == "v1"
        post.assert_awaited_once()

    async def test_refreshes_after_expiry(self) -> None:
        minter = ServiceTokenMinter(
            auth_url="https://auth.bsvibe.dev",
            service_account_token="boot",
            service_account_tenant_id="t1",
            audience="bsupervisor",
            scope=["bsupervisor.events"],
            safety_margin_s=60,
        )

        # Manually expire the cached token.
        post = AsyncMock(
            side_effect=[
                _good_response("v1", expires_in=3600),
                _good_response("v2", expires_in=3600),
            ]
        )
        with patch("httpx.AsyncClient.post", new=post):
            t1 = await minter.get_token()
            # Force expiry: jump the clock past exp - safety
            minter._cached_exp = int(time.time()) - 1  # type: ignore[attr-defined]
            t2 = await minter.get_token()

        assert t1 == "v1"
        assert t2 == "v2"
        assert post.await_count == 2

    async def test_concurrent_callers_share_one_mint(self) -> None:
        """Single in-flight refresh — never N concurrent POSTs for one cold-start."""
        minter = ServiceTokenMinter(
            auth_url="https://auth.bsvibe.dev",
            service_account_token="boot",
            service_account_tenant_id="t1",
            audience="bsupervisor",
            scope=["bsupervisor.events"],
        )
        slow_resp = _good_response("v1", expires_in=3600)

        async def _slow_post(*_a, **_kw):
            await asyncio.sleep(0.05)
            return slow_resp

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=_slow_post)) as post:
            results = await asyncio.gather(
                minter.get_token(),
                minter.get_token(),
                minter.get_token(),
            )

        assert results == ["v1", "v1", "v1"]
        # CRITICAL: only one network call.
        assert post.await_count == 1

    async def test_auth_failure_raises_typed_error(self) -> None:
        minter = ServiceTokenMinter(
            auth_url="https://auth.bsvibe.dev",
            service_account_token="boot",
            service_account_tenant_id="t1",
            audience="bsupervisor",
            scope=["bsupervisor.events"],
        )

        post = AsyncMock(return_value=_bad_response(403))
        with patch("httpx.AsyncClient.post", new=post):
            with pytest.raises(ServiceTokenMinterError):
                await minter.get_token()

    async def test_audience_must_be_supported(self) -> None:
        with pytest.raises(ValueError):
            ServiceTokenMinter(
                auth_url="https://auth.bsvibe.dev",
                service_account_token="boot",
                service_account_tenant_id="t1",
                audience="bogus",  # type: ignore[arg-type]
                scope=["bogus.events"],
            )

    async def test_scope_must_match_audience(self) -> None:
        with pytest.raises(ValueError):
            ServiceTokenMinter(
                auth_url="https://auth.bsvibe.dev",
                service_account_token="boot",
                service_account_tenant_id="t1",
                audience="bsupervisor",
                scope=["bsage.read"],  # wrong product prefix
            )

    async def test_invalidate_forces_refresh(self) -> None:
        minter = ServiceTokenMinter(
            auth_url="https://auth.bsvibe.dev",
            service_account_token="boot",
            service_account_tenant_id="t1",
            audience="bsupervisor",
            scope=["bsupervisor.events"],
        )
        post = AsyncMock(
            side_effect=[
                _good_response("v1", expires_in=3600),
                _good_response("v2", expires_in=3600),
            ]
        )
        with patch("httpx.AsyncClient.post", new=post):
            t1 = await minter.get_token()
            minter.invalidate()
            t2 = await minter.get_token()

        assert t1 == "v1"
        assert t2 == "v2"
        assert post.await_count == 2
