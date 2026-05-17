"""Tests for ChatService executor path: streaming + system prompt + pubsub completion."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from bsgateway.chat.service import ChatError, ChatService
from bsgateway.rules.models import TenantModel

TENANT_ID = uuid4()
WORKER_ID = uuid4()


def _make_pool_with_task(task_status: str = "done", output: str = "ok") -> tuple:
    """Mock pool whose conn yields task rows for create + get_task."""
    from bsgateway.tests.conftest import make_mock_pool

    pool, conn = make_mock_pool()
    task_row = {
        "id": uuid4(),
        "tenant_id": TENANT_ID,
        "executor_type": "claude_code",
        "prompt": "p",
        "status": task_status,
        "output": output,
        "error_message": None,
    }
    conn.fetchrow = AsyncMock(side_effect=[task_row, {"id": WORKER_ID}, task_row])
    conn.execute = AsyncMock()
    return pool, conn, task_row


def _executor_model() -> TenantModel:
    return TenantModel(
        model_name="my-worker",
        provider="executor",
        litellm_model="executor/claude_code",
        extra_params={"worker_id": str(WORKER_ID), "timeout_seconds": 5},
    )


def _build_svc(pool, redis: AsyncMock | None = None) -> ChatService:
    svc = ChatService(pool, b"\x00" * 32, redis=redis)
    return svc


class TestSystemPromptForwarding:
    @pytest.mark.asyncio
    async def test_system_message_is_passed_to_dispatcher(self) -> None:
        pool, _conn, _row = _make_pool_with_task()
        redis = AsyncMock()
        svc = _build_svc(pool, redis=redis)

        captured: dict[str, Any] = {}

        async def fake_dispatch(
            self,
            worker_id,
            task_id,
            executor_type,
            prompt,
            system="",
            workspace_dir=".",
            mcp_servers=None,
            ai_model=None,
        ):
            captured["system"] = system
            captured["prompt"] = prompt
            return "msg-1"

        async def fake_await(self, task_id, tenant_id, timeout_seconds, poll_interval=None):
            return {"status": "done", "output": "ok", "error_message": None}

        with (
            patch(
                "bsgateway.chat.service.WorkerDispatcher.dispatch_task",
                fake_dispatch,
            ),
            patch.object(svc, "_await_task_completion", new=fake_await.__get__(svc)),
            patch("bsgateway.chat.service._executor_sql") as mock_sql,
        ):
            mock_sql.query.side_effect = lambda q: q

            request = {
                "model": "my-worker",
                "messages": [
                    {"role": "system", "content": "You are concise."},
                    {"role": "user", "content": "hello"},
                ],
            }
            await svc._execute_via_worker(TENANT_ID, request, _executor_model(), None)

        assert captured["system"] == "You are concise."
        assert captured["prompt"] == "hello"


class TestMetadataForwarding:
    """metadata.workspace_dir + metadata.mcp_servers → WorkerDispatcher kwargs."""

    @pytest.mark.asyncio
    async def test_workspace_dir_forwarded_to_dispatcher(self) -> None:
        pool, _conn, _row = _make_pool_with_task()
        redis = AsyncMock()
        svc = _build_svc(pool, redis=redis)

        captured: dict[str, Any] = {}

        async def fake_dispatch(
            self,
            worker_id,
            task_id,
            executor_type,
            prompt,
            system="",
            workspace_dir=".",
            mcp_servers=None,
            ai_model=None,
        ):
            captured["workspace_dir"] = workspace_dir
            return "msg-1"

        async def fake_await(self, task_id, tenant_id, timeout_seconds, poll_interval=None):
            return {"status": "done", "output": "ok", "error_message": None}

        with (
            patch(
                "bsgateway.chat.service.WorkerDispatcher.dispatch_task",
                fake_dispatch,
            ),
            patch.object(svc, "_await_task_completion", new=fake_await.__get__(svc)),
            patch("bsgateway.chat.service._executor_sql") as mock_sql,
        ):
            mock_sql.query.side_effect = lambda q: q

            request = {
                "model": "my-worker",
                "messages": [{"role": "user", "content": "hi"}],
                "metadata": {"workspace_dir": "/abs/ws"},
            }
            await svc._execute_via_worker(TENANT_ID, request, _executor_model(), None)

        assert captured["workspace_dir"] == "/abs/ws"

    @pytest.mark.asyncio
    async def test_mcp_servers_forwarded_to_dispatcher(self) -> None:
        pool, _conn, _row = _make_pool_with_task()
        redis = AsyncMock()
        svc = _build_svc(pool, redis=redis)

        captured: dict[str, Any] = {}

        async def fake_dispatch(
            self,
            worker_id,
            task_id,
            executor_type,
            prompt,
            system="",
            workspace_dir=".",
            mcp_servers=None,
            ai_model=None,
        ):
            captured["mcp_servers"] = mcp_servers
            return "msg-1"

        async def fake_await(self, task_id, tenant_id, timeout_seconds, poll_interval=None):
            return {"status": "done", "output": "ok", "error_message": None}

        mcp = {"bsnexus": {"url": "http://localhost:8100/mcp/sse?token=t", "headers": {}}}

        with (
            patch(
                "bsgateway.chat.service.WorkerDispatcher.dispatch_task",
                fake_dispatch,
            ),
            patch.object(svc, "_await_task_completion", new=fake_await.__get__(svc)),
            patch("bsgateway.chat.service._executor_sql") as mock_sql,
        ):
            mock_sql.query.side_effect = lambda q: q

            request = {
                "model": "my-worker",
                "messages": [{"role": "user", "content": "hi"}],
                "metadata": {"mcp_servers": mcp},
            }
            await svc._execute_via_worker(TENANT_ID, request, _executor_model(), None)

        assert captured["mcp_servers"] == mcp


class TestAiModelForwarding:
    """model.extra_params.ai_model → WorkerDispatcher.dispatch_task kwarg."""

    @pytest.mark.asyncio
    async def test_ai_model_forwarded_to_dispatcher(self) -> None:
        pool, _conn, _row = _make_pool_with_task()
        svc = _build_svc(pool, redis=AsyncMock())

        captured: dict[str, Any] = {}

        async def fake_dispatch(
            self,
            worker_id,
            task_id,
            executor_type,
            prompt,
            system="",
            workspace_dir=".",
            mcp_servers=None,
            ai_model=None,
        ):
            captured["ai_model"] = ai_model
            return "msg-1"

        async def fake_await(self, task_id, tenant_id, timeout_seconds, poll_interval=None):
            return {"status": "done", "output": "ok", "error_message": None}

        pinned_model = TenantModel(
            model_name="codex-opus",
            provider="executor",
            litellm_model="executor/codex",
            extra_params={
                "worker_id": str(WORKER_ID),
                "timeout_seconds": 5,
                "ai_model": "openai/gpt-5-codex",
            },
        )

        with (
            patch("bsgateway.chat.service.WorkerDispatcher.dispatch_task", fake_dispatch),
            patch.object(svc, "_await_task_completion", new=fake_await.__get__(svc)),
            patch("bsgateway.chat.service._executor_sql") as mock_sql,
        ):
            mock_sql.query.side_effect = lambda q: q
            request = {
                "model": "codex-opus",
                "messages": [{"role": "user", "content": "hi"}],
            }
            await svc._execute_via_worker(TENANT_ID, request, pinned_model, None)

        assert captured["ai_model"] == "openai/gpt-5-codex"

    @pytest.mark.asyncio
    async def test_ai_model_absent_dispatches_none(self) -> None:
        """Back-compat: a model without ai_model ⇒ dispatch ai_model=None."""
        pool, _conn, _row = _make_pool_with_task()
        svc = _build_svc(pool, redis=AsyncMock())

        captured: dict[str, Any] = {}

        async def fake_dispatch(
            self,
            worker_id,
            task_id,
            executor_type,
            prompt,
            system="",
            workspace_dir=".",
            mcp_servers=None,
            ai_model=None,
        ):
            captured["ai_model"] = ai_model
            return "msg-1"

        async def fake_await(self, task_id, tenant_id, timeout_seconds, poll_interval=None):
            return {"status": "done", "output": "ok", "error_message": None}

        with (
            patch("bsgateway.chat.service.WorkerDispatcher.dispatch_task", fake_dispatch),
            patch.object(svc, "_await_task_completion", new=fake_await.__get__(svc)),
            patch("bsgateway.chat.service._executor_sql") as mock_sql,
        ):
            mock_sql.query.side_effect = lambda q: q
            request = {
                "model": "my-worker",
                "messages": [{"role": "user", "content": "hi"}],
            }
            await svc._execute_via_worker(TENANT_ID, request, _executor_model(), None)

        assert captured["ai_model"] is None


class TestMetadataExecutorOnlyStrip:
    """B2/B3/S3 from PR #26 review — ``mcp_servers`` and ``workspace_dir``
    must not leak past the executor path. The strip happens in
    ``ChatService.complete`` before LiteLLM kwargs are built. Executor
    path reads them straight from ``request_data.metadata``.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bogus", [["/abs"], {"path": "/x"}, 123, ""])
    async def test_workspace_dir_non_string_rejected(self, bogus) -> None:
        """list / dict / int / empty-string workspace_dir would stringify
        to garbage like ``"['/abs']"`` and surface as opaque
        FileNotFoundError when the worker tries to ``cwd`` into it.
        Default to ``"."`` instead."""
        pool, _conn, _row = _make_pool_with_task()
        redis = AsyncMock()
        svc = _build_svc(pool, redis=redis)

        captured: dict[str, Any] = {}

        async def fake_dispatch(
            self,
            worker_id,
            task_id,
            executor_type,
            prompt,
            system="",
            workspace_dir=".",
            mcp_servers=None,
            ai_model=None,
        ):
            captured["workspace_dir"] = workspace_dir
            return "msg-1"

        async def fake_await(self, task_id, tenant_id, timeout_seconds, poll_interval=None):
            return {"status": "done", "output": "ok", "error_message": None}

        with (
            patch(
                "bsgateway.chat.service.WorkerDispatcher.dispatch_task",
                fake_dispatch,
            ),
            patch.object(svc, "_await_task_completion", new=fake_await.__get__(svc)),
            patch("bsgateway.chat.service._executor_sql") as mock_sql,
        ):
            mock_sql.query.side_effect = lambda q: q

            request = {
                "model": "my-worker",
                "messages": [{"role": "user", "content": "hi"}],
                "metadata": {"workspace_dir": bogus},
            }
            await svc._execute_via_worker(TENANT_ID, request, _executor_model(), None)
            assert captured["workspace_dir"] == ".", f"non-string {bogus!r} leaked"


class TestStreamingResponse:
    @pytest.mark.asyncio
    async def test_chunks_become_openai_chunk_dicts(self) -> None:
        pool, _conn, _row = _make_pool_with_task()
        redis = AsyncMock()
        svc = _build_svc(pool, redis=redis)

        async def fake_dispatch(
            self,
            worker_id,
            task_id,
            executor_type,
            prompt,
            system="",
            workspace_dir=".",
            mcp_servers=None,
            ai_model=None,
        ):
            return "msg-1"

        async def fake_subscribe(channel: str, *, timeout: float):
            async def _gen():
                yield {"delta": "Hello ", "done": False}
                yield {"delta": "world", "done": False}
                yield {"delta": "", "done": True}

            return _gen()

        with (
            patch(
                "bsgateway.chat.service.WorkerDispatcher.dispatch_task",
                fake_dispatch,
            ),
            patch(
                "bsgateway.streams.RedisStreamManager.subscribe_pubsub",
                AsyncMock(side_effect=fake_subscribe),
            ),
            patch("bsgateway.chat.service._executor_sql") as mock_sql,
        ):
            mock_sql.query.side_effect = lambda q: q

            request = {
                "model": "my-worker",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            }
            response = await svc._execute_via_worker(TENANT_ID, request, _executor_model(), None)

            chunks = []
            async for c in response:
                chunks.append(c)

        # First chunk: role marker; then 2 deltas; then final finish_reason.
        assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
        assert chunks[1]["choices"][0]["delta"] == {"content": "Hello "}
        assert chunks[2]["choices"][0]["delta"] == {"content": "world"}
        assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
        assert all(c["object"] == "chat.completion.chunk" for c in chunks)
        assert all(c["model"] == "my-worker" for c in chunks)

    @pytest.mark.asyncio
    async def test_terminal_error_chunk_emits_error_payload(self) -> None:
        pool, _conn, _row = _make_pool_with_task()
        redis = AsyncMock()
        svc = _build_svc(pool, redis=redis)

        async def fake_dispatch(
            self,
            worker_id,
            task_id,
            executor_type,
            prompt,
            system="",
            workspace_dir=".",
            mcp_servers=None,
            ai_model=None,
        ):
            return "msg-1"

        async def fake_subscribe(channel: str, *, timeout: float):
            async def _gen():
                yield {"delta": "partial", "done": False}
                yield {"delta": "", "done": True, "error": "boom"}

            return _gen()

        with (
            patch(
                "bsgateway.chat.service.WorkerDispatcher.dispatch_task",
                fake_dispatch,
            ),
            patch(
                "bsgateway.streams.RedisStreamManager.subscribe_pubsub",
                AsyncMock(side_effect=fake_subscribe),
            ),
            patch("bsgateway.chat.service._executor_sql") as mock_sql,
        ):
            mock_sql.query.side_effect = lambda q: q

            request = {
                "model": "my-worker",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            }
            response = await svc._execute_via_worker(TENANT_ID, request, _executor_model(), None)
            chunks = [c async for c in response]

        # Last entry should carry the error payload.
        error_chunk = chunks[-1]
        assert "error" in error_chunk
        assert error_chunk["error"]["message"] == "boom"


class TestAwaitPubsubCompletion:
    @pytest.mark.asyncio
    async def test_done_signal_returns_db_row(self) -> None:
        from bsgateway.tests.conftest import MockAcquire

        pool = MagicMock()
        conn = AsyncMock()
        conn.transaction = MagicMock()
        pool.acquire.return_value = MockAcquire(conn)
        conn.fetchrow = AsyncMock(
            return_value={"status": "done", "output": "out", "error_message": None}
        )

        async def fake_subscribe(channel: str, *, timeout: float):
            async def _gen():
                yield {"task_id": "t", "success": True}

            return _gen()

        redis = AsyncMock()
        svc = _build_svc(pool, redis=redis)

        with (
            patch(
                "bsgateway.streams.RedisStreamManager.subscribe_pubsub",
                AsyncMock(side_effect=fake_subscribe),
            ),
            patch("bsgateway.chat.service._executor_sql") as mock_sql,
        ):
            mock_sql.query.side_effect = lambda q: q
            row = await svc._await_task_completion(uuid4(), TENANT_ID, timeout_seconds=2)

        assert row["status"] == "done"

    @pytest.mark.asyncio
    async def test_no_signal_within_timeout_raises(self) -> None:
        from bsgateway.tests.conftest import MockAcquire

        pool = MagicMock()
        conn = AsyncMock()
        conn.transaction = MagicMock()
        pool.acquire.return_value = MockAcquire(conn)
        # First (during loop) returns nothing-yet; final fallback also pending.
        conn.fetchrow = AsyncMock(return_value={"status": "pending"})

        async def fake_subscribe(channel: str, *, timeout: float):
            async def _gen():
                if False:
                    yield {}

            return _gen()

        redis = AsyncMock()
        svc = _build_svc(pool, redis=redis)

        with (
            patch(
                "bsgateway.streams.RedisStreamManager.subscribe_pubsub",
                AsyncMock(side_effect=fake_subscribe),
            ),
            patch("bsgateway.chat.service._executor_sql") as mock_sql,
        ):
            mock_sql.query.side_effect = lambda q: q
            with pytest.raises(ChatError, match="timed out"):
                await svc._await_task_completion(uuid4(), TENANT_ID, timeout_seconds=1)

    @pytest.mark.asyncio
    async def test_no_redis_raises(self) -> None:
        pool, _conn, _row = _make_pool_with_task()
        svc = _build_svc(pool, redis=None)

        with pytest.raises(ChatError, match="Redis"):
            await svc._await_task_completion(uuid4(), TENANT_ID, timeout_seconds=1)
