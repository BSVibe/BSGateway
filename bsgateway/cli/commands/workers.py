"""``bsgateway workers`` sub-app — wraps ``/workers``.

Subcommands: ``list``, ``register``, ``revoke``.

The ``workers`` resource is tenant-scoped via the ``X-Tenant-ID`` header
(set by :func:`bsgateway.cli._client.build_client`); the URL path itself
does not carry ``tenant_id``. Every subcommand still requires a resolved
tenant — :func:`require_tenant` surfaces a clear error otherwise.

``register`` requires an install token (``--install-token``) that admins
mint via ``POST /workers/install-token``; the token is sent on the
``X-Install-Token`` header and is *not* echoed in ``--dry-run`` previews.
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
    name="workers",
    help="Manage executor workers (list/register/revoke).",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List workers registered for the active tenant.")
def list_cmd(ctx: typer.Context) -> None:
    obj = ctx.obj
    require_tenant(obj)
    path = "/workers"

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
# register
# ---------------------------------------------------------------------------


@app.command("register", help="Register a new worker (admin smoke test path).")
def register_cmd(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Worker hostname or label."),
    install_token: str = typer.Option(
        ...,
        "--install-token",
        help="Install token minted via POST /workers/install-token.",
    ),
    label: list[str] = typer.Option(
        None, "--label", help="Repeatable label tag (e.g. --label gpu --label x86)."
    ),
    capability: list[str] = typer.Option(
        None,
        "--capability",
        help="Repeatable executor capability (e.g. --capability claude_code).",
    ),
) -> None:
    obj = ctx.obj
    require_tenant(obj)

    body: dict[str, Any] = {
        "name": name,
        "labels": list(label or []),
        "capabilities": list(capability or []),
    }
    path = "/workers/register"

    if obj.dry_run:
        # Never echo the install token in the preview — it grants
        # tenant-scoped registration on disclosure.
        emit_dry_run(obj, {"method": "POST", "path": path, "body": body})
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.post(
                path,
                json=body,
                headers={"X-Install-Token": install_token},
            )
        finally:
            await client.aclose()

    resp = run_async(_go)
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)
    obj.formatter.emit(resp.json())


# ---------------------------------------------------------------------------
# revoke
# ---------------------------------------------------------------------------


@app.command("revoke", help="Deregister a worker by id.")
def revoke_cmd(
    ctx: typer.Context,
    worker_id: str = typer.Argument(..., help="Worker id (uuid)."),
    if_exists: bool = typer.Option(
        False, "--if-exists", help="Treat 404 as success (idempotent revoke)."
    ),
) -> None:
    obj = ctx.obj
    require_tenant(obj)
    path = f"/workers/{worker_id}"

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
        obj.formatter.emit({"revoked": False, "id": worker_id, "reason": "not_found"})
        return
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)
    obj.formatter.emit({"revoked": True, "id": worker_id})


__all__ = ["app"]
