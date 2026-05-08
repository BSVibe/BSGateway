"""``bsgateway usage`` sub-app — wraps ``/tenants/{tenant_id}/usage`` endpoints.

Subcommands: ``report``, ``sparklines``.

Deviation from the literal TASK-010 spec: ``--by tenant|model`` is not
exposed because the backend ``GET /tenants/{tenant_id}/usage`` already
returns ``by_model`` + ``by_rule`` aggregates inline; cross-tenant
aggregation is intentionally not a CLI surface (operators consume that
via the audit log + tenant list).
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
    name="usage",
    help="Usage / cost reports for the active tenant.",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


@app.command("report", help="Aggregate usage report for the active tenant.")
def report_cmd(
    ctx: typer.Context,
    period: str = typer.Option(
        "day", "--period", help="Window: day / week / month (ignored if --from + --to set)."
    ),
    from_date: str | None = typer.Option(
        None, "--from", help="Start date (YYYY-MM-DD, inclusive)."
    ),
    to_date: str | None = typer.Option(None, "--to", help="End date (YYYY-MM-DD, inclusive)."),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)
    path = f"/tenants/{tenant}/usage"

    params: dict[str, Any] = {"period": period}
    if from_date is not None:
        params["from"] = from_date
    if to_date is not None:
        params["to"] = to_date

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
    obj.formatter.emit(resp.json())


# ---------------------------------------------------------------------------
# sparklines
# ---------------------------------------------------------------------------


@app.command("sparklines", help="Per-model daily request counts (sparkline arrays).")
def sparklines_cmd(
    ctx: typer.Context,
    days: int = typer.Option(7, "--days", min=1, max=90, help="Window in days."),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)
    path = f"/tenants/{tenant}/usage/sparklines"
    params = {"days": days}

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
    obj.formatter.emit(resp.json() or {})


__all__ = ["app"]
