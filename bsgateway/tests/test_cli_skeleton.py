"""TASK-007 — bsgateway CLI skeleton smoke tests.

Asserts that:

* `bsgateway/cli/main.py::app` is a `typer.Typer` produced by
  `bsvibe_cli_base.cli_app` so it inherits the global flag set
  (--profile, --output, --tenant, --token, --url, --dry-run).
* The CLI renders `--help` non-empty and exits 0 (no subcommands
  required at this stage — they land in TASK-008..011).
* `bsgateway/cli/_client.py::build_client` returns a configured
  `CliHttpClient` derived from a `CliContext`, with no network call
  on construction.
* The console-script entry `bsgateway = bsgateway.cli.main:app` is
  declared in pyproject.toml so `uv run bsgateway --help` works.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import typer
from bsvibe_cli_base import CliContext, CliHttpClient, OutputFormatter, ProfileStore
from typer.testing import CliRunner


def test_main_app_is_typer_instance() -> None:
    from bsgateway.cli.main import app

    assert isinstance(app, typer.Typer)
    # cli_app wires no_args_is_help so bare `bsgateway` prints help.
    assert app.info.name == "bsgateway"


def test_help_renders_with_global_flags(tmp_path: Path) -> None:
    from bsgateway.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    out = result.output
    # Sanity — top-level help must surface every global flag from cli_app.
    for flag in ("--profile", "--output", "--tenant", "--token", "--url", "--dry-run"):
        assert flag in out, f"missing global flag {flag} in --help output:\n{out}"


def test_pyproject_declares_console_script() -> None:
    pyproject = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
    parsed = tomllib.loads(pyproject)
    scripts = parsed.get("project", {}).get("scripts", {})
    assert scripts.get("bsgateway") == "bsgateway.cli.main:app", (
        f'expected `bsgateway = "bsgateway.cli.main:app"` in [project.scripts]; got {scripts!r}'
    )


def test_build_client_returns_configured_cli_http_client(tmp_path: Path) -> None:
    from bsgateway.cli._client import build_client

    formatter = OutputFormatter(format="json")
    ctx = CliContext(
        profile=None,
        url="https://gateway.example.test",
        tenant_id="t-123",
        token="bearer-abc",
        dry_run=False,
        formatter=formatter,
        profile_store=ProfileStore(path=tmp_path / "profiles.toml"),
    )
    client = build_client(ctx)
    assert isinstance(client, CliHttpClient)
    # CliHttpClient stores base_url + token internally; verify via the
    # public httpx attribute it exposes.
    assert client._base_url == "https://gateway.example.test"
    assert client._token == "bearer-abc"


def test_build_client_rejects_empty_url(tmp_path: Path) -> None:
    import pytest

    from bsgateway.cli._client import build_client

    formatter = OutputFormatter(format="json")
    ctx = CliContext(
        profile=None,
        url="",
        tenant_id=None,
        token=None,
        dry_run=False,
        formatter=formatter,
        profile_store=ProfileStore(path=tmp_path / "profiles.toml"),
    )
    with pytest.raises(typer.BadParameter):
        build_client(ctx)
