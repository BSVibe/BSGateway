"""Tests for streaming worker executors (claude / codex / opencode)."""

from __future__ import annotations

import asyncio
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
    _opencode_is_terminal,
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
    def test_message_delta(self) -> None:
        assert _codex_extract_delta({"type": "message_delta", "content": "x"}) == "x"

    def test_assistant_delta(self) -> None:
        assert _codex_extract_delta({"type": "assistant_delta", "text": "y"}) == "y"

    def test_message_final(self) -> None:
        assert _codex_extract_delta({"type": "message", "content": "final"}) == "final"

    def test_unknown_returns_empty(self) -> None:
        assert _codex_extract_delta({"type": "noop"}) == ""


class TestOpencodeExtract:
    def test_message_part_update_with_session_match(self) -> None:
        evt = {
            "type": "message.part.update",
            "properties": {
                "sessionID": "s1",
                "part": {"type": "text", "text": "hi"},
            },
        }
        assert _opencode_extract_delta(evt, "s1") == "hi"

    def test_session_mismatch_drops_event(self) -> None:
        evt = {
            "type": "message.part.update",
            "properties": {"sessionID": "other", "part": {"type": "text", "text": "no"}},
        }
        assert _opencode_extract_delta(evt, "s1") == ""

    def test_terminal_session_idle(self) -> None:
        assert _opencode_is_terminal(
            {"type": "session.idle", "properties": {"sessionID": "s1"}}, "s1"
        )

    def test_terminal_other_session_ignored(self) -> None:
        assert not _opencode_is_terminal(
            {"type": "session.idle", "properties": {"sessionID": "x"}}, "s1"
        )


# ─── ClaudeCodeExecutor — subprocess streaming ───────────────────────


def _make_proc(stdout_lines: list[bytes], stderr_lines: list[bytes] | None = None,
               returncode: int = 0) -> MagicMock:
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
    executor = ClaudeCodeExecutor(timeout_seconds=5, total_timeout_seconds=10,
                                   rate_limit_retries=0)
    line = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
    ).encode() + b"\n"
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
async def test_codex_executor_streams_message_delta() -> None:
    executor = CodexExecutor(timeout_seconds=5)
    line1 = json.dumps({"type": "message_delta", "content": "first "}).encode() + b"\n"
    line2 = json.dumps({"type": "message_delta", "content": "second"}).encode() + b"\n"
    proc = _make_proc([line1, line2], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await collect(executor.execute("p", {"task_id": "t"}))

    assert result.success is True
    assert result.stdout == "first second"


@pytest.mark.asyncio
async def test_codex_executor_writes_system_to_tempfile_and_cleans_up() -> None:
    executor = CodexExecutor(timeout_seconds=5)
    proc = _make_proc([], returncode=0)

    captured_args: list[str] = []
    real_create = asyncio.create_subprocess_exec

    async def _fake_exec(*args, **_kwargs):
        captured_args.extend(args)
        return proc

    with patch("asyncio.create_subprocess_exec", _fake_exec):
        await collect(
            executor.execute("p", {"task_id": "t", "system": "Be helpful and brief."})
        )

    cfg_args = [a for a in captured_args if a.startswith("experimental_instructions_file=")]
    assert len(cfg_args) == 1
    sys_path = cfg_args[0].split("=", 1)[1]
    # Tempfile should be cleaned up after execute() returns.
    import os

    assert not os.path.exists(sys_path)
    _ = real_create  # silence "unused"


# ─── OpenCodeExecutor ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_opencode_executor_streams_sse_events() -> None:
    executor = OpenCodeExecutor()
    executor._cmd = "/bin/true"
    executor._base_url = "http://127.0.0.1:1234"
    executor._proc = MagicMock()
    executor._proc.returncode = None

    sse_events = [
        # session ack (subscribe message)
        "data: " + json.dumps(
            {
                "type": "message.part.update",
                "properties": {"sessionID": "sess-1", "part": {"type": "text", "text": "He"}},
            }
        ),
        "",
        "data: " + json.dumps(
            {
                "type": "message.part.update",
                "properties": {"sessionID": "sess-1", "part": {"type": "text", "text": "llo"}},
            }
        ),
        "",
        "data: " + json.dumps(
            {"type": "session.idle", "properties": {"sessionID": "sess-1"}}
        ),
        "",
    ]

    class _FakeStreamResp:
        def __init__(self) -> None:
            self.status_code = 200

        def raise_for_status(self) -> None:
            pass

        async def aiter_lines(self):
            for line in sse_events:
                yield line

    class _FakeStreamCtx:
        async def __aenter__(self):
            return _FakeStreamResp()

        async def __aexit__(self, *a, **kw):
            return None

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a, **kw):
            return None

        async def post(self, path: str, json: dict[str, Any] | None = None):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value={"id": "sess-1"})
            return resp

        def stream(self, method: str, path: str):
            return _FakeStreamCtx()

    with patch("worker.executors.httpx.AsyncClient", _FakeClient):
        result = await collect(executor.execute("hello", {"task_id": "t"}))

    assert result.success is True
    assert result.stdout == "Hello"


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
