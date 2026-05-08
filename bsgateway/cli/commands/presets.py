"""``bsgateway presets`` sub-app — list preset templates and apply them.

Subcommands: ``list`` (no tenant required), ``apply`` (tenant-scoped).

Update / delete are intentionally not exposed: presets in BSGateway are
read-only templates baked into :mod:`bsgateway.presets.registry`. The
backend has no per-tenant preset state to update or delete — applying a
preset materialises rules + intents which are then managed via the
``rules``/``intents`` sub-apps.
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
    name="presets",
    help="List preset templates and apply them to a tenant.",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List available preset templates.")
def list_cmd(ctx: typer.Context) -> None:
    obj = ctx.obj
    path = "/presets"

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
# apply
# ---------------------------------------------------------------------------


@app.command("apply", help="Apply a preset template to the active tenant.")
def apply_cmd(
    ctx: typer.Context,
    preset: str = typer.Option(..., "--preset", help="Preset template name."),
    economy: str = typer.Option(..., "--economy", help="Concrete model for 'economy' tier."),
    balanced: str = typer.Option(..., "--balanced", help="Concrete model for 'balanced' tier."),
    premium: str = typer.Option(..., "--premium", help="Concrete model for 'premium' tier."),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)

    body: dict[str, Any] = {
        "preset_name": preset,
        "model_mapping": {
            "economy": economy,
            "balanced": balanced,
            "premium": premium,
        },
    }
    path = f"/tenants/{tenant}/presets/apply"

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


__all__ = ["app"]
