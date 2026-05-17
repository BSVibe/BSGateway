"""Tests for streaming worker executors (claude / codex / opencode)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.executors import (
    ClaudeCodeExecutor,
    CodexExecutor,
    ExecutionChunk,
    OpenCodeExecutor,
    _claude_extract_delta,
    _codex_extract_delta,
    _opencode_extract_delta,
    collect,
    create_executor,
)

# ─── Format extractors ───────────────────────────────────────────────


class TestClaudeExtract:
    def test_assistant_text_block(self) -> None:
        evt = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello"}]},
        }
        assert _claude_extract_delta(evt) == "Hello"

    def test_assistant_string_content(self) -> None:
        evt = {"type": "assistant", "message": {"content": "world"}}
        assert _claude_extract_delta(evt) == "world"

    def test_delta_text_fallback(self) -> None:
        evt = {"delta": {"text": "incremental"}}
        assert _claude_extract_delta(evt) == "incremental"

    def test_unknown_event_returns_empty(self) -> None:
        assert _claude_extract_delta({"type": "tool_use"}) == ""


class TestCodexExtract:
    def test_agent_message_item_completed(self) -> None:
        evt = {
            "type": "item.completed",
            "item": {"id": "item_0", "type": "agent_message", "text": "pong"},
        }
        assert _codex_extract_delta(evt) == "pong"

    def test_non_agent_item_returns_empty(self) -> None:
        evt = {
            "type": "item.completed",
            "item": {"id": "item_1", "type": "reasoning", "text": "thinking"},
        }
        assert _codex_extract_delta(evt) == ""

    def test_lifecycle_events_return_empty(self) -> None:
        assert _codex_extract_delta({"type": "thread.started", "thread_id": "x"}) == ""
        assert _codex_extract_delta({"type": "turn.completed", "usage": {}}) == ""

    def test_legacy_message_delta_returns_empty(self) -> None:
        """The old message_delta/message schema is no longer emitted."""
        assert _codex_extract_delta({"type": "message_delta", "content": "x"}) == ""

    def test_unknown_returns_empty(self) -> None:
        assert _codex_extract_delta({"type": "noop"}) == ""


class TestOpencodeExtract:
    def test_text_event_yields_part_text(self) -> None:
        evt = {
            "type": "text",
            "sessionID": "ses_1",
            "part": {"id": "prt_1", "type": "text", "text": "hi"},
        }
        assert _opencode_extract_delta(evt) == "hi"

    def test_step_events_yield_empty(self) -> None:
        assert _opencode_extract_delta({"type": "step_start", "part": {"type": "step-start"}}) == ""
        assert (
            _opencode_extract_delta({"type": "step_finish", "part": {"type": "step-finish"}}) == ""
        )

    def test_unknown_event_yields_empty(self) -> None:
        assert _opencode_extract_delta({"type": "tool", "part": {}}) == ""


# ─── ClaudeCodeExecutor — subprocess streaming ───────────────────────


def _make_proc(
    stdout_lines: list[bytes], stderr_lines: list[bytes] | None = None, returncode: int = 0
) -> MagicMock:
    """Mock asyncio.subprocess.Process with controlled stdout/stderr/returncode."""

    proc = MagicMock()
    proc.returncode = returncode

    out_iter = iter([*stdout_lines, b""])
    err_iter = iter([*(stderr_lines or []), b""])

    async def _readline():
        return next(out_iter)

    proc.stdout = MagicMock()
    proc.stdout.readline = _readline

    async def _read(_n):
        try:
            return next(err_iter)
        except StopIteration:
            return b""

    proc.stderr = MagicMock()
    proc.stderr.read = _read

    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    return proc


@pytest.mark.asyncio
async def test_claude_executor_streams_stdout_lines() -> None:
    executor = ClaudeCodeExecutor(timeout_seconds=5, total_timeout_seconds=10, rate_limit_retries=0)
    line = (
        json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
        ).encode()
        + b"\n"
    )
    proc = _make_proc([line], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await collect(executor.execute("prompt", {"task_id": "t"}))

    assert result.success is True
    assert result.stdout == "hi"


@pytest.mark.asyncio
async def test_claude_executor_appends_system_prompt() -> None:
    executor = ClaudeCodeExecutor(rate_limit_retries=0)
    proc = _make_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await collect(executor.execute("p", {"task_id": "t", "system": "be terse"}))

    args = mock_exec.call_args.args
    assert "--append-system-prompt" in args
    sys_idx = args.index("--append-system-prompt")
    assert args[sys_idx + 1] == "be terse"
    assert "--output-format" in args
    assert "stream-json" in args


@pytest.mark.asyncio
async def test_claude_executor_no_system_omits_flag() -> None:
    executor = ClaudeCodeExecutor(rate_limit_retries=0)
    proc = _make_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await collect(executor.execute("p", {"task_id": "t"}))

    args = mock_exec.call_args.args
    assert "--append-system-prompt" not in args


@pytest.mark.asyncio
async def test_claude_executor_uses_workspace_dir_as_cwd() -> None:
    executor = ClaudeCodeExecutor(rate_limit_retries=0)
    proc = _make_proc([], returncode=0)

    captured: dict[str, Any] = {}

    async def _fake_exec(*args, **kwargs):
        captured["cwd"] = kwargs.get("cwd")
        return proc

    with patch("asyncio.create_subprocess_exec", _fake_exec):
        await collect(executor.execute("p", {"task_id": "t", "workspace_dir": "/abs/ws"}))

    assert captured["cwd"] == "/abs/ws"


@pytest.mark.asyncio
async def test_claude_executor_writes_mcp_config_when_servers_provided() -> None:
    """mcp_servers context → tmpfile JSON + --mcp-config CLI arg."""
    executor = ClaudeCodeExecutor(rate_limit_retries=0)
    proc = _make_proc([], returncode=0)

    mcp_servers = {
        "bsnexus": {
            "url": "http://localhost:8100/mcp/sse?token=run-xyz",
            "headers": {},
        }
    }
    captured_args: list[str] = []
    captured_paths: list[str] = []

    async def _fake_exec(*args, **_kwargs):
        captured_args.extend(args)
        # Read the tmpfile content while the subprocess is "alive".
        if "--mcp-config" in args:
            idx = args.index("--mcp-config")
            path = args[idx + 1]
            captured_paths.append(path)
            with open(path) as f:
                captured_paths.append(f.read())
        return proc

    with patch("asyncio.create_subprocess_exec", _fake_exec):
        await collect(executor.execute("p", {"task_id": "t", "mcp_servers": mcp_servers}))

    assert "--mcp-config" in captured_args
    assert len(captured_paths) == 2  # path + content
    written = json.loads(captured_paths[1])
    # Claude expects an object with `mcpServers` top-level key (camelCase).
    assert written == {"mcpServers": mcp_servers}
    # Tmpfile should be unlinked after exit.
    import os as _os

    assert not _os.path.exists(captured_paths[0])


@pytest.mark.asyncio
async def test_claude_executor_omits_mcp_config_when_servers_empty() -> None:
    """Backward-compat: empty/missing mcp_servers ⇒ no --mcp-config arg."""
    executor = ClaudeCodeExecutor(rate_limit_retries=0)
    proc = _make_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await collect(executor.execute("p", {"task_id": "t"}))

    args = mock_exec.call_args.args
    assert "--mcp-config" not in args


@pytest.mark.asyncio
async def test_claude_executor_unlinks_mcp_tmpfile_on_subprocess_error() -> None:
    """Tmpfile cleanup runs even when subprocess fails."""
    executor = ClaudeCodeExecutor(rate_limit_retries=0)

    captured_paths: list[str] = []

    async def _fake_exec(*args, **_kwargs):
        if "--mcp-config" in args:
            idx = args.index("--mcp-config")
            captured_paths.append(args[idx + 1])
        raise FileNotFoundError("claude not found")

    mcp_servers = {"bsnexus": {"url": "http://x/mcp/sse", "headers": {}}}

    with patch("asyncio.create_subprocess_exec", _fake_exec):
        await collect(executor.execute("p", {"task_id": "t", "mcp_servers": mcp_servers}))

    assert len(captured_paths) == 1
    import os as _os

    assert not _os.path.exists(captured_paths[0])


@pytest.mark.asyncio
async def test_claude_executor_handles_filenotfound() -> None:
    executor = ClaudeCodeExecutor(rate_limit_retries=0)

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(side_effect=FileNotFoundError("claude not found")),
    ):
        result = await collect(executor.execute("p", {"task_id": "t"}))

    assert result.success is False
    assert "claude not found" in (result.error_message or "")


# ─── CodexExecutor ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_codex_executor_streams_agent_message() -> None:
    """codex emits the answer as a completed agent_message item."""
    executor = CodexExecutor(timeout_seconds=5)
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "th-1"}).encode() + b"\n",
        json.dumps({"type": "turn.started"}).encode() + b"\n",
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item_0", "type": "agent_message", "text": "pong"},
            }
        ).encode()
        + b"\n",
        json.dumps({"type": "turn.completed", "usage": {}}).encode() + b"\n",
    ]
    proc = _make_proc(lines, returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await collect(executor.execute("p", {"task_id": "t"}))

    assert result.success is True
    assert result.stdout == "pong"


@pytest.mark.asyncio
async def test_codex_executor_uses_workspace_write_sandbox() -> None:
    """--full-auto is deprecated — the executor uses --sandbox workspace-write."""
    executor = CodexExecutor(timeout_seconds=5)
    proc = _make_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await collect(executor.execute("p", {"task_id": "t"}))

    args = mock_exec.call_args.args
    assert "--sandbox" in args
    assert args[args.index("--sandbox") + 1] == "workspace-write"
    assert "--full-auto" not in args


@pytest.mark.asyncio
async def test_codex_executor_writes_system_to_tempfile_and_cleans_up() -> None:
    executor = CodexExecutor(timeout_seconds=5)
    proc = _make_proc([], returncode=0)

    captured_args: list[str] = []

    async def _fake_exec(*args, **_kwargs):
        captured_args.extend(args)
        return proc

    with patch("asyncio.create_subprocess_exec", _fake_exec):
        await collect(executor.execute("p", {"task_id": "t", "system": "Be helpful and brief."}))

    # codex 0.130+ reads the system override from model_instructions_file —
    # the old experimental_instructions_file key is silently ignored.
    cfg_args = [a for a in captured_args if a.startswith("model_instructions_file=")]
    assert len(cfg_args) == 1
    sys_path = cfg_args[0].split("=", 1)[1]
    import os

    assert not os.path.exists(sys_path)


# ─── model selection (context["model"]) ─────────────────────────────


@pytest.mark.asyncio
async def test_claude_executor_passes_model_flag() -> None:
    executor = ClaudeCodeExecutor(rate_limit_retries=0)
    proc = _make_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await collect(executor.execute("p", {"task_id": "t", "model": "claude-opus-4-7"}))

    args = mock_exec.call_args.args
    assert "--model" in args
    assert args[args.index("--model") + 1] == "claude-opus-4-7"


@pytest.mark.asyncio
async def test_claude_executor_omits_model_flag_when_absent() -> None:
    executor = ClaudeCodeExecutor(rate_limit_retries=0)
    proc = _make_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await collect(executor.execute("p", {"task_id": "t"}))

    assert "--model" not in mock_exec.call_args.args


@pytest.mark.asyncio
async def test_codex_executor_passes_model_flag() -> None:
    executor = CodexExecutor(timeout_seconds=5)
    proc = _make_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await collect(executor.execute("p", {"task_id": "t", "model": "gpt-5-codex"}))

    args = mock_exec.call_args.args
    assert "--model" in args
    assert args[args.index("--model") + 1] == "gpt-5-codex"


@pytest.mark.asyncio
async def test_codex_executor_omits_model_flag_when_absent() -> None:
    executor = CodexExecutor(timeout_seconds=5)
    proc = _make_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await collect(executor.execute("p", {"task_id": "t"}))

    assert "--model" not in mock_exec.call_args.args


# ─── OpenCodeExecutor (opencode run subprocess) ──────────────────────


@pytest.mark.asyncio
async def test_opencode_executor_streams_text_events() -> None:
    """`opencode run --format json` emits step_start → text → step_finish."""
    executor = OpenCodeExecutor(timeout_seconds=5)
    lines = [
        json.dumps({"type": "step_start", "part": {"type": "step-start"}}).encode() + b"\n",
        json.dumps(
            {"type": "text", "sessionID": "ses_1", "part": {"type": "text", "text": "po"}}
        ).encode()
        + b"\n",
        json.dumps(
            {"type": "text", "sessionID": "ses_1", "part": {"type": "text", "text": "ng"}}
        ).encode()
        + b"\n",
        json.dumps(
            {"type": "step_finish", "part": {"type": "step-finish", "reason": "stop"}}
        ).encode()
        + b"\n",
    ]
    proc = _make_proc(lines, returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await collect(executor.execute("p", {"task_id": "t"}))

    assert result.success is True
    assert result.stdout == "pong"


@pytest.mark.asyncio
async def test_opencode_executor_uses_run_format_json_and_dir() -> None:
    executor = OpenCodeExecutor(timeout_seconds=5)
    proc = _make_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await collect(executor.execute("do it", {"task_id": "t", "workspace_dir": "/abs/ws"}))

    args = mock_exec.call_args.args
    assert args[1:4] == ("run", "--format", "json")
    assert "--dir" in args
    assert args[args.index("--dir") + 1] == "/abs/ws"
    # prompt is the trailing positional
    assert args[-1] == "do it"
    assert mock_exec.call_args.kwargs.get("cwd") == "/abs/ws"


@pytest.mark.asyncio
async def test_opencode_executor_passes_model_verbatim() -> None:
    """opencode `run -m` takes the provider/model string as-is."""
    executor = OpenCodeExecutor(timeout_seconds=5)
    proc = _make_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await collect(executor.execute("p", {"task_id": "t", "model": "anthropic/claude-opus-4-7"}))

    args = mock_exec.call_args.args
    assert "-m" in args
    assert args[args.index("-m") + 1] == "anthropic/claude-opus-4-7"


@pytest.mark.asyncio
async def test_opencode_executor_omits_model_when_absent() -> None:
    executor = OpenCodeExecutor(timeout_seconds=5)
    proc = _make_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await collect(executor.execute("p", {"task_id": "t"}))

    assert "-m" not in mock_exec.call_args.args


@pytest.mark.asyncio
async def test_opencode_executor_system_via_config_content() -> None:
    """system ⇒ temp instructions file referenced by OPENCODE_CONFIG_CONTENT."""
    executor = OpenCodeExecutor(timeout_seconds=5)
    proc = _make_proc([], returncode=0)

    captured_env: dict[str, Any] = {}
    captured_inst: list[str] = []

    async def _fake_exec(*_args, **kwargs):
        env = kwargs.get("env") or {}
        captured_env.update(env)
        cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        path = cfg["instructions"][0]
        captured_inst.append(path)
        with open(path) as f:
            captured_inst.append(f.read())
        return proc

    with patch("asyncio.create_subprocess_exec", _fake_exec):
        await collect(executor.execute("p", {"task_id": "t", "system": "be very terse"}))

    assert "OPENCODE_CONFIG_CONTENT" in captured_env
    assert captured_inst[1] == "be very terse"
    # temp instructions file cleaned up after execute() returns
    import os as _os

    assert not _os.path.exists(captured_inst[0])


@pytest.mark.asyncio
async def test_opencode_executor_mcp_via_config_content() -> None:
    """mcp_servers ⇒ opencode `mcp` block (remote servers) in the config."""
    executor = OpenCodeExecutor(timeout_seconds=5)
    proc = _make_proc([], returncode=0)

    captured_cfg: list[dict[str, Any]] = []

    async def _fake_exec(*_args, **kwargs):
        captured_cfg.append(json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"]))
        return proc

    mcp = {"bsnexus": {"url": "http://localhost:8100/mcp?token=t", "headers": {"X-A": "1"}}}
    with patch("asyncio.create_subprocess_exec", _fake_exec):
        await collect(executor.execute("p", {"task_id": "t", "mcp_servers": mcp}))

    assert captured_cfg[0]["mcp"] == {
        "bsnexus": {
            "type": "remote",
            "enabled": True,
            "url": "http://localhost:8100/mcp?token=t",
            "headers": {"X-A": "1"},
        }
    }


@pytest.mark.asyncio
async def test_opencode_executor_no_config_env_when_plain() -> None:
    """No system / no mcp_servers ⇒ OPENCODE_CONFIG_CONTENT absent."""
    executor = OpenCodeExecutor(timeout_seconds=5)
    proc = _make_proc([], returncode=0)

    captured_env: dict[str, Any] = {}

    async def _fake_exec(*_args, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        return proc

    with patch("asyncio.create_subprocess_exec", _fake_exec):
        await collect(executor.execute("p", {"task_id": "t"}))

    assert "OPENCODE_CONFIG_CONTENT" not in captured_env


@pytest.mark.asyncio
async def test_opencode_executor_handles_filenotfound() -> None:
    executor = OpenCodeExecutor(timeout_seconds=5)

    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(side_effect=FileNotFoundError("opencode not found")),
    ):
        result = await collect(executor.execute("p", {"task_id": "t"}))

    assert result.success is False
    assert "opencode not found" in (result.error_message or "")


def test_opencode_mcp_block_shape() -> None:
    from worker.executors import _opencode_mcp_block

    block = _opencode_mcp_block({"a": {"url": "http://x/mcp", "headers": {}}, "bad": "not-a-dict"})
    assert block["a"] == {"type": "remote", "enabled": True, "url": "http://x/mcp"}
    assert "bad" not in block


# ─── factory ─────────────────────────────────────────────────────────


def test_factory_creates_known_executors() -> None:
    assert isinstance(create_executor("claude_code"), ClaudeCodeExecutor)
    assert isinstance(create_executor("codex"), CodexExecutor)
    assert isinstance(create_executor("opencode"), OpenCodeExecutor)


def test_factory_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        create_executor("nope")


# ─── ExecutionChunk dataclass ────────────────────────────────────────


def test_execution_chunk_defaults() -> None:
    c = ExecutionChunk()
    assert c.delta == ""
    assert c.done is False
    assert c.error is None
    assert c.raw is None


@pytest.mark.asyncio
async def test_collect_stops_on_done() -> None:
    async def _gen():
        yield ExecutionChunk(delta="a")
        yield ExecutionChunk(delta="b")
        yield ExecutionChunk(done=True)
        yield ExecutionChunk(delta="c")  # should not be reached

    res = await collect(_gen())
    assert res.stdout == "ab"
    assert res.success is True
