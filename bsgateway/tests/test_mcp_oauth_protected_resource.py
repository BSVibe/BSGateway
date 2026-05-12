"""Tests for the MCP OAuth protected-resource wrapper (RFC 9728)."""

from __future__ import annotations

import pytest

from bsgateway.mcp.oauth_protected_resource import (
    build_protected_resource_metadata,
    wrap_mcp_with_oauth_401,
)


def test_protected_resource_metadata_shape():
    body = build_protected_resource_metadata(
        resource_url="https://api-gateway.bsvibe.dev",
        authorization_server="https://auth.bsvibe.dev",
        scopes_supported=["gateway:*"],
    )
    assert body["resource"] == "https://api-gateway.bsvibe.dev"
    assert body["authorization_servers"] == ["https://auth.bsvibe.dev"]
    assert body["bearer_methods_supported"] == ["header"]
    assert "gateway:*" in body["scopes_supported"]


@pytest.mark.asyncio
async def test_wrapper_passes_through_when_bearer_present():
    seen: list[str] = []

    async def inner(scope, receive, send):
        seen.append("called")

    wrapped = wrap_mcp_with_oauth_401(inner)
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"authorization", b"Bearer abc.def.ghi")],
        "scheme": "https",
        "server": ("test", 443),
    }
    await wrapped(scope, None, None)
    assert seen == ["called"]


@pytest.mark.asyncio
async def test_wrapper_returns_401_with_www_authenticate_when_missing():
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def inner(scope, receive, _send):
        sent.append({"type": "inner-called"})

    wrapped = wrap_mcp_with_oauth_401(inner)
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [
            (b"x-forwarded-proto", b"https"),
            (b"x-forwarded-host", b"api-gateway.bsvibe.dev"),
        ],
        "scheme": "http",
        "server": ("internal", 80),
    }
    await wrapped(scope, None, send)
    assert not any(m.get("type") == "inner-called" for m in sent)
    start = next(m for m in sent if m.get("type") == "http.response.start")
    assert start["status"] == 401
    www = next(v for k, v in start["headers"] if k == b"www-authenticate")
    assert b"resource_metadata=" in www
    assert b"api-gateway.bsvibe.dev/.well-known/oauth-protected-resource" in www


@pytest.mark.asyncio
async def test_wrapper_options_preflight_passes_through():
    seen: list[str] = []

    async def inner(scope, receive, send):
        seen.append("called")

    wrapped = wrap_mcp_with_oauth_401(inner)
    scope = {
        "type": "http",
        "method": "OPTIONS",
        "headers": [],
        "scheme": "https",
        "server": ("test", 443),
    }
    await wrapped(scope, None, None)
    assert seen == ["called"]
