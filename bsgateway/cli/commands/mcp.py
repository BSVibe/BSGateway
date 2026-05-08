"""``bsgateway mcp`` sub-app — TASK-005 stdio launcher + tool inspector.

Two subcommands:

* ``list-tools`` — build the unified :class:`ToolRegistry` locally
  (no HTTP) and print the catalog. Honours the global ``--output``
  flag (``text`` default, ``json`` for agents).
* ``serve`` — boot the MCP server. ``--transport stdio`` (default)
  reads ``BSV_BOOTSTRAP_TOKEN`` from env and runs the in-process
  stdio transport. ``--transport http`` prints a hint pointing the
  operator at the running gateway's ``/mcp`` endpoint and exits
  (the HTTP transport is mounted by the gateway's lifespan, not by
  this CLI).

The registry built here uses stub callers: domain tools fail closed
on a missing service factory, admin tools fail closed on a missing
loopback. This matches stdio semantics — the CLI's role is to expose
the *shape* of the catalog and bridge stdio → ToolRegistry.dispatch;
production stdio deployments connect a long-lived HTTP loopback into
a separately-running gateway. Wiring that loopback is left to a
future task once a deployment story exists.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import structlog
import typer

from bsgateway.mcp.api import ToolError, ToolRegistry, build_mcp_server, resolve_tool_context
from bsgateway.mcp.lifespan import build_registry

logger = structlog.get_logger(__name__)


app = typer.Typer(
    name="mcp",
    help="MCP server tooling — list the catalog or boot a stdio transport.",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# Stub factories used when the CLI builds a registry without a live gateway.
# ---------------------------------------------------------------------------


def _stub_service_factory(_ctx: Any) -> Any:
    raise ToolError(
        code="unavailable",
        message=(
            "Domain MCP tools require a live gateway. Run `bsgateway mcp serve "
            "--transport http` against the gateway, or call this tool through "
            "the gateway's /mcp HTTP endpoint."
        ),
    )


async def _stub_loopback(*_args: Any, **_kwargs: Any) -> Any:
    raise ToolError(
        code="unavailable",
        message=(
            "Admin MCP tools require a live gateway. Use `bsgateway mcp serve "
            "--transport http` for the URL of the running gateway's /mcp endpoint."
        ),
    )


def _build_local_registry() -> ToolRegistry:
    return build_registry(service_factory=_stub_service_factory, loopback=_stub_loopback)


# ---------------------------------------------------------------------------
# list-tools
# ---------------------------------------------------------------------------


@app.command("list-tools")
def list_tools(ctx: typer.Context) -> None:
    """Print every registered MCP tool name (domain + admin)."""
    registry = _build_local_registry()
    names = sorted(registry.names())
    cli_ctx = ctx.obj
    fmt = getattr(getattr(cli_ctx, "formatter", None), "format", "text")
    if fmt == "json":
        typer.echo(json.dumps(names))
    else:
        for name in names:
            typer.echo(name)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


_VALID_TRANSPORTS: tuple[str, ...] = ("stdio", "http")


@app.command("serve")
def serve(
    ctx: typer.Context,
    transport: str = typer.Option(
        "stdio",
        "--transport",
        "-t",
        help="Transport to boot. 'stdio' runs the MCP server on stdin/stdout. "
        "'http' prints the URL of the running gateway's /mcp endpoint.",
        case_sensitive=False,
    ),
) -> None:
    """Boot the MCP server on the requested transport."""
    transport_lc = transport.lower()
    if transport_lc not in _VALID_TRANSPORTS:
        raise typer.BadParameter(
            f"--transport must be one of {_VALID_TRANSPORTS}, got {transport!r}"
        )

    cli_ctx = ctx.obj
    if getattr(cli_ctx, "dry_run", False):
        typer.echo(f"dry-run: would boot MCP server on transport={transport_lc}")
        return

    if transport_lc == "http":
        url = getattr(cli_ctx, "url", None) or "<gateway-url>"
        typer.echo(
            f"MCP HTTP transport is hosted by the gateway at {url}/mcp. "
            "Point your MCP client there directly — this command is for stdio."
        )
        return

    # stdio
    bootstrap_token = os.environ.get("BSV_BOOTSTRAP_TOKEN")
    if not bootstrap_token:
        raise typer.BadParameter("stdio transport requires BSV_BOOTSTRAP_TOKEN in the environment.")

    asyncio.run(_run_stdio(_build_local_registry(), bootstrap_token))


async def _run_stdio(registry: ToolRegistry, bootstrap_token: str) -> None:  # pragma: no cover
    """Run the MCP server bound to stdio.

    Excluded from coverage because it depends on real stdin/stdout —
    the unit tests verify the wiring (registry build, transport
    dispatch, dry-run / http branches) without actually attaching to
    file descriptors.
    """
    from mcp.server.stdio import stdio_server

    headers = {"Authorization": f"Bearer {bootstrap_token}"}

    async def resolver(_unused: Any) -> Any:
        return await resolve_tool_context(headers)

    server = build_mcp_server(registry, context_resolver=resolver)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


__all__ = ["app"]
