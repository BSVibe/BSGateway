"""RFC 9728 OAuth 2.0 Protected Resource Metadata for the MCP transport.

MCP clients (Claude Code, IDE plugins) bootstrap OAuth via two steps:

1. Hit ``/mcp`` with no Authorization header → get a 401 with a
   ``WWW-Authenticate: Bearer resource_metadata="<url>"`` header.
2. Fetch the metadata URL → discover ``authorization_servers``.
3. Follow RFC 8414 on each authorization server → discover authorize +
   token endpoints, then run authorization_code + PKCE.

This module provides the two pieces this service needs:
  - :func:`build_protected_resource_metadata` — the JSON body.
  - :func:`wrap_mcp_with_oauth_401` — ASGI shim that emits the 401 +
    header on unauthenticated MCP requests, before delegating to the
    underlying transport.

The wrapper deliberately checks only header presence (not validity) —
inner MCP auth (``resolve_tool_context``) still does the full JWT check.
The wrapper exists so the *unauthenticated* path emits the discovery
header; once a token is present, the inner handler decides.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

ASGIApp = Callable[[Any, Any, Any], Awaitable[None]]


def build_protected_resource_metadata(
    *,
    resource_url: str,
    authorization_server: str,
    scopes_supported: list[str],
) -> dict[str, Any]:
    """RFC 9728 protected-resource metadata body.

    ``resource_url`` is the canonical URL of the protected resource
    (e.g. ``https://api-gateway.bsvibe.dev``). ``authorization_server``
    is the issuer URL the client should consult for its OAuth discovery
    (typically ``https://auth.bsvibe.dev``).
    """
    return {
        "resource": resource_url,
        "authorization_servers": [authorization_server],
        "bearer_methods_supported": ["header"],
        "scopes_supported": scopes_supported,
    }


def _resource_url_from_scope(scope: dict[str, Any]) -> str:
    """Derive the canonical resource URL from the ASGI scope.

    Prefers ``x-forwarded-host`` + ``x-forwarded-proto`` (Caddy / Vercel
    edge), falls back to scope's ``server`` tuple.
    """
    headers = dict(scope.get("headers") or [])

    def _h(name: bytes) -> str | None:
        v = headers.get(name)
        if isinstance(v, bytes):
            try:
                return v.decode("latin-1")
            except UnicodeDecodeError:
                return None
        return None

    proto = _h(b"x-forwarded-proto") or scope.get("scheme") or "https"
    host = _h(b"x-forwarded-host") or _h(b"host")
    if not host:
        server = scope.get("server")
        if isinstance(server, tuple) and len(server) >= 2:
            host = f"{server[0]}:{server[1]}"
        else:
            host = "localhost"
    return f"{proto}://{host}"


def wrap_mcp_with_oauth_401(
    inner: ASGIApp,
    *,
    metadata_path: str = "/.well-known/oauth-protected-resource",
) -> ASGIApp:
    """Wrap an MCP ASGI app so unauthenticated requests return 401.

    The wrapper checks for an ``Authorization: Bearer ...`` header. On
    miss, it responds with::

        HTTP/1.1 401 Unauthorized
        WWW-Authenticate: Bearer resource_metadata="<base>/.well-known/oauth-protected-resource", \
                          error="invalid_token", error_description="..."

    The ``resource_metadata`` URL is computed from the incoming
    forwarded-host/proto so the same code serves prod + every preview.

    OPTIONS / preflight passes through untouched.
    """

    async def wrapper(scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await inner(scope, receive, send)
            return
        if scope.get("method") in {"OPTIONS"}:
            await inner(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization")
        has_bearer = False
        if isinstance(auth, bytes):
            try:
                decoded = auth.decode("latin-1")
            except UnicodeDecodeError:
                decoded = ""
            has_bearer = decoded.lower().startswith("bearer ") and len(decoded) > 7
        if has_bearer:
            await inner(scope, receive, send)
            return
        # Unauthenticated MCP request — emit the discovery 401.
        base = _resource_url_from_scope(scope)
        challenge = (
            f'Bearer resource_metadata="{base}{metadata_path}", '
            f'error="invalid_token", '
            f'error_description="MCP request requires a Bearer access token"'
        )
        body = b'{"error":"unauthorized","error_description":"Bearer token required."}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", challenge.encode("latin-1")),
                    (b"access-control-expose-headers", b"WWW-Authenticate"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return wrapper


__all__ = [
    "build_protected_resource_metadata",
    "wrap_mcp_with_oauth_401",
]
