"""TASK-005 — MCP lifespan integration: registry builder + loopback caller.

Covers the wiring that boots the first-class MCP server alongside the
FastAPI app:

* :func:`bsgateway.mcp.lifespan.build_registry` registers all 9 domain
  + 30 admin tools onto a single :class:`ToolRegistry`.
* :func:`bsgateway.mcp.lifespan.make_loopback_caller` returns an async
  caller that drives the FastAPI app via ``httpx.ASGITransport`` —
  admin tools share the EXACT REST request handlers without duplication.
* The mounted ``/mcp`` ASGI handler is reachable.
* ``/mcp/health`` reports liveness + tool count.

Tests follow memory ``mcp-python-sdk-testing`` — no subprocesses, no
real network.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from bsgateway.mcp.api import ToolRegistry
from bsgateway.mcp.lifespan import build_registry, make_loopback_caller, make_service_factory

# ---------------------------------------------------------------------------
# build_registry
# ---------------------------------------------------------------------------


class TestBuildRegistry:
    def test_returns_tool_registry(self):
        reg = build_registry(
            service_factory=lambda _ctx: MagicMock(),
            loopback=AsyncMock(return_value={}),
        )
        assert isinstance(reg, ToolRegistry)

    def test_registers_domain_tools(self):
        reg = build_registry(
            service_factory=lambda _ctx: MagicMock(),
            loopback=AsyncMock(return_value={}),
        )
        names = reg.names()
        # 9 domain tools (TASK-003)
        assert "bsgateway_mcp_list_rules" in names
        assert "bsgateway_mcp_create_rule" in names
        assert "bsgateway_mcp_get_cost_report" in names

    def test_registers_admin_tools(self):
        reg = build_registry(
            service_factory=lambda _ctx: MagicMock(),
            loopback=AsyncMock(return_value={}),
        )
        names = reg.names()
        # spot-check 5 admin tools (TASK-004)
        for expected in (
            "bsgateway_models_list",
            "bsgateway_rules_add",
            "bsgateway_tenants_show",
            "bsgateway_workers_register",
            "bsgateway_execute",
        ):
            assert expected in names

    def test_total_tool_count_at_least_39(self):
        """Domain (9) + admin (30) = 39 — drift guard."""
        reg = build_registry(
            service_factory=lambda _ctx: MagicMock(),
            loopback=AsyncMock(return_value={}),
        )
        assert len(reg) >= 39

    def test_no_name_collisions(self):
        reg = build_registry(
            service_factory=lambda _ctx: MagicMock(),
            loopback=AsyncMock(return_value={}),
        )
        names = reg.names()
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# make_loopback_caller
# ---------------------------------------------------------------------------


class TestMakeLoopbackCaller:
    async def test_dispatches_through_asgi_app(self):
        app = FastAPI()

        @app.get("/api/v1/probe")
        async def probe() -> dict[str, str]:
            return {"ok": "yes"}

        caller = make_loopback_caller(app)
        ctx = MagicMock()
        ctx.user.scope = ["*"]
        ctx.user.id = "u-1"

        result = await caller(ctx, "GET", "/probe")
        assert result == {"ok": "yes"}

    async def test_forwards_tenant_and_custom_headers(self):
        captured: dict[str, str] = {}
        app = FastAPI()

        @app.post("/api/v1/echo")
        async def echo(request: Request) -> dict[str, str]:
            captured["xtenant"] = request.headers.get("x-tenant-id", "")
            captured["xcustom"] = request.headers.get("x-custom", "")
            return {"echoed": "yes"}

        caller = make_loopback_caller(app)
        ctx = MagicMock()
        ctx.user.scope = ["*"]
        ctx.user.id = "u-1"
        ctx.user.is_service = False
        ctx.user.active_tenant_id = "t-99"

        await caller(
            ctx,
            "POST",
            "/echo",
            body={"a": 1},
            headers={"X-Custom": "v"},
        )
        # X-Tenant-ID derived from ctx.user.active_tenant_id; explicit
        # headers (X-Install-Token etc.) propagate verbatim.
        assert captured["xtenant"] == "t-99"
        assert captured["xcustom"] == "v"

    async def test_returns_none_for_empty_response(self):
        """``204 No Content`` (and any empty body) yields ``None``."""
        app = FastAPI()

        @app.delete("/api/v1/empty", status_code=204)
        async def empty() -> None:
            return None

        caller = make_loopback_caller(app)
        ctx = MagicMock()
        ctx.user.scope = ["*"]
        ctx.user.is_service = False
        ctx.user.active_tenant_id = None

        result = await caller(ctx, "DELETE", "/empty")
        assert result is None

    async def test_forwards_authorization_from_request_headers_var(self):
        """Round 4 Finding 15: loopback caller must forward the MCP
        request's Authorization header so the inner admin REST hop
        authenticates as the same principal the MCP transport already
        verified. Without this, every admin tool 401s on its own loopback."""
        from bsgateway.mcp.lifespan import _request_headers_var

        captured: dict[str, str] = {}
        app = FastAPI()

        @app.get("/api/v1/auth-probe")
        async def auth_probe(request: Request) -> dict[str, str]:
            captured["auth"] = request.headers.get("authorization", "")
            return {"ok": "yes"}

        caller = make_loopback_caller(app)
        ctx = MagicMock()
        ctx.user.scope = ["*"]
        ctx.user.is_service = False
        ctx.user.active_tenant_id = None

        token = _request_headers_var.set({"authorization": "Bearer the-user-pat"})
        try:
            await caller(ctx, "GET", "/auth-probe")
        finally:
            _request_headers_var.reset(token)
        assert captured["auth"] == "Bearer the-user-pat"

    async def test_no_authorization_when_context_var_empty(self):
        """Outside an MCP request (no headers stashed), the loopback
        caller does not invent an Authorization header — the REST hop
        will 401 normally, which is the desired failure mode."""
        captured: dict[str, str] = {}
        app = FastAPI()

        @app.get("/api/v1/auth-probe2")
        async def auth_probe2(request: Request) -> dict[str, str]:
            captured["auth"] = request.headers.get("authorization", "<missing>")
            return {"ok": "yes"}

        caller = make_loopback_caller(app)
        ctx = MagicMock()
        ctx.user.scope = ["*"]
        ctx.user.is_service = False
        ctx.user.active_tenant_id = None

        await caller(ctx, "GET", "/auth-probe2")
        assert captured["auth"] == "<missing>"

    async def test_propagates_query_params(self):
        captured: dict[str, str] = {}
        app = FastAPI()

        @app.get("/api/v1/q")
        async def q(request: Request) -> dict[str, int]:
            captured["days"] = request.query_params.get("days", "")
            return {"got": 1}

        caller = make_loopback_caller(app)
        ctx = MagicMock()
        ctx.user.scope = ["*"]
        ctx.user.is_service = False
        ctx.user.active_tenant_id = None

        await caller(ctx, "GET", "/q", params={"days": 7})
        assert captured["days"] == "7"


# ---------------------------------------------------------------------------
# /mcp/health endpoint integration
# ---------------------------------------------------------------------------


class TestMcpHealthEndpoint:
    """The /mcp/health endpoint reports tool count + liveness.

    We patch the heavy parts of lifespan (DB pool, redis, schemas)
    because /mcp/health only needs ``app.state.mcp_registry`` populated.
    """

    def test_reports_tool_count(self):
        from bsgateway.api.app import create_app

        app = create_app()

        # The /mcp/health route reads from app.state.mcp_registry which
        # is populated in lifespan. For a focused unit test we set it
        # directly without booting lifespan.
        app.state.mcp_registry = build_registry(
            service_factory=lambda _ctx: MagicMock(),
            loopback=AsyncMock(return_value={}),
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/mcp/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["tool_count"] >= 39

    def test_returns_503_when_registry_missing(self):
        from bsgateway.api.app import create_app

        app = create_app()
        # No app.state.mcp_registry assigned -> not ready
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/mcp/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "unavailable"


# ---------------------------------------------------------------------------
# /mcp ASGI mount
# ---------------------------------------------------------------------------


class TestMcpRoute:
    def test_mcp_route_registered(self):
        from bsgateway.api.app import create_app

        app = create_app()
        paths = [getattr(r, "path", None) for r in app.routes]
        # Either a dedicated /mcp mount or /mcp* path is present.
        assert any(p and p.startswith("/mcp") for p in paths), paths


# ---------------------------------------------------------------------------
# make_service_factory
# ---------------------------------------------------------------------------


class TestMakeServiceFactory:
    def test_raises_when_pool_missing(self):
        app = FastAPI()
        # No app.state.db_pool set -> factory must fail loudly so the
        # operator notices the misconfiguration during boot, not at the
        # first MCP tool call.
        factory = make_service_factory(app)
        with pytest.raises(RuntimeError, match="lifespan"):
            factory(MagicMock())

    def test_builds_mcp_service_from_pool(self):
        app = FastAPI()
        app.state.db_pool = MagicMock()
        app.state.cache = None

        factory = make_service_factory(app)
        svc = factory(MagicMock())
        # MCPService keeps the pool privately — verify shape via attr.
        assert getattr(svc, "_pool", None) is app.state.db_pool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_real_introspection(monkeypatch):
    # Defensive — prevent any test in this module from accidentally
    # reaching out for introspection if a misconfigured token slips in.
    from bsgateway.api import deps

    monkeypatch.setattr(deps, "_get_introspection_client", lambda: None)
    monkeypatch.setattr(deps, "_get_introspection_cache", lambda: None)
