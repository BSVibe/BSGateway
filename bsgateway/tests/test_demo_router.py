"""Tests for the BSGateway demo HTTP endpoints + auth dependency."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsgateway.demo.auth import demo_auth_context, get_demo_jwt_secret
from bsgateway.demo.jwt import mint_demo_jwt
from bsgateway.demo.router import demo_router


@pytest.fixture
def app() -> FastAPI:
    """FastAPI app with demo router mounted."""
    a = FastAPI()
    a.include_router(demo_router, prefix="/api/v1")
    return a


@pytest.fixture
def jwt_secret() -> str:
    return "h" * 64


def _override_jwt_secret(app: FastAPI, secret: str) -> None:
    app.dependency_overrides[get_demo_jwt_secret] = lambda: secret


class TestPostDemoSession:
    def test_create_session_returns_201_with_token_and_tenant_id(
        self, app: FastAPI, jwt_secret: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Mock the service so it doesn't actually hit PG
        from bsgateway.demo import session as session_module

        mock_service = AsyncMock()
        tid = uuid4()
        mock_service.create_session.return_value = session_module.DemoSessionResult(
            tenant_id=tid,
            token=mint_demo_jwt(tid, secret=jwt_secret, ttl_seconds=7200),
            expires_in=7200,
        )

        async def _override_service():
            return mock_service

        from bsgateway.demo.router import get_demo_session_service

        app.dependency_overrides[get_demo_session_service] = _override_service
        _override_jwt_secret(app, jwt_secret)

        client = TestClient(app)
        resp = client.post("/api/v1/demo/session")

        assert resp.status_code == 201
        body = resp.json()
        assert "token" in body
        assert "tenant_id" in body
        assert "expires_in" in body
        assert body["tenant_id"] == str(tid)

    def test_create_session_sets_cookie(self, app: FastAPI, jwt_secret: str) -> None:
        from bsgateway.demo import session as session_module
        from bsgateway.demo.router import get_demo_session_service

        mock_service = AsyncMock()
        tid = uuid4()
        token = mint_demo_jwt(tid, secret=jwt_secret, ttl_seconds=7200)
        mock_service.create_session.return_value = session_module.DemoSessionResult(
            tenant_id=tid, token=token, expires_in=7200
        )

        async def _override_service():
            return mock_service

        app.dependency_overrides[get_demo_session_service] = _override_service
        _override_jwt_secret(app, jwt_secret)

        client = TestClient(app)
        resp = client.post("/api/v1/demo/session")

        # Cookie must be set with HttpOnly + Secure + SameSite for the session
        cookies = resp.headers.get("set-cookie", "")
        assert "bsvibe_demo_session=" in cookies
        assert "HttpOnly" in cookies or "httponly" in cookies.lower()
        assert "SameSite" in cookies or "samesite" in cookies.lower()


class TestDemoAuthContext:
    @pytest.mark.asyncio
    async def test_valid_demo_jwt_returns_auth_context(self, jwt_secret: str) -> None:
        from fastapi import Request

        tid = uuid4()
        token = mint_demo_jwt(tid, secret=jwt_secret, ttl_seconds=60)

        # Build a fake Request with the bearer header
        scope = {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
        request = Request(scope)

        ctx = await demo_auth_context(request, secret=jwt_secret)
        assert ctx.tenant_id == tid
        assert ctx.is_admin is False

    @pytest.mark.asyncio
    async def test_invalid_jwt_raises_401(self, jwt_secret: str) -> None:
        from fastapi import HTTPException, Request

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer not-a-real-token")],
        }
        request = Request(scope)

        with pytest.raises(HTTPException) as exc_info:
            await demo_auth_context(request, secret=jwt_secret)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_header_raises_401(self, jwt_secret: str) -> None:
        from fastapi import HTTPException, Request

        scope = {"type": "http", "headers": []}
        request = Request(scope)

        with pytest.raises(HTTPException) as exc_info:
            await demo_auth_context(request, secret=jwt_secret)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_cookie_fallback_when_header_missing(self, jwt_secret: str) -> None:
        from fastapi import Request

        tid = uuid4()
        token = mint_demo_jwt(tid, secret=jwt_secret, ttl_seconds=60)
        scope = {
            "type": "http",
            "headers": [(b"cookie", f"bsvibe_demo_session={token}".encode())],
        }
        request = Request(scope)

        ctx = await demo_auth_context(request, secret=jwt_secret)
        assert ctx.tenant_id == tid
