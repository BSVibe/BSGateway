"""``bsgateway intents`` sub-app — wraps ``/tenants/{tenant_id}/intents`` CRUD.

Subcommands: ``list``, ``add``, ``update``, ``delete``.

Examples can be passed as repeated ``--example "<text>"`` flags. The backend
embeds them inline when the tenant has an embedding model configured.
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
    name="intents",
    help="Manage tenant intents (list/add/update/delete).",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List intents for the active tenant.")
def list_cmd(ctx: typer.Context) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)
    path = f"/tenants/{tenant}/intents"

    if obj.dry_run:
        emit_dry_run(obj, {"method": "GET", "path": path})
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.get(path)
        finally:
            await client.aclose()

    resp = run_async(_go)
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)
    obj.formatter.emit(resp.json() or [])


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


@app.command("add", help="Create an intent (with optional examples).")
def add_cmd(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Intent name (slug)."),
    description: str = typer.Option("", "--description", help="Human-readable description."),
    threshold: float = typer.Option(0.7, "--threshold", help="Similarity threshold (0..1)."),
    examples: list[str] = typer.Option(
        [],
        "--example",
        "-e",
        help="Example utterance (repeat for multiple).",
    ),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)

    body: dict[str, Any] = {
        "name": name,
        "description": description,
        "threshold": threshold,
        "examples": list(examples),
    }
    path = f"/tenants/{tenant}/intents"

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
# update
# ---------------------------------------------------------------------------


@app.command("update", help="Patch an intent (only the fields you pass).")
def update_cmd(
    ctx: typer.Context,
    intent_id: str = typer.Argument(..., help="Intent id (uuid)."),
    name: str | None = typer.Option(None, "--name"),
    description: str | None = typer.Option(None, "--description"),
    threshold: float | None = typer.Option(None, "--threshold"),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)

    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if threshold is not None:
        body["threshold"] = threshold

    if not body:
        raise typer.BadParameter(
            "update needs at least one of --name / --description / --threshold"
        )

    path = f"/tenants/{tenant}/intents/{intent_id}"

    if obj.dry_run:
        emit_dry_run(obj, {"method": "PATCH", "path": path, "body": body})
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.request("PATCH", path, json=body)
        finally:
            await client.aclose()

    resp = run_async(_go)
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)
    obj.formatter.emit(resp.json())


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@app.command("delete", help="Delete an intent.")
def delete_cmd(
    ctx: typer.Context,
    intent_id: str = typer.Argument(..., help="Intent id (uuid)."),
    if_exists: bool = typer.Option(
        False, "--if-exists", help="Treat 404 as success (idempotent delete)."
    ),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)
    path = f"/tenants/{tenant}/intents/{intent_id}"

    if obj.dry_run:
        emit_dry_run(obj, {"method": "DELETE", "path": path})
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.delete(path)
        finally:
            await client.aclose()

    resp = run_async(_go)
    if resp.status_code == 404 and if_exists:
        obj.formatter.emit({"deleted": False, "id": intent_id, "reason": "not_found"})
        return
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)
    obj.formatter.emit({"deleted": True, "id": intent_id})


__all__ = ["app"]
