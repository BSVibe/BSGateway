"""``bsgateway tenants`` sub-app — wraps the top-level ``/tenants`` router.

Subcommands: ``list``, ``add``, ``show``, ``update``, ``delete``.

The ``tenants`` resource is operator-scoped (gateway:tenants:{read,write}) —
none of the subcommands require ``--tenant`` from :class:`CliContext`. The
subject of the operation is always the ``<tenant_id>`` passed positionally
(``show``/``update``/``delete``) or implicit via ``POST /tenants`` (``add``).
"""

from __future__ import annotations

from typing import Any

import structlog
import typer

from bsgateway.cli._client import build_client
from bsgateway.cli.commands._common import (
    emit_dry_run,
    emit_http_error,
    parse_json_value,
    run_async,
)

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="tenants",
    help="Manage tenants (list/add/show/update/delete).",
    no_args_is_help=True,
    add_completion=False,
)


def _parse_settings(raw: str) -> dict[str, Any]:
    decoded = parse_json_value(raw, "--settings")
    if not isinstance(decoded, dict):
        raise typer.BadParameter("--settings must decode to a JSON object")
    return decoded


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List tenants.")
def list_cmd(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="Page size."),
    offset: int = typer.Option(0, "--offset", min=0, help="Page offset."),
) -> None:
    obj = ctx.obj
    path = "/tenants"
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


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


@app.command("add", help="Create a new tenant.")
def add_cmd(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Human-readable tenant name."),
    slug: str = typer.Option(..., "--slug", help="URL slug (lowercase, hyphens)."),
    settings: str | None = typer.Option(None, "--settings", help="JSON object of tenant settings."),
) -> None:
    obj = ctx.obj

    body: dict[str, Any] = {
        "name": name,
        "slug": slug,
        "settings": _parse_settings(settings) if settings is not None else {},
    }
    path = "/tenants"

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
# show
# ---------------------------------------------------------------------------


@app.command("show", help="Get a tenant by id.")
def show_cmd(
    ctx: typer.Context,
    tenant_id: str = typer.Argument(..., help="Tenant id (uuid)."),
) -> None:
    obj = ctx.obj
    path = f"/tenants/{tenant_id}"

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
    obj.formatter.emit(resp.json())


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


@app.command("update", help="Patch a tenant (only the fields you pass).")
def update_cmd(
    ctx: typer.Context,
    tenant_id: str = typer.Argument(..., help="Tenant id (uuid)."),
    name: str | None = typer.Option(None, "--name"),
    slug: str | None = typer.Option(None, "--slug"),
    settings: str | None = typer.Option(None, "--settings", help="JSON object replacing settings."),
) -> None:
    obj = ctx.obj

    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if slug is not None:
        body["slug"] = slug
    if settings is not None:
        body["settings"] = _parse_settings(settings)

    if not body:
        raise typer.BadParameter("update needs at least one of --name / --slug / --settings")

    path = f"/tenants/{tenant_id}"

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


@app.command("delete", help="Deactivate a tenant.")
def delete_cmd(
    ctx: typer.Context,
    tenant_id: str = typer.Argument(..., help="Tenant id (uuid)."),
    if_exists: bool = typer.Option(
        False, "--if-exists", help="Treat 404 as success (idempotent delete)."
    ),
) -> None:
    obj = ctx.obj
    path = f"/tenants/{tenant_id}"

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
        obj.formatter.emit({"deleted": False, "id": tenant_id, "reason": "not_found"})
        return
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)
    obj.formatter.emit({"deleted": True, "id": tenant_id})


__all__ = ["app"]
