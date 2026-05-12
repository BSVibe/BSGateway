"""First-class MCP API for BSGateway (Phase 7 — TASK-002).

Tools are first-class definitions with explicit Pydantic input/output
schemas, an async handler, required scopes, and an optional audit
event. The :class:`ToolRegistry` is the single dispatcher for both
domain and admin tools (TASK-003 / TASK-004).

Design contract (mirrors REST routers, not Typer commands):

* ``ListTools`` derives the JSON Schema for each registered tool from
  ``tool.input_schema.model_json_schema()`` — schemas live next to the
  models, no auto-derivation gymnastics.
* ``CallTool`` validates input, enforces every entry of
  ``required_scopes`` against the caller's :class:`bsvibe_authz.User`,
  runs the handler, validates output, and emits a single audit event
  when ``audit_event`` is set AND the handler returned successfully.
* All errors leave the dispatcher as a typed :class:`ToolError` with a
  stable ``code`` literal (``invalid_input``, ``permission_denied``,
  ``tool_not_found``, ``invalid_output``). Handler-raised
  :class:`ToolError` propagates unchanged so domain code can surface
  application errors with their own codes.
* Failed calls (validation, scope, handler exception) MUST NOT trigger
  audit emission.

The auth resolver :func:`resolve_tool_context` mirrors the bsvibe-authz
3-way dispatch in :mod:`bsgateway.api.deps` but consumes a plain header
mapping rather than a FastAPI ``Request`` so it can be reused by both
the HTTP transport (TASK-005) and the stdio launcher.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

import structlog
from bsvibe_audit.events.base import AuditActor, AuditEventBase
from bsvibe_authz import (
    User,
)
from bsvibe_authz.deps import _scope_grants
from bsvibe_authz.deps import get_current_user as _authz_get_current_user
from fastapi import HTTPException
from mcp.server import Server as McpServer
from mcp.types import (
    TextContent,
)
from mcp.types import (
    Tool as McpTool,
)
from pydantic import BaseModel, ValidationError

from bsgateway.api.deps import (
    _authz_settings,
    _get_introspection_cache,
    _get_introspection_client,
)
from bsgateway.audit_publisher import emit_event
from bsgateway.core.config import settings as gateway_settings

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """A typed error surface for MCP tool dispatch.

    The ``code`` literal is part of the public contract — tests assert
    against it and clients route on it. Built-in dispatcher codes:

    * ``tool_not_found`` — registry miss
    * ``invalid_input`` — input did not validate against ``input_schema``
    * ``invalid_output`` — handler returned a value that failed
      ``output_schema`` validation
    * ``permission_denied`` — caller does not hold a required scope
    * ``unauthenticated`` — :func:`resolve_tool_context` rejected the
      request (missing / malformed / disabled token)

    Handlers MAY raise :class:`ToolError` with a domain-specific code
    (e.g. ``not_found``, ``conflict``); the dispatcher leaves the code
    untouched.
    """

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Tool primitive + context
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """Resolved per-call execution context.

    ``audit_app_state`` is the object that carries
    ``audit_emitter`` + ``audit_outbox_session_factory`` (typically the
    FastAPI ``app.state`` for HTTP transport, or a lifespan-built stub
    for stdio). It may be ``None`` in tests / contexts that have no
    outbox wired — the registry's audit emit step short-circuits when
    no outbox is configured (matches :func:`emit_event` semantics).

    ``log`` is a structlog logger bound with caller identity but never
    with raw tokens (:func:`resolve_tool_context` strips them on the
    way in).
    """

    settings: object
    user: User
    db: object | None = None
    audit_app_state: object | None = None
    log: structlog.BoundLogger | Any | None = None


_HandlerType = Callable[[BaseModel, ToolContext], Awaitable[BaseModel]]


@dataclass
class Tool:
    """First-class MCP tool definition (mirror of a REST route).

    ``input_schema`` and ``output_schema`` are Pydantic v2 models — the
    JSON Schema for ``input_schema`` is what ``ListTools`` advertises.
    ``required_scopes`` is enforced via the same ``_scope_grants``
    semantics that :func:`bsvibe_authz.require_scope` uses for REST
    routes (``"*"`` super-scope, ``"prefix:*"`` wildcard, exact match).
    ``audit_event`` is the literal event_type fired on success.
    """

    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    handler: _HandlerType
    required_scopes: list[str] = field(default_factory=list)
    audit_event: str | None = None


# ---------------------------------------------------------------------------
# Audit primitive
# ---------------------------------------------------------------------------


class _GatewayToolInvoked(AuditEventBase):
    """Generic audit event emitted on every successful mutating tool call.

    The ``event_type`` is overridden per call from
    :attr:`Tool.audit_event` — handlers that need richer typed events
    (for backwards compatibility with the existing ``gateway.*``
    catalog) still emit them directly via
    :func:`bsgateway.audit_publisher.emit_event`.
    """

    DEFAULT_EVENT_TYPE: ClassVar[str | None] = None


def _build_audit_event(tool: Tool, ctx: ToolContext) -> AuditEventBase | None:
    """Construct the AuditEventBase to emit on a successful tool call.

    Returns ``None`` when ``tool.audit_event`` is unset (read-only
    tools never audit).
    """
    if tool.audit_event is None:
        return None
    actor_type = "service" if ctx.user.is_service else "user"
    return _GatewayToolInvoked(
        event_type=tool.audit_event,
        actor=AuditActor(
            type=actor_type,
            id=str(ctx.user.id),
            email=ctx.user.email,
        ),
        tenant_id=ctx.user.active_tenant_id,
        data={"tool": tool.name},
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """In-memory catalog of first-class :class:`Tool` definitions.

    Single dispatcher for both domain and admin tools — tests rely on
    this being the one place where input validation, scope enforcement,
    output validation, and audit emission happen.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def list_tools(self) -> list[McpTool]:
        """Return the wire-format Tool list for ``tools/list``."""
        return [
            McpTool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_schema.model_json_schema(),
            )
            for t in self._tools.values()
        ]

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None,
        ctx: ToolContext,
    ) -> dict[str, Any]:
        """Dispatch ``name`` with ``arguments`` and the caller's context.

        Order of operations (each step is a separate failure mode):

        1. Tool lookup → ``tool_not_found``
        2. Scope enforcement → ``permission_denied``
        3. Input validation → ``invalid_input``
        4. Handler invocation → propagates :class:`ToolError`
        5. Output validation → ``invalid_output``
        6. Audit emission (only on success, only when configured)
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(code="tool_not_found", message=f"Tool not found: {name}")

        # Enforce ALL required scopes (AND-semantics).
        for required in tool.required_scopes:
            if not _scope_grants(list(ctx.user.scope), required):
                raise ToolError(
                    code="permission_denied",
                    message=f"missing required scope: {required}",
                )

        try:
            input_obj = tool.input_schema.model_validate(arguments or {})
        except ValidationError as exc:
            raise ToolError(code="invalid_input", message=exc.json()) from exc

        result = await tool.handler(input_obj, ctx)

        if not isinstance(result, tool.output_schema):
            try:
                result = tool.output_schema.model_validate(result)
            except ValidationError as exc:
                raise ToolError(code="invalid_output", message=exc.json()) from exc

        # Audit emission — only on success.
        event = _build_audit_event(tool, ctx)
        if event is not None and ctx.audit_app_state is not None:
            await emit_event(ctx.audit_app_state, event)

        return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Auth resolver — bsvibe-authz 3-way dispatch over plain headers
# ---------------------------------------------------------------------------


def _extract_bearer_token(headers: Mapping[str, str]) -> str | None:
    """Return the bearer token from headers, or ``None`` if absent."""
    # Headers are case-insensitive on the wire, but Mapping is not — we
    # accept both ``Authorization`` and ``authorization``.
    auth = headers.get("authorization") or headers.get("Authorization")
    if not auth:
        return None
    if not auth.startswith("Bearer "):
        return None
    return auth[7:]


async def resolve_tool_context(
    headers: Mapping[str, str],
    *,
    app_state: object | None = None,
) -> ToolContext:
    """Authenticate an MCP request from raw headers + return a :class:`ToolContext`.

    Delegates to :func:`bsvibe_authz.deps.get_current_user` — same
    BSage-pattern shape used by REST. The lib runs the canonical
    opaque → JWT → PAT-JWT-introspection-fallback dispatch internally,
    so PAT JWTs from the device-authorization grant work here
    automatically.

    Failure modes raise :class:`ToolError` with code ``unauthenticated``
    (the dispatcher will translate to an MCP error response).
    """
    auth_header = headers.get("authorization") or headers.get("Authorization")
    try:
        user = await _authz_get_current_user(
            authorization=auth_header,
            settings=_authz_settings(),
            introspection_client=_get_introspection_client(),
            introspection_cache=_get_introspection_cache(),
        )
    except HTTPException as exc:
        raise ToolError(code="unauthenticated", message=str(exc.detail)) from exc

    return _ctx_from_user(user, app_state=app_state)

    logger.info("mcp_auth_opaque_accepted", sub=user.id)
    return _ctx_from_user(user, app_state=app_state)


def _ctx_from_user(user: User, *, app_state: object | None) -> ToolContext:
    return ToolContext(
        settings=gateway_settings,
        user=user,
        db=None,
        audit_app_state=app_state,
        log=structlog.get_logger("bsgateway.mcp").bind(user_id=user.id),
    )


# ---------------------------------------------------------------------------
# MCP server wiring — ListTools / CallTool handlers
# ---------------------------------------------------------------------------


_ContextResolver = Callable[[Mapping[str, str]], Awaitable[ToolContext]]


def build_mcp_server(
    registry: ToolRegistry,
    *,
    context_resolver: _ContextResolver,
    name: str = "bsgateway",
) -> McpServer:
    """Create an :class:`mcp.server.Server` bound to ``registry``.

    The returned server exposes ``tools/list`` and ``tools/call``.
    Tests reach into ``server.request_handlers`` to invoke them
    directly (per memory ``mcp-python-sdk-testing`` — never spawn a
    subprocess in tests).

    ``context_resolver`` is called per-CallTool to authenticate the
    caller. Headers are NOT visible at this layer in the SDK's
    in-process call-tool path — the HTTP transport (TASK-005) plumbs
    them through a contextvar; for now we accept an empty mapping so
    the wiring shape is stable and tests can pass a stub resolver.
    """
    server = McpServer(name)

    @server.list_tools()
    async def _list_tools() -> list[McpTool]:
        return registry.list_tools()

    @server.call_tool()
    async def _call_tool(tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
        # In-process callers (TASK-005 will plumb the HTTP request
        # headers via a contextvar). We pass an empty mapping today;
        # tests inject a resolver that returns a pre-built context.
        #
        # Wrap the registry's dict/list result into [TextContent] —
        # the MCP SDK's CallToolResult.content must be a list of
        # typed ContentBlocks (TextContent, ImageContent, ...). Round 4
        # Finding 22 surfaced this once F15 unblocked the loopback auth
        # path: every list-returning tool failed with 72 validation
        # errors trying to fit a plain dict into the ContentBlock union.
        try:
            import json

            ctx = await context_resolver({})
            result = await registry.call_tool(tool_name, arguments, ctx)
            return [TextContent(type="text", text=json.dumps(result, default=str))]
        except ToolError as exc:
            # The SDK turns a raised exception into a CallToolResult
            # with isError=True whose first text block carries
            # str(exc) — encode the typed code there so callers can
            # route on it.
            raise _mcp_error(exc) from exc

    return server


def _mcp_error(exc: ToolError) -> Exception:
    """Wrap a ToolError as a generic Exception for the MCP SDK to surface.

    The SDK's ``@server.call_tool()`` decorator catches Exceptions and
    builds a CallToolResult with ``isError=True`` whose first text
    block carries ``str(exc)`` — we encode the typed code there so
    callers can route on it.
    """
    return RuntimeError(f"{exc.code}: {exc.message}")


__all__ = [
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "build_mcp_server",
    "resolve_tool_context",
]
