"""``bsgateway rules`` sub-app — wraps ``/tenants/{tenant_id}/rules`` CRUD.

Subcommands: ``list``, ``add``, ``update``, ``delete``.

Conditions are passed as ``--conditions <JSON>`` (a JSON list of condition
dicts matching :class:`bsgateway.rules.schemas.ConditionSchema`). The CLI does
not introspect that shape — the backend validates it on POST/PATCH and
surfaces 422 with a friendly message.
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
    require_tenant,
    run_async,
)

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="rules",
    help="Manage routing rules (list/add/update/delete).",
    no_args_is_help=True,
    add_completion=False,
)


def _parse_conditions(raw: str) -> list[dict[str, Any]]:
    decoded = parse_json_value(raw, "--conditions")
    if not isinstance(decoded, list):
        raise typer.BadParameter("--conditions must decode to a JSON list of condition dicts")
    return decoded


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List rules for the active tenant.")
def list_cmd(ctx: typer.Context) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)
    path = f"/tenants/{tenant}/rules"

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


@app.command("add", help="Create a new routing rule.")
def add_cmd(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Rule name."),
    priority: int = typer.Option(..., "--priority", help="Lower = higher priority."),
    target_model: str = typer.Option(..., "--target-model", help="Resolved model id."),
    is_default: bool = typer.Option(
        False, "--default/--no-default", help="Mark as the tenant default rule."
    ),
    conditions: str | None = typer.Option(
        None, "--conditions", help="JSON list of condition dicts."
    ),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)

    body: dict[str, Any] = {
        "name": name,
        "priority": priority,
        "target_model": target_model,
        "is_default": is_default,
        "conditions": _parse_conditions(conditions) if conditions is not None else [],
    }
    path = f"/tenants/{tenant}/rules"

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


@app.command("update", help="Patch a rule (only the fields you pass).")
def update_cmd(
    ctx: typer.Context,
    rule_id: str = typer.Argument(..., help="Rule id (uuid)."),
    name: str | None = typer.Option(None, "--name"),
    priority: int | None = typer.Option(None, "--priority"),
    target_model: str | None = typer.Option(None, "--target-model"),
    is_default: bool | None = typer.Option(None, "--default/--no-default"),
    conditions: str | None = typer.Option(
        None, "--conditions", help="JSON list replacing conditions."
    ),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)

    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if priority is not None:
        body["priority"] = priority
    if target_model is not None:
        body["target_model"] = target_model
    if is_default is not None:
        body["is_default"] = is_default
    if conditions is not None:
        body["conditions"] = _parse_conditions(conditions)

    if not body:
        raise typer.BadParameter(
            "update needs at least one of --name / --priority / --target-model "
            "/ --default / --conditions"
        )

    path = f"/tenants/{tenant}/rules/{rule_id}"

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


@app.command("delete", help="Delete a rule.")
def delete_cmd(
    ctx: typer.Context,
    rule_id: str = typer.Argument(..., help="Rule id (uuid)."),
    if_exists: bool = typer.Option(
        False, "--if-exists", help="Treat 404 as success (idempotent delete)."
    ),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)
    path = f"/tenants/{tenant}/rules/{rule_id}"

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
        obj.formatter.emit({"deleted": False, "id": rule_id, "reason": "not_found"})
        return
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)
    obj.formatter.emit({"deleted": True, "id": rule_id})


__all__ = ["app"]
