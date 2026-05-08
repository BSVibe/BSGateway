"""``bsgateway execute`` sub-app — submit an executor task and (by default)
poll until terminal status.

Single-action sub-app — invoked as ``bsgateway execute --type X <prompt>``;
no nested subcommands. Maps directly to:

* ``POST /execute`` — create + dispatch a task. Returns ``{task_id, status}``.
* ``GET  /tasks/{id}`` — poll the task. Terminal states: ``done``, ``failed``.

Behavior:

* ``--no-wait``  — emit the dispatch response and exit. No polling.
* default       — poll every :data:`_POLL_INTERVAL_S` seconds until terminal
                  status or ``--timeout`` seconds elapse.
* ``--worker``  — set ``worker_id`` on the request body.

  The current ``ExecuteRequest`` schema does not include ``worker_id`` and
  the backend auto-assigns via ``find_available_worker`` — Pydantic will
  silently drop the extra field. We forward it anyway so the CLI surface is
  ready when the backend adds pinning. (mirrored in docs/TODO.md)

Backend ``status='pending'`` (returned when ``find_available_worker`` finds
no live worker) is treated as a fast failure rather than a poll target —
polling would never observe a transition because nothing was dispatched.
"""

from __future__ import annotations

import asyncio
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

# Module-level so tests can monkeypatch to 0.0 for fast polling without
# touching the public CLI surface.
_POLL_INTERVAL_S: float = 1.0

_TERMINAL_STATES: frozenset[str] = frozenset({"done", "failed"})


app = typer.Typer(
    name="execute",
    help="Submit an executor task and (by default) wait for the result.",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def execute_cmd(
    ctx: typer.Context,
    prompt: str = typer.Argument(None, help="Prompt or instruction to execute."),
    executor_type: str = typer.Option(
        None,
        "--type",
        help="Executor type (claude_code, codex, opencode, ...).",
    ),
    worker_id: str | None = typer.Option(
        None,
        "--worker",
        help="Pin to a specific worker id (forward-compat; backend auto-assigns today).",
    ),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="Poll until task reaches a terminal status (default: wait).",
    ),
    timeout: float = typer.Option(
        300.0,
        "--timeout",
        min=0.0,
        help="Seconds to poll before giving up (only when --wait).",
    ),
) -> None:
    # Sub-app callback also fires for ``execute --help``. When invoked without
    # required args (e.g. just ``bsgateway execute``), Typer shows help via
    # ``no_args_is_help=True``.
    if prompt is None or executor_type is None:
        # Triggered when help/version short-circuit didn't fire but required
        # args are missing. Surface a friendly error.
        if ctx.invoked_subcommand is None and ctx.resilient_parsing is False:
            raise typer.BadParameter("Both --type and PROMPT are required.")
        return

    obj = ctx.obj
    require_tenant(obj)

    body: dict[str, Any] = {"executor_type": executor_type, "prompt": prompt}
    if worker_id:
        body["worker_id"] = worker_id

    if obj.dry_run:
        emit_dry_run(obj, {"method": "POST", "path": "/execute", "body": body})
        return

    async def _submit() -> Any:
        client = build_client(obj)
        try:
            return await client.post("/execute", json=body)
        finally:
            await client.aclose()

    resp = run_async(_submit)
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)

    submit_payload = resp.json() or {}
    task_id = submit_payload.get("task_id")
    submit_status = submit_payload.get("status")

    if not wait:
        obj.formatter.emit(submit_payload)
        return

    if submit_status == "pending":
        # No worker available — find_available_worker returned None. Polling
        # won't help because nothing was dispatched.
        typer.echo(
            f"Error: task {task_id} stayed pending — no worker available for tenant.",
            err=True,
        )
        raise typer.Exit(code=1)

    if not task_id:
        typer.echo("Error: backend did not return a task_id.", err=True)
        raise typer.Exit(code=1)

    final = run_async(lambda: _poll_until_terminal(obj, task_id, timeout))
    if final is None:
        typer.echo(
            f"Error: task {task_id} did not reach a terminal status within {timeout}s (timeout).",
            err=True,
        )
        raise typer.Exit(code=1)

    obj.formatter.emit(final)
    if final.get("status") == "failed":
        raise typer.Exit(code=1)


async def _poll_until_terminal(obj: Any, task_id: str, timeout: float) -> dict[str, Any] | None:
    """Poll ``GET /tasks/{id}`` until terminal status or timeout."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    client = build_client(obj)
    try:
        while True:
            resp = await client.get(f"/tasks/{task_id}")
            if resp.status_code >= 400:
                emit_http_error(resp)
                raise typer.Exit(code=1)
            payload = resp.json() or {}
            status = payload.get("status")
            if status in _TERMINAL_STATES:
                return payload
            if loop.time() >= deadline:
                return None
            await asyncio.sleep(_POLL_INTERVAL_S)
    finally:
        await client.aclose()


__all__ = ["app"]
