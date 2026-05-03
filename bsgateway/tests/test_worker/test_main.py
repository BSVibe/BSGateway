"""Tests for worker.main — register, _handle_task streaming, capability detection."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from worker.executors import ExecutionChunk

# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def mock_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BSGATEWAY_SERVER_URL", "http://test-server:8000")
    monkeypatch.setenv("BSGATEWAY_WORKER_TOKEN", "")
    monkeypatch.setenv("BSGATEWAY_WORKER_NAME", "test-worker")
    monkeypatch.setenv("BSGATEWAY_POLL_INTERVAL_SECONDS", "1")

    from worker.config import WorkerSettings

    return WorkerSettings()


def _make_streaming_executor(chunks: list[ExecutionChunk]) -> MagicMock:
    """Build an executor whose execute() returns an async iterator of chunks."""

    async def _gen(*_args, **_kwargs):
        for c in chunks:
            yield c

    executor = MagicMock()
    executor.execute = _gen
    return executor


# ─── detect_capabilities ─────────────────────────────────────────────


def test_detect_capabilities_claude_only() -> None:
    from worker.main import detect_capabilities

    def _which(cmd: str) -> str | None:
        return "/usr/bin/claude" if cmd == "claude" else None

    with patch("shutil.which", side_effect=_which):
        caps = detect_capabilities()
    assert caps == ["claude_code"]


def test_detect_capabilities_all_three() -> None:
    from worker.main import detect_capabilities

    with patch("shutil.which", return_value="/usr/bin/x"):
        caps = detect_capabilities()
    assert set(caps) == {"claude_code", "codex", "opencode"}


def test_detect_capabilities_none() -> None:
    from worker.main import detect_capabilities

    with patch("shutil.which", return_value=None):
        caps = detect_capabilities()
    assert caps == []


# ─── register ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_success(tmp_path) -> None:
    from worker.main import register

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "w-1", "token": "tok-new"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        patch("worker.main.detect_capabilities", return_value=["claude_code"]),
        patch("worker.main._update_env_file") as mock_update,
    ):
        await register(
            name="test-worker",
            server_url="http://localhost:8000",
            install_token="fake-install-token",
        )

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert call_args[0][0] == "/api/v1/workers/register"
    body = call_args[1]["json"]
    assert body["name"] == "test-worker"
    assert "claude_code" in body["capabilities"]

    mock_update.assert_called_once()
    env_updates = mock_update.call_args[0][1]
    assert env_updates["BSGATEWAY_WORKER_TOKEN"] == "tok-new"


@pytest.mark.asyncio
async def test_register_with_labels() -> None:
    from worker.main import register

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "w-2", "token": "tok-lab"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        patch("worker.main.detect_capabilities", return_value=[]),
        patch("worker.main._update_env_file"),
    ):
        token = await register("w", "http://x", "install-tok", labels=["env:prod"])

    assert token == "tok-lab"
    body = mock_client.post.call_args[1]["json"]
    assert body["labels"] == ["env:prod"]
    assert body["capabilities"] == ["claude_code"]


# ─── _handle_task: streaming chunks → pubsub + final POST ────────────


@pytest.mark.asyncio
async def test_handle_task_publishes_chunks_and_posts_result() -> None:
    from worker.main import _handle_task

    executor = _make_streaming_executor(
        [
            ExecutionChunk(delta="Hello "),
            ExecutionChunk(delta="world"),
            ExecutionChunk(done=True),
        ]
    )
    executors = {"claude_code": executor}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
    redis = AsyncMock()

    task = {
        "task_id": "t-1",
        "prompt": "say hi",
        "executor_type": "claude_code",
        "stream_channel": "task:t-1:stream",
        "done_channel": "task:t-1:done",
    }
    await _handle_task(task, executors, mock_client, {"X-Worker-Token": "tok"}, redis)

    # 3 chunk publishes + 1 done publish
    assert redis.publish.await_count == 4
    chunk_calls = [c.args for c in redis.publish.await_args_list[:3]]
    assert all(args[0] == "task:t-1:stream" for args in chunk_calls)
    payloads = [json.loads(args[1]) for args in chunk_calls]
    assert payloads[0]["delta"] == "Hello "
    assert payloads[1]["delta"] == "world"
    assert payloads[2]["done"] is True

    done_args = redis.publish.await_args_list[3].args
    assert done_args[0] == "task:t-1:done"
    done_payload = json.loads(done_args[1])
    assert done_payload["task_id"] == "t-1"
    assert done_payload["success"] is True

    report_call = mock_client.post.call_args
    assert report_call[0][0] == "/api/v1/workers/result"
    body = report_call[1]["json"]
    assert body["output"] == "Hello world"
    assert body["success"] is True


@pytest.mark.asyncio
async def test_handle_task_failure_chunk_marks_failed() -> None:
    from worker.main import _handle_task

    executor = _make_streaming_executor(
        [
            ExecutionChunk(delta="partial"),
            ExecutionChunk(done=True, error="boom"),
        ]
    )
    executors = {"claude_code": executor}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
    redis = AsyncMock()

    task = {"task_id": "t-2", "prompt": "x", "executor_type": "claude_code"}
    await _handle_task(task, executors, mock_client, {"X-Worker-Token": "t"}, redis)

    body = mock_client.post.call_args[1]["json"]
    assert body["success"] is False
    assert body["error_message"] == "boom"
    assert body["output"] == "partial"


@pytest.mark.asyncio
async def test_handle_task_no_redis_still_runs() -> None:
    """Worker must still execute and POST result even when Redis is unavailable."""
    from worker.main import _handle_task

    executor = _make_streaming_executor([ExecutionChunk(delta="ok"), ExecutionChunk(done=True)])
    executors = {"claude_code": executor}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))

    task = {"task_id": "t-3", "prompt": "x", "executor_type": "claude_code"}
    await _handle_task(task, executors, mock_client, {"X-Worker-Token": "t"}, None)

    body = mock_client.post.call_args[1]["json"]
    assert body["success"] is True
    assert body["output"] == "ok"


@pytest.mark.asyncio
async def test_handle_task_passes_system_prompt_in_context() -> None:
    from worker.main import _handle_task

    captured: dict = {}

    async def _gen(prompt, context):
        captured["prompt"] = prompt
        captured["context"] = context
        yield ExecutionChunk(done=True)

    executor = MagicMock()
    executor.execute = _gen
    executors = {"claude_code": executor}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))

    task = {
        "task_id": "t-4",
        "prompt": "do",
        "executor_type": "claude_code",
        "system": "You are terse.",
    }
    await _handle_task(task, executors, mock_client, {"X-Worker-Token": "t"}, None)

    assert captured["prompt"] == "do"
    assert captured["context"]["system"] == "You are terse."


@pytest.mark.asyncio
async def test_handle_task_falls_back_to_title() -> None:
    from worker.main import _handle_task

    captured: dict = {}

    async def _gen(prompt, _ctx):
        captured["prompt"] = prompt
        yield ExecutionChunk(done=True)

    executor = MagicMock()
    executor.execute = _gen
    executors = {"claude_code": executor}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))

    task = {"task_id": "t-5", "title": "title fallback", "executor_type": "claude_code"}
    await _handle_task(task, executors, mock_client, {"X-Worker-Token": "t"}, None)

    assert captured["prompt"] == "title fallback"


# ─── _update_env_file ────────────────────────────────────────────────


def test_update_env_file_creates(tmp_path) -> None:
    from worker.main import _update_env_file

    env_path = tmp_path / ".env"
    _update_env_file(str(env_path), {"KEY": "val"})
    assert "KEY=val" in env_path.read_text()


def test_update_env_file_updates_existing(tmp_path) -> None:
    from worker.main import _update_env_file

    env_path = tmp_path / ".env"
    env_path.write_text("A=1\nB=2\n")
    _update_env_file(str(env_path), {"B": "3", "C": "4"})
    content = env_path.read_text()
    assert "A=1" in content
    assert "B=3" in content
    assert "C=4" in content
    assert "B=2" not in content


# ─── select_executor ─────────────────────────────────────────────────


def test_select_executor_claude() -> None:
    from worker.executors import ClaudeCodeExecutor
    from worker.main import select_executor

    assert isinstance(select_executor("claude_code"), ClaudeCodeExecutor)


def test_select_executor_codex() -> None:
    from worker.executors import CodexExecutor
    from worker.main import select_executor

    assert isinstance(select_executor("codex"), CodexExecutor)


def test_select_executor_opencode() -> None:
    from worker.executors import OpenCodeExecutor
    from worker.main import select_executor

    assert isinstance(select_executor("opencode"), OpenCodeExecutor)


def test_select_executor_unknown() -> None:
    from worker.main import select_executor

    with pytest.raises(ValueError, match="Unknown executor"):
        select_executor("nonexistent")


# ─── poll_and_execute loop ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_and_execute_registers_when_no_token(monkeypatch) -> None:
    from worker import main as worker_main

    monkeypatch.setattr(worker_main.settings, "worker_token", "")
    monkeypatch.setattr(worker_main.settings, "worker_name", "test")
    monkeypatch.setattr(worker_main.settings, "server_url", "http://localhost")
    monkeypatch.setattr(worker_main.settings, "poll_interval_seconds", 1)

    register_mock = AsyncMock(return_value="new-token")
    monkeypatch.setattr(worker_main, "register", register_mock)
    monkeypatch.setattr(worker_main, "detect_capabilities", lambda: ["claude_code"])
    monkeypatch.setattr(worker_main, "_connect_redis", lambda: None)

    mock_executor = MagicMock()
    monkeypatch.setattr(worker_main, "select_executor", lambda *a, **kw: mock_executor)

    poll_response = MagicMock()
    poll_response.json.return_value = []
    poll_response.raise_for_status = MagicMock()

    call_count = 0

    async def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count > 2:
            raise KeyboardInterrupt
        return poll_response

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(KeyboardInterrupt):
            await worker_main.poll_and_execute()

    register_mock.assert_called_once_with("test", "http://localhost", "")


@pytest.mark.asyncio
async def test_poll_and_execute_dispatches_tasks(monkeypatch) -> None:
    from worker import main as worker_main

    monkeypatch.setattr(worker_main.settings, "worker_token", "tok-ok")
    monkeypatch.setattr(worker_main.settings, "poll_interval_seconds", 0)
    monkeypatch.setattr(worker_main.settings, "max_parallel_tasks", 5)
    monkeypatch.setattr(worker_main, "detect_capabilities", lambda: ["claude_code"])
    monkeypatch.setattr(worker_main, "_connect_redis", lambda: None)

    execute_called = asyncio.Event()

    async def fake_execute(prompt, context):
        execute_called.set()
        yield ExecutionChunk(delta="ok")
        yield ExecutionChunk(done=True)

    mock_executor = MagicMock()
    mock_executor.execute = fake_execute
    monkeypatch.setattr(worker_main, "select_executor", lambda *a, **kw: mock_executor)

    poll_count = 0

    async def mock_post(url, **kwargs):
        nonlocal poll_count
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "/poll" in url:
            poll_count += 1
            if poll_count == 1:
                resp.json.return_value = [
                    {"task_id": "t-1", "prompt": "hi", "executor_type": "claude_code"}
                ]
            else:
                await asyncio.sleep(0.05)
                raise KeyboardInterrupt
        else:
            resp.json.return_value = {}
        return resp

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(KeyboardInterrupt):
            await worker_main.poll_and_execute()

    assert execute_called.is_set()


@pytest.mark.asyncio
async def test_poll_and_execute_handles_connect_error(monkeypatch) -> None:
    from worker import main as worker_main

    monkeypatch.setattr(worker_main.settings, "worker_token", "tok-ok")
    monkeypatch.setattr(worker_main.settings, "poll_interval_seconds", 0)
    monkeypatch.setattr(worker_main, "detect_capabilities", lambda: ["claude_code"])
    monkeypatch.setattr(worker_main, "select_executor", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(worker_main, "_connect_redis", lambda: None)

    call_count = 0

    async def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectError("refused")
        raise KeyboardInterrupt

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(KeyboardInterrupt):
            await worker_main.poll_and_execute()

    assert call_count >= 2


@pytest.mark.asyncio
async def test_poll_and_execute_401_exits(monkeypatch) -> None:
    from worker import main as worker_main

    monkeypatch.setattr(worker_main.settings, "worker_token", "bad-tok")
    monkeypatch.setattr(worker_main.settings, "poll_interval_seconds", 0)
    monkeypatch.setattr(worker_main, "detect_capabilities", lambda: ["claude_code"])
    monkeypatch.setattr(worker_main, "select_executor", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(worker_main, "_connect_redis", lambda: None)

    async def mock_post(url, **kwargs):
        resp = httpx.Response(401, request=httpx.Request("POST", url))
        raise httpx.HTTPStatusError("401", request=resp.request, response=resp)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(SystemExit) as exc_info:
            await worker_main.poll_and_execute()
    assert exc_info.value.code == 1
