"""Tests for WorkerDispatcher: task dispatch via Redis Streams."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from bsgateway.executor.dispatcher import WORKER_STREAM_PREFIX, WorkerDispatcher
from bsgateway.streams import RedisStreamManager


@pytest.fixture
def mock_stream_manager() -> AsyncMock:
    sm = AsyncMock(spec=RedisStreamManager)
    sm.publish.return_value = "msg-001"
    return sm


@pytest.fixture
def dispatcher(mock_stream_manager: AsyncMock) -> WorkerDispatcher:
    return WorkerDispatcher(mock_stream_manager)


class TestDispatchTask:
    async def test_publishes_to_correct_stream(
        self, dispatcher: WorkerDispatcher, mock_stream_manager: AsyncMock
    ) -> None:
        worker_id = uuid4()
        task_id = uuid4()

        await dispatcher.dispatch_task(
            worker_id=worker_id,
            task_id=task_id,
            executor_type="claude_code",
            prompt="Write tests",
        )

        expected_stream = f"{WORKER_STREAM_PREFIX}{worker_id}"
        call_args = mock_stream_manager.publish.call_args
        assert call_args[0][0] == expected_stream

    async def test_includes_required_fields(
        self, dispatcher: WorkerDispatcher, mock_stream_manager: AsyncMock
    ) -> None:
        worker_id = uuid4()
        task_id = uuid4()

        await dispatcher.dispatch_task(
            worker_id=worker_id,
            task_id=task_id,
            executor_type="codex",
            prompt="Fix bug",
            system="be terse",
        )

        data = mock_stream_manager.publish.call_args[0][1]
        assert data["task_id"] == str(task_id)
        assert data["executor_type"] == "codex"
        assert data["prompt"] == "Fix bug"
        assert data["action"] == "execute"
        assert "dispatched_at" in data
        assert data["system"] == "be terse"
        assert data["stream_channel"] == f"task:{task_id}:stream"
        assert data["done_channel"] == f"task:{task_id}:done"

    async def test_system_defaults_to_empty(
        self, dispatcher: WorkerDispatcher, mock_stream_manager: AsyncMock
    ) -> None:
        await dispatcher.dispatch_task(
            worker_id=uuid4(),
            task_id=uuid4(),
            executor_type="claude_code",
            prompt="hi",
        )
        data = mock_stream_manager.publish.call_args[0][1]
        assert data["system"] == ""

    async def test_returns_message_id(
        self, dispatcher: WorkerDispatcher, mock_stream_manager: AsyncMock
    ) -> None:
        msg_id = await dispatcher.dispatch_task(
            worker_id=uuid4(),
            task_id=uuid4(),
            executor_type="claude_code",
            prompt="hello",
        )

        assert msg_id == "msg-001"

    async def test_includes_workspace_dir_in_payload(
        self, dispatcher: WorkerDispatcher, mock_stream_manager: AsyncMock
    ) -> None:
        await dispatcher.dispatch_task(
            worker_id=uuid4(),
            task_id=uuid4(),
            executor_type="claude_code",
            prompt="hi",
            workspace_dir="/abs/path/to/workspace",
        )
        data = mock_stream_manager.publish.call_args[0][1]
        assert data["workspace_dir"] == "/abs/path/to/workspace"

    async def test_workspace_dir_defaults_to_dot(
        self, dispatcher: WorkerDispatcher, mock_stream_manager: AsyncMock
    ) -> None:
        await dispatcher.dispatch_task(
            worker_id=uuid4(),
            task_id=uuid4(),
            executor_type="claude_code",
            prompt="hi",
        )
        data = mock_stream_manager.publish.call_args[0][1]
        assert data["workspace_dir"] == "."

    async def test_includes_mcp_servers_in_payload(
        self, dispatcher: WorkerDispatcher, mock_stream_manager: AsyncMock
    ) -> None:
        mcp = {
            "bsnexus": {
                "url": "http://localhost:8100/mcp/sse?token=xyz",
                "headers": {},
            }
        }
        await dispatcher.dispatch_task(
            worker_id=uuid4(),
            task_id=uuid4(),
            executor_type="claude_code",
            prompt="hi",
            mcp_servers=mcp,
        )
        data = mock_stream_manager.publish.call_args[0][1]
        # Stored as JSON string for Redis Stream compatibility (no nested dicts).
        import json as _json

        assert _json.loads(data["mcp_servers"]) == mcp

    async def test_mcp_servers_defaults_to_empty(
        self, dispatcher: WorkerDispatcher, mock_stream_manager: AsyncMock
    ) -> None:
        await dispatcher.dispatch_task(
            worker_id=uuid4(),
            task_id=uuid4(),
            executor_type="claude_code",
            prompt="hi",
        )
        data = mock_stream_manager.publish.call_args[0][1]
        import json as _json

        assert _json.loads(data["mcp_servers"]) == {}

    async def test_includes_ai_model_when_set(
        self, dispatcher: WorkerDispatcher, mock_stream_manager: AsyncMock
    ) -> None:
        await dispatcher.dispatch_task(
            worker_id=uuid4(),
            task_id=uuid4(),
            executor_type="codex",
            prompt="hi",
            ai_model="openai/gpt-5-codex",
        )
        data = mock_stream_manager.publish.call_args[0][1]
        assert data["ai_model"] == "openai/gpt-5-codex"

    async def test_omits_ai_model_when_none(
        self, dispatcher: WorkerDispatcher, mock_stream_manager: AsyncMock
    ) -> None:
        """Redis Stream fields must be flat strings — None is dropped entirely."""
        await dispatcher.dispatch_task(
            worker_id=uuid4(),
            task_id=uuid4(),
            executor_type="claude_code",
            prompt="hi",
        )
        data = mock_stream_manager.publish.call_args[0][1]
        assert "ai_model" not in data
