"""TASK-005 — MCP lifespan integration.

This module is the single entry point that boots the first-class MCP
server alongside the existing FastAPI gateway:

* :func:`build_registry` — register all 9 domain (TASK-003) + 30 admin
  (TASK-004) tools onto one :class:`ToolRegistry`. Both transports
  (HTTP ``/mcp`` and stdio launcher) read from this registry so
  ``ListTools`` returns the exact same catalog regardless of how the
  caller connected.
* :func:`make_loopback_caller` — return a :data:`LoopbackCaller` that
  drives the FastAPI app in-process via ``httpx.ASGITransport``.
  Admin tools share the EXACT REST request handlers the CLI hits over
  HTTP — no router-logic duplication.
* :func:`make_service_factory` — build the per-call
  :class:`MCPService` for domain tools from the running ``app.state``
  (DB pool + cache manager).
* :func:`build_streamable_http_app` — build the MCP SDK's
  :class:`StreamableHTTPSessionManager`, return both the manager and
  the per-request ASGI app that the FastAPI lifespan mounts at
  ``/mcp``. The manager's ``run()`` context is owned by the lifespan
  so request handling sees an active task group.

Auth resolution lives in :func:`bsgateway.mcp.api.resolve_tool_context`
(TASK-002); the HTTP transport stashes per-request headers on a
context-var that the resolver reads.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar
from typing import Any

import httpx
import structlog
from fastapi import FastAPI
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from bsgateway.mcp.admin_tools import LoopbackCaller, register_admin_tools
from bsgateway.mcp.api import (
    ToolContext,
    ToolRegistry,
    build_mcp_server,
    resolve_tool_context,
)
from bsgateway.mcp.server import register_domain_tools
from bsgateway.mcp.service import MCPService

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Registry assembly
# ---------------------------------------------------------------------------


_ServiceFactory = Callable[[ToolContext], MCPService]


def build_registry(
    *,
    service_factory: _ServiceFactory,
    loopback: LoopbackCaller,
) -> ToolRegistry:
    """Assemble the unified registry: 9 domain tools + 30 admin tools.

    ``service_factory`` builds an :class:`MCPService` for each domain
    tool call (production wiring uses :func:`make_service_factory` to
    read pool+cache from ``app.state``; tests inject a stub).

    ``loopback`` is the per-call transport for admin tools — production
    wiring uses :func:`make_loopback_caller` so admin tools share the
    EXACT request handlers the CLI hits over HTTP.
    """
    registry = ToolRegistry()
    register_domain_tools(registry, service_factory=service_factory)
    register_admin_tools(registry, loopback=loopback)
    return registry


# ---------------------------------------------------------------------------
# Loopback caller — ASGI transport against the running FastAPI app
# ---------------------------------------------------------------------------


def make_loopback_caller(
    app: FastAPI,
    *,
    base_url: str = "http://mcp-loopback",
) -> LoopbackCaller:
    """Return a :data:`LoopbackCaller` driven by ``httpx.ASGITransport``.

    The returned async callable matches the signature documented on
    :data:`bsgateway.mcp.admin_tools.LoopbackCaller` — handlers in
    ``admin_tools`` already pass typed args verbatim. The caller:

    * Forwards the resolved tenant id on ``X-Tenant-ID`` so tenant-
      scoped REST routes pick up the same active tenant the MCP
      caller has.
    * Forwards the user's original ``Authorization`` header from the
      MCP request context-var so admin REST routes (which `Depends`
      on ``get_current_user``) see the same principal the MCP layer
      already verified. Without this, every admin tool 401s on its
      own loopback hop (Round 4 Finding 15).
    * Forwards explicit headers from the handler (e.g. workers-register
      passes ``X-Install-Token`` here, never in the body).
    * Re-raises non-2xx responses as :class:`httpx.HTTPStatusError`
      so the dispatcher's audit emit step never fires on REST
      failures.
    """

    async def caller(
        ctx: Any,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        merged_headers: dict[str, str] = {}
        # Forward active tenant if the caller's principal has one.
        active_tenant = getattr(getattr(ctx, "user", None), "active_tenant_id", None)
        if active_tenant is not None:
            merged_headers["X-Tenant-ID"] = str(active_tenant)
        # Forward the user's Authorization so admin REST routes that
        # Depends(get_current_user) authenticate as the same principal
        # the MCP transport already verified. The header is captured by
        # the streamable-HTTP ASGI shim into _request_headers_var.
        incoming = _request_headers_var.get() or {}
        incoming_auth = incoming.get("authorization") or incoming.get("Authorization")
        if incoming_auth:
            merged_headers["Authorization"] = incoming_auth
        if headers:
            merged_headers.update(headers)

        full_path = f"/api/v1{path}" if path.startswith("/") else f"/api/v1/{path}"

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            resp = await client.request(
                method,
                full_path,
                json=body,
                params=params,
                headers=merged_headers or None,
            )
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    return caller


# ---------------------------------------------------------------------------
# Service factory — domain tools read pool+cache from app.state
# ---------------------------------------------------------------------------


def make_service_factory(app: FastAPI) -> _ServiceFactory:
    """Build a service factory that reads ``app.state`` per call.

    Domain MCP tools (rules / models / simulate / usage) need a live
    DB pool and the cache manager. Production wiring stores both on
    ``app.state`` during lifespan; the factory closes over ``app`` so
    handlers always see the current state without re-imports.
    """

    def factory(_ctx: ToolContext) -> MCPService:
        pool = getattr(app.state, "db_pool", None)
        if pool is None:
            raise RuntimeError("MCP service factory called before lifespan started")
        cache = getattr(app.state, "cache", None)
        return MCPService(pool=pool, cache=cache)

    return factory


# ---------------------------------------------------------------------------
# Public ASGI handler factory — for tests + alternate mount layouts
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Streamable HTTP transport — mounted at /mcp by the FastAPI lifespan.
# ---------------------------------------------------------------------------


_request_headers_var: ContextVar[Mapping[str, str] | None] = ContextVar(
    "_mcp_request_headers",
    default=None,
)
"""Per-request header mapping populated by the ASGI shim.

The MCP SDK's CallTool path doesn't carry HTTP headers down to the
handler, so the shim stashes them here on the way in and the auth
resolver reads them back. ``None`` (the default outside an active
request) makes :func:`resolve_tool_context` raise ``unauthenticated`` —
ruff B039 forbids a mutable default, hence ``None`` rather than ``{}``.
"""


def build_streamable_http_app(
    registry: ToolRegistry,
    *,
    app_state: object | None = None,
) -> tuple[StreamableHTTPSessionManager, Callable[..., Any]]:
    """Return ``(manager, asgi_app)`` for the ``/mcp`` HTTP transport.

    ``manager.run()`` MUST be entered by the FastAPI lifespan before
    the first request arrives — the SDK's task group is created
    there and per-request handlers raise ``RuntimeError`` otherwise.

    The returned ASGI app is what the lifespan mounts at ``/mcp``: it
    captures the incoming HTTP headers into the context-var so
    :func:`resolve_tool_context` can dispatch them through bsvibe-authz
    3-way auth, then delegates to ``manager.handle_request``.

    Stateless + JSON response is the default — agent clients are
    request/response shaped today and we don't run a session store.
    """

    async def _resolver(_unused: Mapping[str, str]) -> ToolContext:
        headers = _request_headers_var.get() or {}
        return await resolve_tool_context(headers, app_state=app_state)

    server = build_mcp_server(registry, context_resolver=_resolver)
    manager = StreamableHTTPSessionManager(
        app=server,
        stateless=True,
        json_response=True,
    )

    async def asgi_app(scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await manager.handle_request(scope, receive, send)
            return
        raw_headers = scope.get("headers", []) or []
        decoded: dict[str, str] = {}
        for k, v in raw_headers:
            try:
                decoded[k.decode("latin-1").lower()] = v.decode("latin-1")
            except (AttributeError, UnicodeDecodeError):  # pragma: no cover
                continue
        token = _request_headers_var.set(decoded)
        try:
            await manager.handle_request(scope, receive, send)
        finally:
            _request_headers_var.reset(token)

    return manager, asgi_app


__all__ = [
    "LoopbackCaller",
    "ToolContext",
    "ToolRegistry",
    "build_registry",
    "build_streamable_http_app",
    "make_loopback_caller",
    "make_service_factory",
]
