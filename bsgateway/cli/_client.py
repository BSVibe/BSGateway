"""Thin :class:`bsvibe_cli_base.CliHttpClient` wrapper for BSGateway.

Sub-commands call :func:`build_client` to get an HTTP client configured
from the resolved :class:`bsvibe_cli_base.CliContext`. The wrapper:

* Pulls ``base_url`` from ``ctx.url`` — fails fast with a friendly
  :class:`typer.BadParameter` when it's empty (no implicit fallback so
  AI agents aren't silently pointed at the wrong cluster).
* Forwards ``ctx.token`` as the bearer for the admin REST endpoints.
* Sends ``X-Tenant-ID`` when the tenant is resolved so tenant-scoped
  routes can target the right tenant without per-call wiring.

The 401-refresh-retry path lives in :class:`CliHttpClient` itself —
nothing extra to do here.
"""

from __future__ import annotations

import typer
from bsvibe_cli_base import CliContext, CliHttpClient


def build_client(ctx: CliContext) -> CliHttpClient:
    """Return a :class:`CliHttpClient` configured from ``ctx``."""
    if not ctx.url:
        raise typer.BadParameter(
            "No control-plane URL resolved. Pass --url, set $BSVIBE_URL, or "
            "configure an active profile via `bsgateway profile add`."
        )

    headers: dict[str, str] = {}
    if ctx.tenant_id:
        headers["X-Tenant-ID"] = ctx.tenant_id

    return CliHttpClient(
        base_url=ctx.url,
        token=ctx.token,
        headers=headers or None,
    )


__all__ = ["build_client"]
