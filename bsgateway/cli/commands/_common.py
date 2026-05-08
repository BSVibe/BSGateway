"""Shared helpers for ``bsgateway`` CLI sub-apps (routes / rules / intents / presets).

Centralises the dry-run renderer, friendly HTTP-error printer, async-runner,
and tenant-resolver so each sub-app focuses on its own request shape rather
than re-deriving these primitives.

``models.py`` (TASK-008) uses its own private copies and is intentionally not
refactored here — that module's tests are stable and the duplication cost is
small.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer

__all__ = [
    "emit_dry_run",
    "emit_http_error",
    "parse_json_value",
    "require_tenant",
    "run_async",
]


def emit_dry_run(ctx_obj: Any, payload: dict[str, Any]) -> None:
    """Render the planned request without firing it."""
    ctx_obj.formatter.emit({"dry_run": True, **payload})


def emit_http_error(resp: Any) -> None:
    """Print a one-line error to stderr — no stack trace."""
    detail: Any
    try:
        body = resp.json()
    except Exception:
        body = None
    if isinstance(body, dict) and "detail" in body:
        detail = body["detail"]
    elif body is not None:
        detail = body
    else:
        detail = (resp.text or "").strip()[:300]
    typer.echo(f"Error: HTTP {resp.status_code} — {detail}", err=True)


def parse_json_value(raw: str, flag: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"{flag} is not valid JSON: {exc}") from exc


def require_tenant(ctx_obj: Any) -> str:
    """Pull tenant_id from CliContext or fail fast."""
    tenant = ctx_obj.tenant_id
    if not tenant:
        raise typer.BadParameter(
            "No tenant resolved. Pass --tenant <uuid>, set $BSVIBE_TENANT, "
            "or configure a profile with a default tenant."
        )
    return tenant


def run_async(coro_factory: Any) -> Any:
    """Run an async coroutine factory (for build_client + aclose pattern)."""
    return asyncio.run(coro_factory())
