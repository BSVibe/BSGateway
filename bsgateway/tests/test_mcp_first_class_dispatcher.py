"""TASK-002 — first-class MCP Tool primitive + dispatcher.

These tests pin the contract that ``bsgateway/mcp/api.py`` must satisfy:

* ``Tool`` is a typed primitive (Pydantic input/output schemas, async
  handler, required scopes, optional audit_event literal).
* ``ToolRegistry.list_tools()`` derives JSON Schema from
  ``input_schema.model_json_schema()`` and emits one ``mcp.types.Tool``
  per registered tool.
* ``ToolRegistry.call_tool()`` validates input against ``input_schema``,
  enforces every entry in ``required_scopes`` against the caller's
  scope list (with ``"prefix:*"`` semantics), runs the handler, validates
  output, and emits a single audit event when ``audit_event`` is set AND
  the handler returned successfully.
* Errors translate to a typed :class:`ToolError` with a stable code
  (``invalid_input``, ``permission_denied``, ``tool_not_found``,
  ``invalid_output``); handler-raised :class:`ToolError` propagates
  unchanged. Failed calls do NOT trigger audit emission.
* ``resolve_tool_context`` mirrors :mod:`bsgateway.api.deps` dispatch
  (opaque → JWT) but consumes a plain header mapping rather than a
  FastAPI ``Request``.

Per memory ``mcp-python-sdk-testing``, the in-process pattern (no
subprocesses) is enforced by exercising the registry directly and via
the ``server.request_handlers`` map for the integration sanity check.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bsvibe_authz import User
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    ListToolsRequest,
    ServerResult,
)
from pydantic import BaseModel, Field

from bsgateway.mcp.api import (
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
    build_mcp_server,
    resolve_tool_context,
)

# ---------------------------------------------------------------------------
# Dummy schemas + handlers
# ---------------------------------------------------------------------------


class _EchoIn(BaseModel):
    message: str = Field(min_length=1)


class _EchoOut(BaseModel):
    echoed: str


class _AddIn(BaseModel):
    a: int
    b: int


class _AddOut(BaseModel):
    sum: int


async def _echo_handler(args: _EchoIn, ctx: ToolContext) -> _EchoOut:
    return _EchoOut(echoed=args.message)


async def _add_handler(args: _AddIn, ctx: ToolContext) -> _AddOut:
    return _AddOut(sum=args.a + args.b)


async def _bad_output_handler(args: _EchoIn, ctx: ToolContext) -> _EchoOut:
    # Returns the wrong shape — dispatcher must catch it as invalid_output.
    return {"not_a_model": True}  # type: ignore[return-value]


async def _raises_handler(args: _EchoIn, ctx: ToolContext) -> _EchoOut:
    raise ToolError(code="boom", message="domain error")


def _make_user(scopes: list[str] | None = None, tenant_id: str | None = None) -> User:
    return User(
        id="user-1",
        email="u@example.com",
        active_tenant_id=tenant_id,
        tenants=[],
        is_service=False,
        scope=scopes or [],
    )


def _make_ctx(user: User | None = None) -> ToolContext:
    return ToolContext(
        settings=MagicMock(),
        user=user or _make_user(scopes=["*"]),
        db=None,
        audit_app_state=None,
        log=MagicMock(),
    )


# ---------------------------------------------------------------------------
# Registry + ListTools
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def test_register_and_get(self) -> None:
        reg = ToolRegistry()
        tool = Tool(
            name="echo",
            description="Echo a message",
            input_schema=_EchoIn,
            output_schema=_EchoOut,
            handler=_echo_handler,
        )
        reg.register(tool)
        assert reg.get("echo") is tool
        assert "echo" in reg.names()

    def test_register_duplicate_raises(self) -> None:
        reg = ToolRegistry()
        tool = Tool(
            name="echo",
            description="x",
            input_schema=_EchoIn,
            output_schema=_EchoOut,
            handler=_echo_handler,
        )
        reg.register(tool)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(tool)

    def test_list_tools_emits_input_schema_jsonschema(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="Echo",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_echo_handler,
            )
        )
        listing = reg.list_tools()
        assert len(listing) == 1
        item = listing[0]
        assert item.name == "echo"
        # The JSON Schema for the input model lives on the listed tool.
        assert item.inputSchema["type"] == "object"
        assert "message" in item.inputSchema["properties"]
        # Required field came through.
        assert "message" in item.inputSchema.get("required", [])


# ---------------------------------------------------------------------------
# CallTool — input validation + scopes + output validation + errors
# ---------------------------------------------------------------------------


class TestCallToolBasics:
    async def test_validates_input_and_returns_dict(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_echo_handler,
            )
        )
        result = await reg.call_tool("echo", {"message": "hi"}, _make_ctx())
        assert result == {"echoed": "hi"}

    async def test_unknown_tool_raises_tool_not_found(self) -> None:
        reg = ToolRegistry()
        with pytest.raises(ToolError) as exc:
            await reg.call_tool("missing", {}, _make_ctx())
        assert exc.value.code == "tool_not_found"

    async def test_invalid_input_raises_invalid_input(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_echo_handler,
            )
        )
        with pytest.raises(ToolError) as exc:
            await reg.call_tool("echo", {"message": ""}, _make_ctx())
        assert exc.value.code == "invalid_input"

    async def test_handler_tool_error_propagates(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="boom",
                description="x",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_raises_handler,
            )
        )
        with pytest.raises(ToolError) as exc:
            await reg.call_tool("boom", {"message": "ok"}, _make_ctx())
        assert exc.value.code == "boom"

    async def test_invalid_output_raises_invalid_output(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="bad",
                description="x",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_bad_output_handler,
            )
        )
        with pytest.raises(ToolError) as exc:
            await reg.call_tool("bad", {"message": "ok"}, _make_ctx())
        assert exc.value.code == "invalid_output"


class TestCallToolScopeEnforcement:
    async def test_missing_scope_raises_permission_denied(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_echo_handler,
                required_scopes=["bsgateway:models:write"],
            )
        )
        ctx = _make_ctx(_make_user(scopes=["bsgateway:models:read"]))
        with pytest.raises(ToolError) as exc:
            await reg.call_tool("echo", {"message": "hi"}, ctx)
        assert exc.value.code == "permission_denied"

    async def test_prefix_wildcard_grants_subscope(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_echo_handler,
                required_scopes=["bsgateway:models:write"],
            )
        )
        ctx = _make_ctx(_make_user(scopes=["bsgateway:*"]))
        result = await reg.call_tool("echo", {"message": "hi"}, ctx)
        assert result == {"echoed": "hi"}

    async def test_all_required_scopes_must_be_present(self) -> None:
        # When two scopes are required, a user holding only one must be denied.
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_echo_handler,
                required_scopes=["bsgateway:models:write", "bsgateway:routing:write"],
            )
        )
        ctx = _make_ctx(_make_user(scopes=["bsgateway:models:write"]))
        with pytest.raises(ToolError) as exc:
            await reg.call_tool("echo", {"message": "hi"}, ctx)
        assert exc.value.code == "permission_denied"


# ---------------------------------------------------------------------------
# Audit emission
# ---------------------------------------------------------------------------


class _AuditCapture:
    """Stand-in for ``app_state`` that records every emit_event call."""

    def __init__(self) -> None:
        self.audit_emitter = AsyncMock()
        self.audit_outbox_session_factory = MagicMock()
        self.events: list[Any] = []

    async def _capture(self, app_state: Any, event: Any) -> None:
        self.events.append(event)


class TestAuditEmission:
    async def test_audit_event_emitted_on_success(self) -> None:
        cap = _AuditCapture()
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="add",
                description="x",
                input_schema=_AddIn,
                output_schema=_AddOut,
                handler=_add_handler,
                audit_event="gateway.tool.add",
            )
        )
        ctx = ToolContext(
            settings=MagicMock(),
            user=_make_user(scopes=["*"], tenant_id="00000000-0000-0000-0000-000000000001"),
            db=None,
            audit_app_state=cap,
            log=MagicMock(),
        )

        with patch(
            "bsgateway.mcp.api.emit_event",
            side_effect=cap._capture,
        ):
            await reg.call_tool("add", {"a": 1, "b": 2}, ctx)

        assert len(cap.events) == 1
        ev = cap.events[0]
        assert ev.event_type == "gateway.tool.add"
        assert ev.actor.id == "user-1"
        assert ev.tenant_id == "00000000-0000-0000-0000-000000000001"
        # Tool name surfaces in data so the audit consumer can route.
        assert ev.data.get("tool") == "add"

    async def test_no_audit_event_when_audit_event_unset(self) -> None:
        cap = _AuditCapture()
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_echo_handler,
                # audit_event left None → read-only tool, no emit.
            )
        )
        ctx = ToolContext(
            settings=MagicMock(),
            user=_make_user(scopes=["*"]),
            audit_app_state=cap,
            log=MagicMock(),
        )
        with patch("bsgateway.mcp.api.emit_event", side_effect=cap._capture):
            await reg.call_tool("echo", {"message": "hi"}, ctx)
        assert cap.events == []

    async def test_no_audit_event_on_handler_failure(self) -> None:
        cap = _AuditCapture()
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="boom",
                description="x",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_raises_handler,
                audit_event="gateway.tool.boom",
            )
        )
        ctx = ToolContext(
            settings=MagicMock(),
            user=_make_user(scopes=["*"]),
            audit_app_state=cap,
            log=MagicMock(),
        )
        with patch("bsgateway.mcp.api.emit_event", side_effect=cap._capture):
            with pytest.raises(ToolError):
                await reg.call_tool("boom", {"message": "ok"}, ctx)
        assert cap.events == []

    async def test_no_audit_event_on_scope_denied(self) -> None:
        cap = _AuditCapture()
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="add",
                description="x",
                input_schema=_AddIn,
                output_schema=_AddOut,
                handler=_add_handler,
                required_scopes=["bsgateway:models:write"],
                audit_event="gateway.tool.add",
            )
        )
        ctx = ToolContext(
            settings=MagicMock(),
            user=_make_user(scopes=[]),
            audit_app_state=cap,
            log=MagicMock(),
        )
        with patch("bsgateway.mcp.api.emit_event", side_effect=cap._capture):
            with pytest.raises(ToolError):
                await reg.call_tool("add", {"a": 1, "b": 2}, ctx)
        assert cap.events == []

    async def test_audit_skipped_when_app_state_missing(self) -> None:
        # No audit_app_state → registry must NOT explode; emit is a no-op.
        cap = _AuditCapture()
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="add",
                description="x",
                input_schema=_AddIn,
                output_schema=_AddOut,
                handler=_add_handler,
                audit_event="gateway.tool.add",
            )
        )
        ctx = _make_ctx(_make_user(scopes=["*"]))  # audit_app_state is None
        with patch("bsgateway.mcp.api.emit_event", side_effect=cap._capture):
            await reg.call_tool("add", {"a": 1, "b": 2}, ctx)
        # We don't insist on whether emit_event is called or not — but we DO
        # insist that no event was actually appended (since app_state is None
        # the real emit_event would short-circuit; the registry honors that).
        assert cap.events == []


# ---------------------------------------------------------------------------
# build_mcp_server: ListTools / CallTool wired through MCP server handlers
# ---------------------------------------------------------------------------


class TestBuildMcpServer:
    async def test_list_tools_handler_returns_registered_tools(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="Echo",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_echo_handler,
            )
        )

        async def _resolver(headers: dict[str, str]) -> ToolContext:
            return _make_ctx(_make_user(scopes=["*"]))

        server = build_mcp_server(reg, context_resolver=_resolver)
        # Per memory `mcp-python-sdk-testing`: invoke the registered handler
        # directly, do not spawn a subprocess.
        handler = server.request_handlers[ListToolsRequest]
        req = ListToolsRequest(method="tools/list")
        result = await handler(req)
        assert isinstance(result, ServerResult)
        names = [t.name for t in result.root.tools]
        assert "echo" in names

    async def test_call_tool_handler_runs_registered_tool(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="add",
                description="x",
                input_schema=_AddIn,
                output_schema=_AddOut,
                handler=_add_handler,
            )
        )

        async def _resolver(headers: dict[str, str]) -> ToolContext:
            return _make_ctx(_make_user(scopes=["*"]))

        server = build_mcp_server(reg, context_resolver=_resolver)
        handler = server.request_handlers[CallToolRequest]
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="add", arguments={"a": 2, "b": 3}),
        )
        result = await handler(req)
        assert isinstance(result, ServerResult)
        # Successful call: not an error. The result dict is JSON-serialized
        # into the wire-required TextContent block (Round 4 Finding 22).
        assert result.root.isError is False
        import json

        text_blocks = [c for c in result.root.content if c.type == "text"]
        assert text_blocks, "expected a text content block"
        assert json.loads(text_blocks[0].text) == {"sum": 5}

    async def test_call_tool_handler_translates_tool_error(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_echo_handler,
                required_scopes=["bsgateway:models:write"],
            )
        )

        async def _resolver(headers: dict[str, str]) -> ToolContext:
            # Caller has no scopes → permission_denied
            return _make_ctx(_make_user(scopes=[]))

        server = build_mcp_server(reg, context_resolver=_resolver)
        handler = server.request_handlers[CallToolRequest]
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="echo", arguments={"message": "hi"}),
        )
        result = await handler(req)
        # ToolError is reflected as isError=True with a text content payload.
        assert result.root.isError is True
        text_blocks = [c for c in result.root.content if c.type == "text"]
        assert text_blocks, "expected a text error content block"
        assert "permission_denied" in text_blocks[0].text


# ---------------------------------------------------------------------------
# resolve_tool_context — bsvibe-authz dispatch over plain headers
# ---------------------------------------------------------------------------


class TestResolveToolContextHeaderValidation:
    async def test_missing_authorization_header_raises_tool_error(self) -> None:
        with pytest.raises(ToolError) as exc:
            await resolve_tool_context(headers={}, app_state=MagicMock())
        assert exc.value.code == "unauthenticated"

    async def test_non_bearer_authorization_rejected(self) -> None:
        with pytest.raises(ToolError) as exc:
            await resolve_tool_context(
                headers={"authorization": "Basic abc"},
                app_state=MagicMock(),
            )
        assert exc.value.code == "unauthenticated"

    async def test_unsupported_token_kind_rejected(self) -> None:
        # Garbage 3-segment string — neither a verifiable user JWT nor
        # a PAT JWT introspection accepts. The resolver must reject.
        with pytest.raises(ToolError) as exc:
            await resolve_tool_context(
                headers={"authorization": "Bearer some.jwt.token"},
                app_state=MagicMock(),
            )
        assert exc.value.code == "unauthenticated"


class TestResolveToolContextIntrospection:
    """PAT-JWT introspection paths through ``resolve_tool_context``.

    bsvibe-authz 1.3.0 retired the legacy ``bsv_sk_*`` opaque dispatch;
    introspection now serves only JWT-shaped PATs issued by the
    device-authorization grant. These tests stub
    ``_authz_get_current_user`` directly, so the token string is
    cosmetic — what's exercised is the BSGateway-side translation of
    the dispatch outcome into a :class:`ToolContext` / :class:`ToolError`.
    """

    _PAT_JWT = "Bearer eyJhbGciOiJFUzI1NiJ9.fake.pat"

    async def test_pat_token_without_introspection_url_rejected(self, monkeypatch) -> None:
        # introspection_url unset → introspection client is None → reject.
        from bsgateway.api import deps as _deps

        monkeypatch.setattr(_deps.gateway_settings, "introspection_url", "")
        _deps._reset_dispatch_singletons()

        with pytest.raises(ToolError) as exc:
            await resolve_tool_context(
                headers={"authorization": self._PAT_JWT},
                app_state=MagicMock(),
            )
        assert exc.value.code == "unauthenticated"

    async def test_pat_token_active_yields_context(self, monkeypatch) -> None:
        # Resolve goes through bsvibe_authz.deps.get_current_user — stub it.
        stub_user = User(
            id="svc-1",
            email=None,
            active_tenant_id=None,
            tenants=[],
            is_service=True,
            scope=["bsgateway:models:read"],
        )

        async def _fake_get_current_user(**_kwargs):
            return stub_user

        monkeypatch.setattr("bsgateway.mcp.api._authz_get_current_user", _fake_get_current_user)

        ctx = await resolve_tool_context(
            headers={"authorization": self._PAT_JWT},
            app_state=MagicMock(),
        )
        assert ctx.user.id == "svc-1"
        assert ctx.user.is_service is True

    async def test_pat_token_introspection_failure_rejected(self, monkeypatch) -> None:
        from fastapi import HTTPException

        async def _fake_get_current_user(**_kwargs):
            raise HTTPException(status_code=401, detail="inactive token")

        monkeypatch.setattr("bsgateway.mcp.api._authz_get_current_user", _fake_get_current_user)

        with pytest.raises(ToolError) as exc:
            await resolve_tool_context(
                headers={"authorization": self._PAT_JWT},
                app_state=MagicMock(),
            )
        assert exc.value.code == "unauthenticated"


class TestRegistryLen:
    def test_registry_len_reflects_register_calls(self) -> None:
        reg = ToolRegistry()
        assert len(reg) == 0
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=_EchoIn,
                output_schema=_EchoOut,
                handler=_echo_handler,
            )
        )
        assert len(reg) == 1
