"""BSGateway Worker — polls for tasks, executes via CLI executors, reports results.

Each task's chunked output is also published to a Redis pub/sub channel
(``task:{id}:stream``) so the gateway can forward incremental SSE chunks
to the client. A terminal ``task:{id}:done`` publish lets the gateway
exit its non-streaming await loop without polling the database.

Usage:
    python -m worker
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from worker.config import settings
from worker.executors import (
    ExecutionChunk,
    ExecutionResult,
    ExecutorProtocol,
    create_executor,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


# ─── Capabilities ────────────────────────────────────────────────────


def detect_capabilities() -> list[str]:
    """Detect which CLI executors are available on this machine."""
    caps: list[str] = []
    if shutil.which("claude"):
        caps.append("claude_code")
    if shutil.which("codex"):
        caps.append("codex")
    if shutil.which("opencode"):
        caps.append("opencode")
    return caps


# ─── Executor selection ──────────────────────────────────────────────


def select_executor(executor_type: str) -> ExecutorProtocol:
    """Create an executor instance by type. Raises ValueError if unknown."""
    return create_executor(executor_type)


# ─── Registration ────────────────────────────────────────────────────


async def register(
    name: str,
    server_url: str,
    install_token: str,
    labels: list[str] | None = None,
) -> str:
    """Register this worker with the BSGateway server.

    ``install_token`` is minted by an admin via the gateway UI
    (Models → Install Worker → Generate Token). Used only once — the
    returned worker token is persisted to ``.env`` for subsequent runs.

    Returns the worker token.
    """
    if not install_token:
        raise ValueError(
            "install_token is required for first-time registration. "
            "Set BSGATEWAY_INSTALL_TOKEN to a token minted via the gateway UI."
        )

    capabilities = detect_capabilities()
    if not capabilities:
        capabilities = ["claude_code"]

    async with httpx.AsyncClient(base_url=server_url, timeout=30) as client:
        payload: dict[str, Any] = {
            "name": name,
            "capabilities": capabilities,
        }
        if labels:
            payload["labels"] = labels

        res = await client.post(
            "/api/v1/workers/register",
            json=payload,
            headers={"X-Install-Token": install_token},
        )
        res.raise_for_status()
        data = res.json()

    token = data["token"]
    worker_id = data["id"]

    _update_env_file(
        ".env",
        {
            "BSGATEWAY_WORKER_TOKEN": token,
            "BSGATEWAY_WORKER_NAME": name,
            "BSGATEWAY_SERVER_URL": server_url,
        },
    )

    logger.info(
        "worker_registered",
        worker_id=worker_id,
        name=name,
        capabilities=capabilities,
    )
    return token


# ─── Task handling ───────────────────────────────────────────────────


async def _handle_task(
    task: dict[str, Any],
    executors: dict[str, ExecutorProtocol],
    client: httpx.AsyncClient,
    headers: dict[str, str],
    redis: Redis | None,
) -> None:
    """Execute a single task and report the result + stream chunks."""
    task_id = task["task_id"]
    prompt = task.get("prompt") or task.get("title", "")
    executor_type = task.get("executor_type", "claude_code")
    # mcp_servers is forwarded as a JSON string by the dispatcher so the
    # Redis Stream payload stays flat. Workers without the new wire (older
    # gateway) won't include it — fall back to empty dict.
    raw_mcp = task.get("mcp_servers")
    mcp_servers: dict[str, Any] = {}
    if raw_mcp:
        if isinstance(raw_mcp, str):
            try:
                parsed = json.loads(raw_mcp)
                if isinstance(parsed, dict):
                    mcp_servers = parsed
            except (json.JSONDecodeError, ValueError):
                logger.warning("mcp_servers_parse_failed", task_id=task_id)
        elif isinstance(raw_mcp, dict):
            mcp_servers = raw_mcp
    context: dict[str, Any] = {
        "task_id": task_id,
        "workspace_dir": task.get("workspace_dir", "."),
        "system": task.get("system") or "",
        "mcp_servers": mcp_servers,
        # The LLM model the executor CLI should run with. Absent for an
        # older gateway ⇒ None ⇒ the CLI uses its local default.
        "model": task.get("ai_model") or None,
    }
    stream_channel = task.get("stream_channel") or f"task:{task_id}:stream"
    done_channel = task.get("done_channel") or f"task:{task_id}:done"

    logger.info("task_received", task_id=task_id, executor=executor_type)

    executor = executors.get(executor_type) or select_executor(executor_type)
    executors[executor_type] = executor

    parts: list[str] = []
    error: str | None = None
    success = True
    final_chunk: ExecutionChunk | None = None
    stream = executor.execute(prompt, context)
    try:
        async for chunk in stream:
            if chunk.delta:
                parts.append(chunk.delta)
            if chunk.error:
                error = chunk.error
                success = False
            if redis is not None:
                await _publish(
                    redis,
                    stream_channel,
                    {"delta": chunk.delta, "done": chunk.done, "error": chunk.error},
                )
            if chunk.done:
                final_chunk = chunk
                break
    except Exception as exc:  # pragma: no cover — defensive
        error = str(exc)
        success = False
        if redis is not None:
            await _publish(
                redis,
                stream_channel,
                {"delta": "", "done": True, "error": error},
            )
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                pass

    result = ExecutionResult(
        success=success,
        stdout="".join(parts),
        error_message=error,
        error_category="" if success else ("environment" if final_chunk is None else "tool"),
    )

    await client.post(
        "/api/v1/workers/result",
        headers=headers,
        json={
            "task_id": task_id,
            "success": result.success,
            "output": result.stdout,
            "error_message": result.error_message,
        },
    )
    if redis is not None:
        await _publish(
            redis,
            done_channel,
            {
                "task_id": task_id,
                "success": result.success,
                "error_message": result.error_message,
            },
        )
    logger.info("task_completed", task_id=task_id, success=result.success)


async def _publish(redis: Redis, channel: str, payload: dict[str, Any]) -> None:
    try:
        await redis.publish(channel, json.dumps(payload))
    except Exception:
        logger.warning("pubsub_publish_failed", channel=channel, exc_info=True)


def _connect_redis() -> Redis | None:
    if not settings.redis_url:
        return None
    try:
        from redis.asyncio import Redis as _Redis

        return _Redis.from_url(settings.redis_url, decode_responses=False)
    except Exception:
        logger.warning("redis_connect_failed", url=settings.redis_url, exc_info=True)
        return None


# ─── Main loop ───────────────────────────────────────────────────────


async def poll_and_execute() -> None:
    """Main loop: heartbeat -> poll -> execute -> report."""
    if not settings.worker_token:
        logger.info("no_token_found", hint="Registering with server...")
        token = await register(
            settings.worker_name,
            settings.server_url,
            settings.install_token,
        )
        settings.worker_token = token

    capabilities = detect_capabilities()
    executors: dict[str, ExecutorProtocol] = {}
    for cap in capabilities:
        try:
            executors[cap] = select_executor(cap)
        except ValueError:
            logger.warning("unknown_capability", capability=cap)

    if not executors:
        # No CLIs detected — register as claude_code so the worker still appears,
        # but tasks will fail at execute time with a clear FileNotFoundError.
        executors["claude_code"] = select_executor("claude_code")

    logger.info(
        "worker_starting",
        name=settings.worker_name,
        executors=list(executors.keys()),
        server=settings.server_url,
    )

    redis = _connect_redis()
    if redis is None:
        logger.warning(
            "no_redis",
            hint="Set BSGATEWAY_REDIS_URL to enable streaming chunks back to the gateway.",
        )

    headers = {"X-Worker-Token": settings.worker_token}
    in_flight: set[asyncio.Task[None]] = set()
    max_parallel = settings.max_parallel_tasks

    async def _run_task(task: dict[str, Any]) -> None:
        try:
            await _handle_task(task, executors, client, headers, redis)
        except Exception:
            logger.exception("task_execution_error", task_id=task.get("task_id"))

    async with httpx.AsyncClient(base_url=settings.server_url, timeout=30) as client:
        while True:
            try:
                done = {t for t in in_flight if t.done()}
                in_flight -= done

                await client.post("/api/v1/workers/heartbeat", headers=headers)

                if len(in_flight) >= max_parallel:
                    await asyncio.sleep(settings.capacity_wait_seconds)
                    continue

                slots = max_parallel - len(in_flight)
                res = await client.post(
                    "/api/v1/workers/poll",
                    headers=headers,
                    params={"count": min(slots, settings.poll_batch_max)},
                )
                res.raise_for_status()
                tasks: list[dict[str, Any]] = res.json()

                if not tasks:
                    await asyncio.sleep(settings.poll_interval_seconds)
                    continue

                for task in tasks:
                    t = asyncio.create_task(_run_task(task))
                    in_flight.add(t)

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    logger.error("auth_failed", hint="Invalid token. Re-register.")
                    sys.exit(1)
                logger.error("http_error", status=e.response.status_code)
                await asyncio.sleep(settings.poll_interval_seconds)
            except httpx.ConnectError:
                logger.warning("server_unreachable", url=settings.server_url)
                await asyncio.sleep(settings.poll_interval_seconds * 3)
            except Exception:
                logger.exception("worker_error")
                await asyncio.sleep(settings.poll_interval_seconds)


# ─── Env file helper ─────────────────────────────────────────────────


def _update_env_file(path: str, updates: dict[str, str]) -> None:
    """Update or create a .env file with the given key-value pairs."""
    lines: list[str] = []
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        pass

    existing: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}\n")
            existing.add(key)
        else:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in existing:
            new_lines.append(f"{key}={value}\n")
    with open(path, "w") as f:
        f.writelines(new_lines)


# ─── Entry point ─────────────────────────────────────────────────────


async def _amain() -> None:
    await poll_and_execute()


def main() -> None:
    """Synchronous entry point for ``bsgateway-worker`` script."""
    asyncio.run(_amain())
