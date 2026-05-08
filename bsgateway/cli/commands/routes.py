"""``bsgateway routes`` sub-app — probe routing for a sample prompt.

Wraps ``POST /tenants/{tenant_id}/rules/test`` (the existing rule-test endpoint
in :mod:`bsgateway.api.routers.rules`). The CLI-level command is named
``routes test`` because the operator's mental model is "what route does this
hit", not "which rule matches".

``--profile-context`` accepts a JSON list of additional message dicts that get
prepended to the synthesised user-prompt message — useful for testing routing
behaviour with system prompts or multi-turn context.
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
    name="routes",
    help="Probe routing decisions for a sample prompt.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command("test", help="Resolve which rule + target model would match a prompt.")
def test_cmd(
    ctx: typer.Context,
    prompt: str = typer.Option(..., "--prompt", help="User prompt to test."),
    model: str = typer.Option("auto", "--model", help="Requested model id."),
    profile_context: str | None = typer.Option(
        None,
        "--profile-context",
        help="JSON list of message dicts prepended before the prompt (e.g. system prompt).",
    ),
) -> None:
    obj = ctx.obj
    tenant = require_tenant(obj)

    messages: list[dict[str, Any]] = []
    if profile_context is not None:
        prefix = parse_json_value(profile_context, "--profile-context")
        if not isinstance(prefix, list):
            raise typer.BadParameter("--profile-context must decode to a JSON list of messages")
        messages.extend(prefix)
    messages.append({"role": "user", "content": prompt})

    body = {"messages": messages, "model": model}
    path = f"/tenants/{tenant}/rules/test"

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
