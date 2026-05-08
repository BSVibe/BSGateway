"""``bsgateway models`` sub-app — wraps the ``/admin/models`` REST surface.

Five subcommands:

* ``list``    — GET, with optional ``--type custom|system|all`` client-side filter.
* ``show``    — GET + filter to a single id (the admin REST does not expose a
  per-id GET; we filter the effective list).
* ``add``     — POST a new ``custom`` row or a ``hide_system`` masker.
* ``update``  — PATCH only the fields the operator passed; ``--no-passthrough``
  is preserved through pydantic's exclude_unset because we build the body
  client-side here.
* ``remove``  — DELETE; ``--if-exists`` makes 404 a success (idempotent).

Every subcommand honours the global flags resolved by :func:`bsvibe_cli_base.cli_app`
(``--profile``, ``--output``, ``--tenant``, ``--token``, ``--url``, ``--dry-run``),
which arrive through ``ctx.obj`` as a :class:`bsvibe_cli_base.CliContext`.
``--dry-run`` short-circuits BEFORE :func:`build_client` so the HTTP layer is
never reached — important because AI agents dogfooding this CLI may not have a
control-plane URL configured yet.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
import typer

from bsgateway.cli._client import build_client

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="models",
    help="Manage tenant model registry (list/add/update/remove/show).",
    no_args_is_help=True,
    add_completion=False,
)


_TYPE_FILTER_VALUES: tuple[str, ...] = ("custom", "system", "all")
_VALID_ORIGINS: tuple[str, ...] = ("custom", "hide_system")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _emit_dry_run(ctx_obj: Any, payload: dict[str, Any]) -> None:
    """Render the planned request without firing it. ``payload`` carries
    method/path/body so the AI agent (or operator) can pipe through ``jq``.
    """

    ctx_obj.formatter.emit({"dry_run": True, **payload})


def _emit_http_error(resp: Any) -> None:
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


def _parse_params(raw: str) -> dict[str, Any]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"--params is not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise typer.BadParameter("--params must decode to a JSON object")
    return decoded


def _run(coro_factory: Any) -> Any:
    """Run an async coroutine factory, ensuring ``aclose`` runs."""
    return asyncio.run(coro_factory())


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List effective models (yaml union DB) for the active tenant.")
def list_cmd(
    ctx: typer.Context,
    type_filter: str = typer.Option(
        "all",
        "--type",
        help="Filter by origin: custom | system | all.",
        case_sensitive=False,
    ),
) -> None:
    obj = ctx.obj
    normalised = type_filter.lower()
    if normalised not in _TYPE_FILTER_VALUES:
        raise typer.BadParameter(
            f"--type must be one of {'|'.join(_TYPE_FILTER_VALUES)} (got {type_filter!r})"
        )

    request_repr = {
        "method": "GET",
        "path": "/admin/models",
        "filter": {"type": normalised},
    }
    if obj.dry_run:
        _emit_dry_run(obj, request_repr)
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.get("/admin/models")
        finally:
            await client.aclose()

    resp = _run(_go)
    if resp.status_code >= 400:
        _emit_http_error(resp)
        raise typer.Exit(code=1)

    rows = resp.json() or []
    if normalised != "all":
        rows = [row for row in rows if row.get("origin") == normalised]
    obj.formatter.emit(rows)


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@app.command("show", help="Show one effective model by id.")
def show_cmd(
    ctx: typer.Context,
    model_id: str = typer.Argument(..., help="Model row id (uuid)."),
) -> None:
    obj = ctx.obj
    if obj.dry_run:
        _emit_dry_run(
            obj,
            {"method": "GET", "path": "/admin/models", "filter": {"id": model_id}},
        )
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.get("/admin/models")
        finally:
            await client.aclose()

    resp = _run(_go)
    if resp.status_code >= 400:
        _emit_http_error(resp)
        raise typer.Exit(code=1)

    rows = resp.json() or []
    match = next((r for r in rows if str(r.get("id")) == model_id), None)
    if match is None:
        typer.echo(f"Error: model not found: {model_id}", err=True)
        raise typer.Exit(code=1)
    obj.formatter.emit(match)


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


@app.command("add", help="Add a custom model (or hide a system model).")
def add_cmd(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Model name (e.g. custom/foo)."),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="LiteLLM model id (e.g. ollama_chat/qwen3:8b). Required for origin=custom.",
    ),
    passthrough: bool = typer.Option(
        True,
        "--passthrough/--no-passthrough",
        help="Whether the model is exposed as a passthrough on /v1/chat/completions.",
    ),
    params: str | None = typer.Option(
        None,
        "--params",
        help="JSON object with extra litellm_params (e.g. '{\"temperature\":0.2}').",
    ),
    origin: str = typer.Option(
        "custom",
        "--origin",
        help="Row origin: custom | hide_system.",
        case_sensitive=False,
    ),
) -> None:
    obj = ctx.obj
    origin_v = origin.lower()
    if origin_v not in _VALID_ORIGINS:
        raise typer.BadParameter(f"--origin must be one of {'|'.join(_VALID_ORIGINS)}")

    body: dict[str, Any] = {
        "name": name,
        "origin": origin_v,
        "is_passthrough": passthrough,
    }
    if origin_v == "custom":
        if provider is not None:
            body["litellm_model"] = provider
        if params is not None:
            body["litellm_params"] = _parse_params(params)
    else:
        # hide_system rows must NOT carry litellm payload (the API rejects them).
        if provider is not None or params is not None:
            raise typer.BadParameter(
                "origin=hide_system must not be combined with --provider / --params"
            )

    if obj.dry_run:
        _emit_dry_run(obj, {"method": "POST", "path": "/admin/models", "body": body})
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.post("/admin/models", json=body)
        finally:
            await client.aclose()

    resp = _run(_go)
    if resp.status_code >= 400:
        _emit_http_error(resp)
        raise typer.Exit(code=1)

    obj.formatter.emit(resp.json())


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


@app.command("update", help="Patch a model row (only the fields you pass).")
def update_cmd(
    ctx: typer.Context,
    model_id: str = typer.Argument(..., help="Model row id (uuid)."),
    name: str | None = typer.Option(None, "--name", help="New model name."),
    provider: str | None = typer.Option(None, "--provider", help="New litellm_model."),
    params: str | None = typer.Option(
        None, "--params", help="JSON object replacing litellm_params."
    ),
    passthrough: bool | None = typer.Option(
        None,
        "--passthrough/--no-passthrough",
        help="Toggle passthrough exposure.",
    ),
    origin: str | None = typer.Option(
        None, "--origin", help="custom | hide_system.", case_sensitive=False
    ),
) -> None:
    obj = ctx.obj

    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if provider is not None:
        body["litellm_model"] = provider
    if params is not None:
        body["litellm_params"] = _parse_params(params)
    if passthrough is not None:
        body["is_passthrough"] = passthrough
    if origin is not None:
        ov = origin.lower()
        if ov not in _VALID_ORIGINS:
            raise typer.BadParameter(f"--origin must be one of {'|'.join(_VALID_ORIGINS)}")
        body["origin"] = ov

    if not body:
        raise typer.BadParameter(
            "update needs at least one of --name / --provider / --params / --passthrough / --origin"
        )

    path = f"/admin/models/{model_id}"

    if obj.dry_run:
        _emit_dry_run(obj, {"method": "PATCH", "path": path, "body": body})
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.request("PATCH", path, json=body)
        finally:
            await client.aclose()

    resp = _run(_go)
    if resp.status_code >= 400:
        _emit_http_error(resp)
        raise typer.Exit(code=1)

    obj.formatter.emit(resp.json())


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


@app.command("remove", help="Delete a model row.")
def remove_cmd(
    ctx: typer.Context,
    model_id: str = typer.Argument(..., help="Model row id (uuid)."),
    if_exists: bool = typer.Option(
        False,
        "--if-exists",
        help="Treat 404 as success (idempotent delete).",
    ),
) -> None:
    obj = ctx.obj
    path = f"/admin/models/{model_id}"

    if obj.dry_run:
        _emit_dry_run(obj, {"method": "DELETE", "path": path})
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.delete(path)
        finally:
            await client.aclose()

    resp = _run(_go)
    if resp.status_code == 404 and if_exists:
        obj.formatter.emit({"deleted": False, "id": model_id, "reason": "not_found"})
        return
    if resp.status_code >= 400:
        _emit_http_error(resp)
        raise typer.Exit(code=1)

    obj.formatter.emit({"deleted": True, "id": model_id})


__all__ = ["app"]
