"""TASK-005 — ``bsgateway mcp`` sub-app smoke tests.

Two subcommands:

* ``bsgateway mcp list-tools`` — builds the ToolRegistry locally and
  prints every registered tool name (one per line, or as JSON when
  ``--output json``). No HTTP, no env required.
* ``bsgateway mcp serve [--transport stdio|http]`` — boots the MCP
  server. ``stdio`` reads BSGATEWAY_PAT from env and runs the
  in-process stdio transport. ``http`` prints a hint pointing the
  operator at the running gateway's ``/mcp`` endpoint.

Help-text assertions strip ANSI escapes (Phase 3 lesson).
"""

from __future__ import annotations

import re

from typer.testing import CliRunner


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_mcp_subapp_registered_on_root() -> None:
    from bsgateway.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0, result.output
    out = _strip_ansi(result.output)
    assert "list-tools" in out
    assert "serve" in out


def test_mcp_list_tools_outputs_tool_names() -> None:
    from bsgateway.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["mcp", "list-tools"])
    assert result.exit_code == 0, result.output
    out = _strip_ansi(result.output)
    # Spot-check 4 tools across domain + admin sub-apps.
    for name in (
        "bsgateway_mcp_list_rules",
        "bsgateway_models_list",
        "bsgateway_rules_add",
        "bsgateway_execute",
    ):
        assert name in out, out


def test_mcp_list_tools_table_output_one_per_line() -> None:
    """Non-JSON output prints one tool name per line."""
    from bsgateway.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["--output", "table", "mcp", "list-tools"])
    assert result.exit_code == 0, result.output
    out = _strip_ansi(result.output)
    # one tool per line — no JSON brackets
    assert "[" not in out
    assert "bsgateway_models_list" in out
    # confirm at least the catalog size shows up
    line_count = sum(1 for line in out.splitlines() if line.startswith("bsgateway_"))
    assert line_count >= 39


def test_mcp_serve_invalid_transport_rejected() -> None:
    from bsgateway.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["mcp", "serve", "--transport", "websocket"])
    assert result.exit_code != 0
    out = _strip_ansi(result.output)
    assert "transport" in out.lower()


def test_mcp_serve_stdio_requires_pat(monkeypatch) -> None:
    """``serve --transport stdio`` fails fast when BSGATEWAY_PAT is unset."""
    from bsgateway.cli.main import app

    monkeypatch.delenv("BSGATEWAY_PAT", raising=False)

    runner = CliRunner()
    result = runner.invoke(app, ["mcp", "serve", "--transport", "stdio"])
    assert result.exit_code != 0
    out = _strip_ansi(result.output)
    assert "BSGATEWAY_PAT" in out


def test_mcp_list_tools_json_output() -> None:
    from bsgateway.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["--output", "json", "mcp", "list-tools"])
    assert result.exit_code == 0, result.output
    out = _strip_ansi(result.output)
    # JSON output is a list[str].
    import json

    payload = json.loads(out)
    assert isinstance(payload, list)
    assert "bsgateway_models_list" in payload
    assert len(payload) >= 39


def test_mcp_serve_help_documents_transport_flag() -> None:
    from bsgateway.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["mcp", "serve", "--help"])
    assert result.exit_code == 0, result.output
    out = _strip_ansi(result.output)
    assert "--transport" in out
    assert "stdio" in out
    assert "http" in out


def test_mcp_serve_http_prints_hint_and_exits(monkeypatch) -> None:
    from bsgateway.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["mcp", "serve", "--transport", "http"])
    # The HTTP transport is hosted by the running gateway — the CLI
    # explains where to point clients and exits 0 without binding a
    # port.
    assert result.exit_code == 0, result.output
    out = _strip_ansi(result.output)
    assert "/mcp" in out


def test_mcp_serve_stdio_dry_run_prints_summary() -> None:
    """``--dry-run`` short-circuits before any IO so tests don't hang.

    Mirrors the dry-run convention used across the CLI sub-apps.
    """
    from bsgateway.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["--dry-run", "mcp", "serve", "--transport", "stdio"])
    assert result.exit_code == 0, result.output
    out = _strip_ansi(result.output)
    assert "stdio" in out.lower()
