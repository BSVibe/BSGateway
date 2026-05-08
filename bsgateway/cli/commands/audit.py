"""``bsgateway audit`` sub-app — wraps ``/tenants/{tenant_id}/audit``.

Subcommand: ``list``.

Deviation from the literal TASK-010 spec:

* ``show <id>`` is not exposed — the backend ``audit`` router has only a
  paginated list endpoint (no per-id GET). Surfacing a CLI ``show`` would
  require a client-side scan of the list, which is unbounded and a
  footgun against very long audit trails.
* ``--since`` and ``--type`` filters are not exposed — the backend
  repository accepts only ``limit`` / ``offset``. Adding filters here
  would silently drop the predicate and produce a misleading scan.

Both gaps are tracked in ``docs/TODO.md`` and can be added once the
backend grows the corresponding query params.
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
    name="audit",
    help="Query audit logs for the active tenant.",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List audit log entries for the active tenant.")
def list_cmd(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="Page size."),
    offset: int = typer.Option(0, "--offset", min=0, help="Page offset."),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)
    path = f"/tenants/{tenant}/audit"
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
    obj.formatter.emit(resp.json() or {"items": [], "total": 0})


__all__ = ["app"]
