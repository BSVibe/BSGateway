"""Worker dispatcher — Redis Streams based task dispatch to remote workers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from bsgateway.streams import RedisStreamManager

logger = structlog.get_logger(__name__)

WORKER_STREAM_PREFIX = "tasks:worker:"


def stream_channel(task_id: UUID) -> str:
    """Pub/sub channel the worker publishes incremental output chunks to."""
    return f"task:{task_id}:stream"


def done_channel(task_id: UUID) -> str:
    """Pub/sub channel the worker publishes the terminal completion signal to."""
    return f"task:{task_id}:done"


class WorkerDispatcher:
    """Dispatches executor tasks to remote workers via Redis Streams."""

    def __init__(self, stream_manager: RedisStreamManager) -> None:
        self._stream = stream_manager

    def _worker_stream(self, worker_id: UUID) -> str:
        return f"{WORKER_STREAM_PREFIX}{worker_id}"

    async def dispatch_task(
        self,
        worker_id: UUID,
        task_id: UUID,
        executor_type: str,
        prompt: str,
        system: str = "",
        workspace_dir: str = ".",
        mcp_servers: dict[str, Any] | None = None,
        ai_model: str | None = None,
    ) -> str:
        """Publish a task to a worker's dedicated stream.

        ``system`` is forwarded as-is to the worker so the executor can
        inject it via the CLI's native flag (``--append-system-prompt``,
        ``--config experimental_instructions_file=...``, or opencode
        session ``system`` field). The worker harness itself (CLAUDE.md,
        settings.json, hooks) is NOT shipped — the worker uses its
        local install.

        ``workspace_dir`` is the absolute filesystem path the executor
        will ``cwd`` into. Defaults to ``"."`` for back-compat with
        callers that don't yet plumb the wire.

        ``mcp_servers`` is the BSNexus-style MCP server dict
        (``{name: {url, headers}}``). The worker writes it to a chmod
        0600 tempfile and passes ``--mcp-config <path>`` to claude CLI.
        Empty / None ⇒ no ``--mcp-config`` injection (back-compat).
        Serialised as a JSON string here because Redis Streams only
        accept flat string fields.

        ``ai_model`` is the LLM model the executor CLI should run with
        (e.g. ``claude-opus-4-7``, ``openai/gpt-5-codex``). It comes from
        the routed model's ``extra_params.ai_model``. ``None`` ⇒ the
        field is omitted and the CLI uses its local default (back-compat).
        """
        data = {
            "task_id": str(task_id),
            "executor_type": executor_type,
            "prompt": prompt,
            "system": system,
            "workspace_dir": workspace_dir,
            "mcp_servers": json.dumps(mcp_servers or {}),
            "stream_channel": stream_channel(task_id),
            "done_channel": done_channel(task_id),
            "action": "execute",
            "dispatched_at": datetime.now(UTC).isoformat(),
        }
        # Redis Stream fields must be flat strings — only include the
        # model when set so an older worker / absent value stays clean.
        if ai_model:
            data["ai_model"] = ai_model
        msg_id = await self._stream.publish(self._worker_stream(worker_id), data)
        logger.info(
            "task_dispatched",
            worker_id=str(worker_id),
            task_id=str(task_id),
            executor_type=executor_type,
        )
        return msg_id
