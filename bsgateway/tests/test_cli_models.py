"""TASK-008 — ``bsgateway models`` CLI sub-app tests.

Each subcommand is exercised through :class:`typer.testing.CliRunner`
with :func:`bsgateway.cli._client.build_client` monkey-patched to a
``MagicMock``. That keeps the tests focused on:

* command wiring (subcommands are registered + reachable),
* request shape (path / body / params on the mocked client),
* output shape (rendered JSON honours ``--output json``),
* ``--dry-run`` truly skipping HTTP,
* friendly error surface on 4xx (no stack trace, exit code != 0),
* ``--if-exists`` swallowing 404 on delete.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from typer.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ``build_client`` with a mock that records calls."""
    client = MagicMock(name="CliHttpClient")
    client.aclose = AsyncMock(return_value=None)
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.delete = AsyncMock()
    client.request = AsyncMock()  # PATCH path

    monkeypatch.setattr(
        "bsgateway.cli.commands.models.build_client",
        lambda ctx: client,
    )
    return client


def _resp(status_code: int = 200, payload: object | None = None) -> MagicMock:
    """Build a `httpx.Response`-shaped mock with ``.status_code`` + ``.json()``."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.json.return_value = payload
    r.text = json.dumps(payload, default=str) if payload is not None else ""
    return r


def _base_args(*extra: str) -> list[str]:
    return ["--url", "http://gw.test", "--token", "tok", "-o", "json", *extra]


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------


def test_models_subapp_help(runner: CliRunner) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, ["models", "--help"])
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    for sub in ("list", "add", "update", "remove", "show"):
        assert sub in out, f"missing subcommand {sub!r} in models --help:\n{out}"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_emits_json_array(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    fake_client.get.return_value = _resp(
        200,
        [
            {
                "name": "custom/foo",
                "origin": "custom",
                "is_passthrough": True,
                "litellm_model": "ollama_chat/qwen3",
                "has_litellm_params": True,
                "id": "00000000-0000-0000-0000-000000000001",
                "tenant_id": "11111111-1111-1111-1111-111111111111",
            }
        ],
    )
    result = runner.invoke(app, _base_args("models", "list"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_awaited_once_with("/admin/models")
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert payload[0]["name"] == "custom/foo"


def test_list_filters_by_type_custom(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    fake_client.get.return_value = _resp(
        200,
        [
            {
                "name": "system/a",
                "origin": "system",
                "is_passthrough": True,
                "litellm_model": "x",
                "has_litellm_params": False,
                "id": None,
                "tenant_id": None,
            },
            {
                "name": "custom/b",
                "origin": "custom",
                "is_passthrough": True,
                "litellm_model": "y",
                "has_litellm_params": False,
                "id": "33333333-3333-3333-3333-333333333333",
                "tenant_id": "44444444-4444-4444-4444-444444444444",
            },
        ],
    )
    result = runner.invoke(app, _base_args("models", "list", "--type", "custom"))
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["origin"] == "custom"


def test_list_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(
        app, ["--url", "http://gw.test", "--dry-run", "-o", "json", "models", "list"]
    )
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["method"] == "GET"
    assert payload["path"] == "/admin/models"


def test_list_bad_type_value(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, _base_args("models", "list", "--type", "bogus"))
    assert result.exit_code != 0
    fake_client.get.assert_not_awaited()


def test_list_surfaces_http_error_friendly(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    fake_client.get.return_value = _resp(403, {"detail": "scope missing: bsgateway:models:read"})
    result = runner.invoke(app, _base_args("models", "list"))
    assert result.exit_code != 0
    assert "scope missing" in (result.stdout + result.stderr)
    # No stack trace bubbled up.
    assert "Traceback" not in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_show_filters_list_by_id(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    fake_client.get.return_value = _resp(
        200,
        [
            {
                "name": "a",
                "origin": "system",
                "is_passthrough": True,
                "litellm_model": "x",
                "has_litellm_params": False,
                "id": None,
                "tenant_id": None,
            },
            {
                "name": "b",
                "origin": "custom",
                "is_passthrough": True,
                "litellm_model": "y",
                "has_litellm_params": False,
                "id": "33333333-3333-3333-3333-333333333333",
                "tenant_id": "44444444-4444-4444-4444-444444444444",
            },
        ],
    )
    result = runner.invoke(
        app, _base_args("models", "show", "33333333-3333-3333-3333-333333333333")
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["name"] == "b"


def test_show_unknown_id_errors(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    fake_client.get.return_value = _resp(200, [])
    result = runner.invoke(
        app, _base_args("models", "show", "44444444-4444-4444-4444-444444444444")
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def test_add_dry_run_emits_request_body(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(
        app,
        [
            "--url",
            "http://gw.test",
            "--dry-run",
            "-o",
            "json",
            "models",
            "add",
            "--name",
            "custom/foo",
            "--provider",
            "ollama_chat/qwen3:8b",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["method"] == "POST"
    assert payload["path"] == "/admin/models"
    assert payload["body"]["name"] == "custom/foo"
    assert payload["body"]["litellm_model"] == "ollama_chat/qwen3:8b"
    assert payload["body"]["is_passthrough"] is True
    assert payload["body"]["origin"] == "custom"


def test_add_posts_request_with_params(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    fake_client.post.return_value = _resp(
        201,
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "name": "custom/foo",
            "origin": "custom",
            "litellm_model": "ollama_chat/qwen3:8b",
            "has_litellm_params": True,
            "is_passthrough": False,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        },
    )
    result = runner.invoke(
        app,
        _base_args(
            "models",
            "add",
            "--name",
            "custom/foo",
            "--provider",
            "ollama_chat/qwen3:8b",
            "--no-passthrough",
            "--params",
            '{"temperature": 0.2}',
        ),
    )
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_awaited_once()
    args, kwargs = fake_client.post.call_args
    assert args[0] == "/admin/models"
    body = kwargs["json"]
    assert body == {
        "name": "custom/foo",
        "origin": "custom",
        "is_passthrough": False,
        "litellm_model": "ollama_chat/qwen3:8b",
        "litellm_params": {"temperature": 0.2},
    }


def test_add_hide_system_does_not_require_provider(
    runner: CliRunner, fake_client: MagicMock
) -> None:
    from bsgateway.cli.main import app

    fake_client.post.return_value = _resp(
        201,
        {
            "id": "00000000-0000-0000-0000-000000000099",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "name": "gpt-3.5-turbo",
            "origin": "hide_system",
            "litellm_model": None,
            "has_litellm_params": False,
            "is_passthrough": True,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        },
    )
    result = runner.invoke(
        app,
        _base_args(
            "models",
            "add",
            "--name",
            "gpt-3.5-turbo",
            "--origin",
            "hide_system",
        ),
    )
    assert result.exit_code == 0, result.stderr
    body = fake_client.post.call_args.kwargs["json"]
    assert body == {
        "name": "gpt-3.5-turbo",
        "origin": "hide_system",
        "is_passthrough": True,
    }


def test_add_invalid_params_json(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(
        app,
        _base_args(
            "models",
            "add",
            "--name",
            "custom/foo",
            "--provider",
            "ollama_chat/x",
            "--params",
            "not-json",
        ),
    )
    assert result.exit_code != 0
    fake_client.post.assert_not_awaited()


def test_add_surfaces_409_friendly(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    fake_client.post.return_value = _resp(
        409, {"detail": "Model 'custom/foo' already exists for this tenant"}
    )
    result = runner.invoke(
        app,
        _base_args(
            "models",
            "add",
            "--name",
            "custom/foo",
            "--provider",
            "ollama_chat/x",
        ),
    )
    assert result.exit_code != 0
    assert "already exists" in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_patches_only_provided_fields(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    fake_client.request.return_value = _resp(
        200,
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "tenant_id": "22222222-2222-2222-2222-222222222222",
            "name": "renamed",
            "origin": "custom",
            "litellm_model": "x",
            "has_litellm_params": False,
            "is_passthrough": False,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        },
    )
    result = runner.invoke(
        app,
        _base_args(
            "models",
            "update",
            "11111111-1111-1111-1111-111111111111",
            "--name",
            "renamed",
            "--no-passthrough",
        ),
    )
    assert result.exit_code == 0, result.stderr
    fake_client.request.assert_awaited_once()
    args, kwargs = fake_client.request.call_args
    assert args[0] == "PATCH"
    assert args[1] == "/admin/models/11111111-1111-1111-1111-111111111111"
    assert kwargs["json"] == {"name": "renamed", "is_passthrough": False}


def test_update_requires_at_least_one_field(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(
        app,
        _base_args("models", "update", "11111111-1111-1111-1111-111111111111"),
    )
    assert result.exit_code != 0
    fake_client.request.assert_not_awaited()


def test_update_dry_run(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(
        app,
        [
            "--url",
            "http://gw.test",
            "--dry-run",
            "-o",
            "json",
            "models",
            "update",
            "11111111-1111-1111-1111-111111111111",
            "--passthrough",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake_client.request.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["method"] == "PATCH"
    assert payload["body"] == {"is_passthrough": True}


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


def test_remove_calls_delete(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    fake_client.delete.return_value = _resp(204, None)
    result = runner.invoke(
        app,
        _base_args("models", "remove", "22222222-2222-2222-2222-222222222222"),
    )
    assert result.exit_code == 0, result.stderr
    fake_client.delete.assert_awaited_once_with(
        "/admin/models/22222222-2222-2222-2222-222222222222"
    )


def test_remove_404_without_if_exists_errors(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    fake_client.delete.return_value = _resp(404, {"detail": "Model not found"})
    result = runner.invoke(
        app,
        _base_args("models", "remove", "22222222-2222-2222-2222-222222222222"),
    )
    assert result.exit_code != 0
    fake_client.delete.assert_awaited_once()


def test_remove_404_with_if_exists_succeeds(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    fake_client.delete.return_value = _resp(404, {"detail": "Model not found"})
    result = runner.invoke(
        app,
        _base_args(
            "models",
            "remove",
            "22222222-2222-2222-2222-222222222222",
            "--if-exists",
        ),
    )
    assert result.exit_code == 0, result.stderr


def test_remove_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(
        app,
        [
            "--url",
            "http://gw.test",
            "--dry-run",
            "-o",
            "json",
            "models",
            "remove",
            "55555555-5555-5555-5555-555555555555",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake_client.delete.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["method"] == "DELETE"
    assert payload["path"] == "/admin/models/55555555-5555-5555-5555-555555555555"


def test_remove_rejects_empty_string_before_http(runner: CliRunner, fake_client: MagicMock) -> None:
    """Phase 8 dogfood (2026-05-11) finding #9: `models remove ""` used
    to send DELETE /admin/models/, hit FastAPI's redirect_slashes 307,
    and be misinterpreted as success (`{deleted: true, id: ""}`) while
    the row remained. The CLI must reject empty / non-UUID arguments
    at the boundary instead of letting them flow through to the wire."""
    from bsgateway.cli.main import app

    result = runner.invoke(app, _base_args("models", "remove", ""))
    assert result.exit_code != 0
    # CLI must not have even attempted the HTTP call.
    fake_client.delete.assert_not_awaited()


def test_remove_rejects_non_uuid(runner: CliRunner, fake_client: MagicMock) -> None:
    """The argument help says 'uuid'; the implementation enforces it.
    Stops `models remove dogfood-gpt5-mini` from going to the wire and
    producing a confusing 422."""
    from bsgateway.cli.main import app

    result = runner.invoke(app, _base_args("models", "remove", "dogfood-gpt5-mini"))
    assert result.exit_code != 0
    fake_client.delete.assert_not_awaited()


def test_remove_treats_3xx_redirect_as_error(runner: CliRunner, fake_client: MagicMock) -> None:
    """A 3xx response (e.g. FastAPI's redirect_slashes 307) must not
    masquerade as success. With the empty-string guard above this
    shouldn't fire in practice for the CLI, but the same defensive
    check protects against any other path-arity edge that returns a
    3xx."""
    from bsgateway.cli.main import app

    fake_client.delete.return_value = _resp(307, None)
    result = runner.invoke(
        app,
        _base_args("models", "remove", "22222222-2222-2222-2222-222222222222"),
    )
    assert result.exit_code != 0
    fake_client.delete.assert_awaited_once()
