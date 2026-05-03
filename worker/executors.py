"""Standalone executor implementations for the BSGateway worker.

Kept self-contained so the worker package doesn't depend on the full
``bsgateway`` backend (which pulls in asyncpg, fastapi, etc.).

All executors expose a streaming contract — ``execute()`` returns an
``AsyncIterator[ExecutionChunk]``. The worker main loop forwards each
chunk to the gateway via Redis pub/sub so the client can receive
incremental ``chat.completion.chunk`` events. Subprocess CLIs read the
CLI's native streaming format (``--output-format stream-json`` for
claude, ``exec --json`` for codex); ``OpenCodeExecutor`` consumes the
``opencode serve`` SSE feed.

User harness (``CLAUDE.md`` / ``settings.json`` / hooks / MCP /
``agents/``) is intentionally **not** propagated by the gateway. Each
executor relies on whatever is installed locally on the worker
machine. Only the OpenAI-API-expressible ``system`` message is
forwarded — via ``--append-system-prompt`` (claude),
``--config experimental_instructions_file=<tmp>`` (codex), or the
``system`` field of the opencode session create request.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import httpx


@dataclass
class ExecutionChunk:
    """One incremental message from a streaming executor.

    Either ``delta`` carries new text to append to the running output,
    or ``done`` marks terminal end-of-stream (with optional ``error``).
    """

    delta: str = ""
    done: bool = False
    error: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class ExecutionResult:
    """Aggregated terminal result. Built by ``collect()`` from chunks."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    error_message: str | None = None
    error_category: Literal["environment", "tool", ""] = ""
    chunks: list[ExecutionChunk] = field(default_factory=list)


@runtime_checkable
class ExecutorProtocol(Protocol):
    def execute(self, prompt: str, context: dict[str, Any]) -> AsyncIterator[ExecutionChunk]: ...

    def supported_task_types(self) -> list[str]: ...


async def collect(stream: AsyncIterator[ExecutionChunk]) -> ExecutionResult:
    """Drain a chunk stream into an ``ExecutionResult`` (for batch callers)."""
    parts: list[str] = []
    chunks: list[ExecutionChunk] = []
    error: str | None = None
    success = True
    try:
        async for chunk in stream:
            chunks.append(chunk)
            if chunk.delta:
                parts.append(chunk.delta)
            if chunk.error:
                error = chunk.error
                success = False
            if chunk.done:
                break
    finally:
        # Force the generator's finally blocks to run synchronously so
        # subprocess cleanup and tempfile unlink happen before we return.
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                pass
    return ExecutionResult(
        success=success,
        stdout="".join(parts),
        error_message=error,
        error_category="" if success else "tool",
        chunks=chunks,
    )


# ─── Claude Code CLI executor ─────────────────────────────────────────


class ClaudeCodeExecutor:
    """Stream from ``claude --print --output-format stream-json``.

    System message (if any) is appended via ``--append-system-prompt`` so
    the worker's local Claude harness (CLAUDE.md, settings.json, hooks)
    stays in effect.
    """

    def __init__(
        self,
        timeout_seconds: int = 3600,
        total_timeout_seconds: int = 7200,
        rate_limit_retries: int = 3,
        rate_limit_wait_seconds: int = 60,
    ) -> None:
        self._cmd = self._resolve_cmd()
        self._timeout = timeout_seconds
        self._total_timeout = total_timeout_seconds
        self._rate_limit_retries = rate_limit_retries
        self._rate_limit_wait = rate_limit_wait_seconds

    @staticmethod
    def _resolve_cmd() -> str:
        resolved = shutil.which("claude")
        if resolved:
            return resolved
        if sys.platform == "win32":
            resolved = shutil.which("claude.cmd")
            if resolved:
                return resolved
        return "claude"

    def supported_task_types(self) -> list[str]:
        return ["coding", "refactor", "bugfix", "test"]

    async def execute(self, prompt: str, context: dict[str, Any]) -> AsyncIterator[ExecutionChunk]:
        workspace = context.get("workspace_dir", ".")
        system = context.get("system") or ""
        mcp_servers = context.get("mcp_servers") or {}
        # Materialise the mcp config tempfile once for the whole retry loop —
        # claude CLI re-reads the path on each invocation, so we don't need
        # to recreate it per attempt. Cleanup happens here in the finally so
        # tmpfile lifetime is bounded by the executor.execute() generator,
        # not by individual subprocess attempts.
        mcp_config_path: str | None = None
        if mcp_servers:
            mcp_config_path = _write_claude_mcp_config(mcp_servers)
        attempts_remaining = self._rate_limit_retries
        deadline = asyncio.get_event_loop().time() + self._total_timeout
        try:
            while True:
                rate_limited = False
                stderr_buf: list[str] = []
                had_delta = False
                try:
                    async for chunk in self._run_once(
                        prompt, workspace, system, mcp_config_path, deadline, stderr_buf
                    ):
                        if chunk.delta:
                            had_delta = True
                        if chunk.error and self._is_rate_limited(
                            (chunk.error or "") + "".join(stderr_buf)
                        ):
                            rate_limited = True
                            # don't yield this chunk; we may retry
                            continue
                        yield chunk
                        if chunk.done:
                            return
                    if not had_delta and self._is_rate_limited("".join(stderr_buf)):
                        rate_limited = True
                except TimeoutError:
                    yield ExecutionChunk(
                        done=True,
                        error=f"Total execution timed out after {self._total_timeout}s",
                    )
                    return

                if rate_limited and attempts_remaining > 0:
                    attempts_remaining -= 1
                    await asyncio.sleep(self._rate_limit_wait)
                    continue
                # Either non-retryable failure, or retries exhausted — surface terminal error.
                yield ExecutionChunk(
                    done=True,
                    error="Rate limit retries exhausted" if rate_limited else "claude exited",
                )
                return
        finally:
            if mcp_config_path is not None:
                try:
                    os.unlink(mcp_config_path)
                except OSError:
                    pass

    async def _run_once(
        self,
        prompt: str,
        workspace: str,
        system: str,
        mcp_config_path: str | None,
        deadline: float,
        stderr_buf: list[str],
    ) -> AsyncIterator[ExecutionChunk]:
        cmd_args = [
            self._cmd,
            "--print",
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        if system:
            cmd_args += ["--append-system-prompt", system]
        if mcp_config_path:
            cmd_args += ["--mcp-config", mcp_config_path]
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                cwd=workspace,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None

            process.stdin.write(prompt.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()

            stderr_task = asyncio.create_task(_drain(process.stderr, stderr_buf))
            try:
                async for line in _aiter_lines(process.stdout, deadline):
                    parsed = _safe_json(line)
                    if parsed is None:
                        continue
                    delta = _claude_extract_delta(parsed)
                    if delta:
                        yield ExecutionChunk(delta=delta, raw=parsed)
            finally:
                rc = await asyncio.wait_for(
                    process.wait(), timeout=max(0.1, deadline - asyncio.get_event_loop().time())
                )
                await stderr_task
            err_text = "".join(stderr_buf)
            if rc != 0:
                yield ExecutionChunk(done=True, error=err_text or f"exit {rc}")
            else:
                yield ExecutionChunk(done=True)
        except (FileNotFoundError, PermissionError, OSError) as e:
            yield ExecutionChunk(done=True, error=str(e))
        finally:
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass

    @staticmethod
    def _is_rate_limited(output: str) -> bool:
        lower = output.lower()
        return "hit your limit" in lower or "rate limit" in lower


# ─── Codex CLI executor (subprocess) ─────────────────────────────────


class CodexExecutor:
    """Stream from ``codex exec --json``.

    System message (if any) is written to a temp file and passed via
    ``--config experimental_instructions_file=<path>`` per the codex
    docs. The temp file is removed when the subprocess exits.
    """

    def __init__(self, timeout_seconds: int = 3600) -> None:
        self._cmd = shutil.which("codex") or "codex"
        self._timeout = timeout_seconds

    def supported_task_types(self) -> list[str]:
        return ["coding", "refactor", "bugfix", "test"]

    async def execute(self, prompt: str, context: dict[str, Any]) -> AsyncIterator[ExecutionChunk]:
        workspace = context.get("workspace_dir", ".")
        system = context.get("system") or ""
        deadline = asyncio.get_event_loop().time() + self._timeout

        sys_path: str | None = None
        if system:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            )
            tmp.write(system)
            tmp.close()
            sys_path = tmp.name

        cmd_args = [self._cmd, "exec", "--json", "--full-auto"]
        if sys_path:
            cmd_args += ["--config", f"experimental_instructions_file={sys_path}"]

        process: asyncio.subprocess.Process | None = None
        stderr_buf: list[str] = []
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                cwd=workspace,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None

            process.stdin.write(prompt.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()

            stderr_task = asyncio.create_task(_drain(process.stderr, stderr_buf))
            try:
                async for line in _aiter_lines(process.stdout, deadline):
                    parsed = _safe_json(line)
                    if parsed is None:
                        continue
                    delta = _codex_extract_delta(parsed)
                    if delta:
                        yield ExecutionChunk(delta=delta, raw=parsed)
            finally:
                rc = await asyncio.wait_for(
                    process.wait(), timeout=max(0.1, deadline - asyncio.get_event_loop().time())
                )
                await stderr_task
            err_text = "".join(stderr_buf)
            if rc != 0:
                yield ExecutionChunk(done=True, error=err_text or f"exit {rc}")
            else:
                yield ExecutionChunk(done=True)
        except TimeoutError:
            yield ExecutionChunk(done=True, error=f"Execution timed out after {self._timeout}s")
        except (FileNotFoundError, PermissionError, OSError) as e:
            yield ExecutionChunk(done=True, error=str(e))
        finally:
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass
            if sys_path:
                try:
                    os.unlink(sys_path)
                except OSError:
                    pass


# ─── opencode serve executor ─────────────────────────────────────────


class OpenCodeExecutor:
    """Talks to a worker-local ``opencode serve`` instance over HTTP+SSE.

    The first ``execute()`` call lazy-spawns ``opencode serve`` on a free
    port (or a configured port) and reuses it for the worker's lifetime.
    Each task gets a fresh session — multi-turn reuse is intentionally
    out of scope for v1 (see follow-ups).

    **TODO E6 — workspace_dir limitation**: ``opencode serve`` is a
    single long-lived process whose ``cwd`` is fixed at spawn time. The
    session create body does not currently expose a per-session
    ``directory`` / ``cwd`` field (verified against opencode upstream
    at PR #26 time). We therefore **ignore** ``context.workspace_dir``
    here — opencode operates in the worker's process cwd. claude_code
    and codex both honor ``workspace_dir`` per-task. BSNexus v1 picks
    ``executor_type=claude_code`` so this is acceptable; tightening the
    opencode cwd is a follow-up TODO E6b.
    """

    _server_lock = asyncio.Lock()

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        spawn_timeout_seconds: float = 30.0,
        request_timeout_seconds: float = 600.0,
    ) -> None:
        self._cmd = shutil.which("opencode") or "opencode"
        self._host = host
        self._port = port
        self._spawn_timeout = spawn_timeout_seconds
        self._request_timeout = request_timeout_seconds
        self._proc: asyncio.subprocess.Process | None = None
        self._base_url: str | None = None

    def supported_task_types(self) -> list[str]:
        return ["coding", "refactor", "bugfix", "test"]

    async def _ensure_server(self) -> str:
        if self._base_url is not None and self._proc is not None and self._proc.returncode is None:
            return self._base_url
        async with OpenCodeExecutor._server_lock:
            if (
                self._base_url is not None
                and self._proc is not None
                and self._proc.returncode is None
            ):
                return self._base_url
            port = self._port if self._port else _find_free_port()
            self._proc = await asyncio.create_subprocess_exec(
                self._cmd,
                "serve",
                "--port",
                str(port),
                "--hostname",
                self._host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._base_url = f"http://{self._host}:{port}"
            await self._wait_ready(self._base_url)
            return self._base_url

    async def _wait_ready(self, base_url: str) -> None:
        deadline = asyncio.get_event_loop().time() + self._spawn_timeout
        async with httpx.AsyncClient(timeout=2.0) as client:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    res = await client.get(f"{base_url}/doc")
                    if res.status_code < 500:
                        return
                except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError):
                    pass
                await asyncio.sleep(0.2)
        raise RuntimeError(f"opencode serve did not become ready at {base_url}")

    async def execute(self, prompt: str, context: dict[str, Any]) -> AsyncIterator[ExecutionChunk]:
        try:
            base_url = await self._ensure_server()
        except (FileNotFoundError, PermissionError, OSError, RuntimeError) as e:
            yield ExecutionChunk(done=True, error=str(e))
            return

        system = context.get("system") or ""
        mcp_servers = context.get("mcp_servers") or {}
        try:
            async with httpx.AsyncClient(
                base_url=base_url, timeout=self._request_timeout
            ) as client:
                session_body: dict[str, Any] = {}
                if system:
                    session_body["system"] = system
                # TODO E5b — opencode session-level MCP injection. The
                # ``mcpServers`` field on session create matches claude
                # CLI's ``--mcp-config`` shape (``{name: {url, headers}}``).
                # Empty / missing ⇒ field omitted (back-compat).
                if mcp_servers:
                    session_body["mcpServers"] = mcp_servers
                res = await client.post("/session", json=session_body)
                res.raise_for_status()
                session_id = res.json().get("id") or res.json().get("sessionID")
                if not session_id:
                    yield ExecutionChunk(done=True, error="opencode session id missing")
                    return

                async def _post_message() -> None:
                    await client.post(
                        f"/session/{session_id}/message",
                        json={"role": "user", "content": prompt},
                    )

                send_task = asyncio.create_task(_post_message())
                try:
                    async with client.stream("GET", "/event") as event_res:
                        event_res.raise_for_status()
                        async for line in event_res.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if not payload:
                                continue
                            parsed = _safe_json(payload)
                            if parsed is None:
                                continue
                            delta = _opencode_extract_delta(parsed, session_id)
                            if delta:
                                yield ExecutionChunk(delta=delta, raw=parsed)
                            if _opencode_is_terminal(parsed, session_id):
                                yield ExecutionChunk(done=True, raw=parsed)
                                break
                finally:
                    if not send_task.done():
                        send_task.cancel()
                        try:
                            await send_task
                        except (asyncio.CancelledError, httpx.HTTPError):
                            pass
        except httpx.HTTPError as e:
            yield ExecutionChunk(done=True, error=str(e))


# ─── Format-specific extractors ──────────────────────────────────────


def _claude_extract_delta(event: dict[str, Any]) -> str:
    """Pull incremental text out of a `claude --output-format stream-json` event.

    Claude emits ``{"type": "assistant", "message": {"content": [...]}}`` blocks
    plus interleaved tool calls. We surface the assistant text only — tool
    activity is implicit in the final output. Robust against minor schema
    variation: also handles a flat ``delta.text`` shape.
    """
    if event.get("type") == "assistant":
        msg = event.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text") or ""
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
    delta = event.get("delta")
    if isinstance(delta, dict):
        text = delta.get("text") or delta.get("content")
        if isinstance(text, str):
            return text
    return ""


def _codex_extract_delta(event: dict[str, Any]) -> str:
    """Pull incremental text from `codex exec --json` JSONL events.

    Codex' JSONL stream uses ``{"type": "message_delta", "content": "..."}``
    for streaming text and a final ``{"type": "message", ...}`` wrap-up.
    Defensive against shape drift across versions.
    """
    t = event.get("type")
    if t in ("message_delta", "assistant_delta"):
        c = event.get("content") or event.get("text") or ""
        return c if isinstance(c, str) else ""
    if t == "message":
        c = event.get("content") or ""
        if isinstance(c, str):
            return c
    return ""


def _opencode_extract_delta(event: dict[str, Any], session_id: str) -> str:
    """Pull incremental text from an opencode SSE bus event.

    opencode multiplexes a global event bus over ``/event``. We only
    surface ``message.update`` / ``message.part.update`` text deltas
    scoped to our session.
    """
    name = event.get("type") or event.get("event")
    props = event.get("properties") or event.get("data") or {}
    sid = props.get("sessionID") or props.get("session_id")
    if sid and sid != session_id:
        return ""
    if name in ("message.part.update", "message.part.added"):
        part = props.get("part") or {}
        if part.get("type") == "text":
            text = part.get("text") or ""
            return text if isinstance(text, str) else ""
    if name == "message.update":
        msg = props.get("message") or {}
        content = msg.get("content") or msg.get("text") or ""
        if isinstance(content, str):
            return content
    return ""


def _opencode_is_terminal(event: dict[str, Any], session_id: str) -> bool:
    name = event.get("type") or event.get("event")
    props = event.get("properties") or event.get("data") or {}
    sid = props.get("sessionID") or props.get("session_id")
    if sid and sid != session_id:
        return False
    return name in ("session.idle", "message.completed", "message.done")


# ─── Subprocess helpers ──────────────────────────────────────────────


async def _aiter_lines(stream: asyncio.StreamReader, deadline: float) -> AsyncIterator[str]:
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError
        try:
            line = await asyncio.wait_for(stream.readline(), timeout=remaining)
        except TimeoutError:
            raise
        if not line:
            return
        yield line.decode("utf-8", errors="replace").rstrip("\n")


async def _drain(stream: asyncio.StreamReader, buf: list[str]) -> None:
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            return
        buf.append(chunk.decode("utf-8", errors="replace"))


def _safe_json(line: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_claude_mcp_config(mcp_servers: dict[str, Any]) -> str:
    """Write a claude-CLI-format MCP config file. Returns the path.

    Wraps the BSNexus-style ``{name: {url, headers}}`` dict into the
    ``{"mcpServers": ...}`` envelope claude CLI expects on
    ``--mcp-config``. File mode is 0600 because the embedded URL may
    contain a run-scoped auth token.
    """
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    )
    try:
        json.dump({"mcpServers": mcp_servers}, tmp)
    finally:
        tmp.close()
    try:
        os.chmod(tmp.name, 0o600)
    except OSError:
        pass
    return tmp.name


# ─── Factory ──────────────────────────────────────────────────────────


_EXECUTORS: dict[str, type] = {
    "claude_code": ClaudeCodeExecutor,
    "codex": CodexExecutor,
    "opencode": OpenCodeExecutor,
}


def create_executor(executor_type: str) -> ExecutorProtocol:
    cls = _EXECUTORS.get(executor_type)
    if cls is None:
        raise ValueError(f"Unknown executor type: {executor_type}")
    return cls()
