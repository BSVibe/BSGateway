"""``bsgateway feedback`` sub-app — wraps ``/tenants/{tenant_id}/feedback``.

Subcommands: ``add``, ``list``.

Feedback rows are tied to a specific routing decision (``--routing-id``)
so the operator / agent can flag bad routes for later review.
"""

from __future__ import annotations

from typing import Any

import structlog
import typer

from bsgateway.cli._client import build_client
from bsgateway.cli.commands._common import (
    emit_dry_run,
    emit_http_error,
    require_tenant,
    run_async,
)

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="feedback",
    help="Submit and list routing feedback (add/list).",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


@app.command("add", help="Submit feedback for a routing decision.")
def add_cmd(
    ctx: typer.Context,
    routing_id: str = typer.Option(..., "--routing-id", help="Routing decision id."),
    rating: int = typer.Option(..., "--rating", min=1, max=5, help="Rating 1..5."),
    comment: str = typer.Option("", "--comment", help="Optional free-text comment."),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)

    body: dict[str, Any] = {
        "routing_id": routing_id,
        "rating": rating,
        "comment": comment,
    }
    path = f"/tenants/{tenant}/feedback"

    if obj.dry_run:
        emit_dry_run(obj, {"method": "POST", "path": path, "body": body})
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.post(path, json=body)
        finally:
            await client.aclose()

    resp = run_async(_go)
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)
    obj.formatter.emit(resp.json())


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List feedback rows for the active tenant.")
def list_cmd(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="Page size."),
    offset: int = typer.Option(0, "--offset", min=0, help="Page offset."),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)
    path = f"/tenants/{tenant}/feedback"
    params = {"limit": limit, "offset": offset}

    if obj.dry_run:
        emit_dry_run(obj, {"method": "GET", "path": path, "params": params})
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.get(path, params=params)
        finally:
            await client.aclose()

    resp = run_async(_go)
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)
    obj.formatter.emit(resp.json() or [])


__all__ = ["app"]
