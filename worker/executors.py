"""Standalone executor implementations for the BSGateway worker.

Kept self-contained so the worker package doesn't depend on the full
``bsgateway`` backend (which pulls in asyncpg, fastapi, etc.).

All three executors are one-shot subprocess streamers — ``execute()``
returns an ``AsyncIterator[ExecutionChunk]`` reading the CLI's native
JSON stream (``--output-format stream-json`` for claude, ``exec --json``
for codex, ``run --format json`` for opencode). The worker main loop
forwards each chunk to the gateway via Redis pub/sub so the client can
receive incremental ``chat.completion.chunk`` events.

User harness (``CLAUDE.md`` / ``settings.json`` / hooks / ``agents/``)
is intentionally **not** propagated by the gateway. Each executor relies
on whatever is installed locally on the worker machine. The
OpenAI-API-expressible ``system`` message IS forwarded — via
``--append-system-prompt`` (claude), ``--config
model_instructions_file=<tmp>`` (codex), or the ``instructions`` config
key (opencode, via ``OPENCODE_CONFIG_CONTENT``).
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
        model = context.get("model") or None
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
                        prompt, workspace, system, mcp_config_path, deadline, stderr_buf, model
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
        model: str | None = None,
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
        if model:
            cmd_args += ["--model", model]
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

    Flags track codex-cli's current contract (verified against 0.130.0):

    * ``--sandbox workspace-write`` — the supported sandbox policy.
      ``--full-auto`` is a deprecated compat alias (prints a warning).
    * ``--config model_instructions_file=<path>`` — the system message
      override. The old ``experimental_instructions_file`` key is no
      longer read by codex and silently drops the system prompt.
    * ``-m/--model`` — per-run model override.

    The prompt is fed on stdin (codex reads stdin when no positional
    prompt is given). The system message (if any) is written to a temp
    file, removed when the subprocess exits.
    """

    def __init__(self, timeout_seconds: int = 3600) -> None:
        self._cmd = shutil.which("codex") or "codex"
        self._timeout = timeout_seconds

    def supported_task_types(self) -> list[str]:
        return ["coding", "refactor", "bugfix", "test"]

    async def execute(self, prompt: str, context: dict[str, Any]) -> AsyncIterator[ExecutionChunk]:
        workspace = context.get("workspace_dir", ".")
        system = context.get("system") or ""
        model = context.get("model") or None
        deadline = asyncio.get_event_loop().time() + self._timeout

        sys_path: str | None = None
        if system:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            )
            tmp.write(system)
            tmp.close()
            sys_path = tmp.name

        cmd_args = [self._cmd, "exec", "--json", "--sandbox", "workspace-write"]
        if sys_path:
            cmd_args += ["--config", f"model_instructions_file={sys_path}"]
        if model:
            cmd_args += ["--model", model]

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


# ─── opencode run executor (subprocess) ──────────────────────────────


class OpenCodeExecutor:
    """Run a one-shot ``opencode run --format json`` subprocess per task.

    Verified against opencode 1.15.0+ (probed 1.15.3). Each task is its
    own process, so per-task ``--dir`` (workspace cwd), model, system
    prompt, and MCP servers are all naturally isolated — no shared
    ``opencode serve``, no port, no SSE.

    ``opencode run --format json`` emits a JSONL event stream on stdout:
    ``{"type":"step_start",...}`` → ``{"type":"text","part":{"type":
    "text","text":"..."}}`` → ``{"type":"step_finish","part":{"reason":
    "stop",...}}``. Assistant text is the ``part.text`` of each ``text``
    event; ``step_finish`` is terminal.

    ``system`` and ``mcp_servers`` are injected via the
    ``OPENCODE_CONFIG_CONTENT`` env var — an inline JSON config opencode
    merges with the worker's global config at startup. ``system`` is
    written to a temp file referenced by the config's ``instructions``
    array; ``mcp_servers`` becomes the config's ``mcp`` block (run-scoped
    MCP, resolving TODO E5b). The temp file is removed when the
    subprocess exits.
    """

    def __init__(self, timeout_seconds: int = 3600) -> None:
        self._cmd = shutil.which("opencode") or "opencode"
        self._timeout = timeout_seconds

    def supported_task_types(self) -> list[str]:
        return ["coding", "refactor", "bugfix", "test"]

    async def execute(self, prompt: str, context: dict[str, Any]) -> AsyncIterator[ExecutionChunk]:
        workspace = context.get("workspace_dir", ".")
        system = context.get("system") or ""
        model = context.get("model") or None
        mcp_servers = context.get("mcp_servers") or {}
        deadline = asyncio.get_event_loop().time() + self._timeout

        # Build the per-task inline config (system instructions + MCP).
        # opencode merges OPENCODE_CONFIG_CONTENT over the worker's global
        # config, so each subprocess is isolated without touching disk
        # config or the workspace.
        sys_path: str | None = None
        config: dict[str, Any] = {}
        if system:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            )
            tmp.write(system)
            tmp.close()
            sys_path = tmp.name
            config["instructions"] = [sys_path]
        if mcp_servers:
            config["mcp"] = _opencode_mcp_block(mcp_servers)

        env = dict(os.environ)
        if config:
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)

        cmd_args = [
            self._cmd,
            "run",
            "--format",
            "json",
            "--dangerously-skip-permissions",
            "--dir",
            workspace,
        ]
        # opencode's ``-m`` takes the provider/model string verbatim.
        if model:
            cmd_args += ["-m", model]
        cmd_args.append(prompt)

        process: asyncio.subprocess.Process | None = None
        stderr_buf: list[str] = []
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                cwd=workspace,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            assert process.stdout is not None
            assert process.stderr is not None

            stderr_task = asyncio.create_task(_drain(process.stderr, stderr_buf))
            try:
                async for line in _aiter_lines(process.stdout, deadline):
                    parsed = _safe_json(line)
                    if parsed is None:
                        continue
                    delta = _opencode_extract_delta(parsed)
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


def _opencode_mcp_block(mcp_servers: dict[str, Any]) -> dict[str, Any]:
    """Convert the BSNexus ``{name: {url, headers}}`` MCP dict into
    opencode's config ``mcp`` block shape: each entry is a remote server
    ``{type: "remote", url, enabled: true, headers?}``.
    """
    block: dict[str, Any] = {}
    for name, spec in mcp_servers.items():
        if not isinstance(spec, dict):
            continue
        entry: dict[str, Any] = {"type": "remote", "enabled": True}
        url = spec.get("url")
        if url:
            entry["url"] = url
        headers = spec.get("headers")
        if headers:
            entry["headers"] = headers
        block[name] = entry
    return block


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
    """Pull assistant text from a `codex exec --json` JSONL event.

    codex-cli (verified 0.130.0) emits an item-based stream:
    ``thread.started`` → ``turn.started`` → ``item.*`` → ``turn.completed``.
    The assistant's answer arrives whole as
    ``{"type": "item.completed", "item": {"type": "agent_message",
    "text": "..."}}`` — there is no token-level delta event, so we
    surface the text from the completed ``agent_message`` item only.
    """
    if event.get("type") == "item.completed":
        item = event.get("item") or {}
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text") or ""
            return text if isinstance(text, str) else ""
    return ""


def _opencode_extract_delta(event: dict[str, Any]) -> str:
    """Pull assistant text from an ``opencode run --format json`` event.

    Verified against opencode 1.15.3. ``opencode run`` emits a flat
    JSONL stream of ``{"type": ..., "part": {...}}`` records:
    ``step_start`` → ``text`` → ``step_finish``. The assistant's answer
    is the ``part.text`` of each ``text`` event; tool / step events
    carry no user-facing text. Process exit (or a ``step_finish``) marks
    the end, so no terminal-event detection is needed here.
    """
    if event.get("type") == "text":
        part = event.get("part") or {}
        if isinstance(part, dict):
            text = part.get("text") or ""
            return text if isinstance(text, str) else ""
    return ""


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
