"""TASK-011 — ``bsgateway workers / execute`` CLI sub-apps.

Pattern matches TASK-008..010 — :class:`typer.testing.CliRunner` invokes the
top-level :data:`bsgateway.cli.main.app` with a per-module-monkey-patched
:func:`build_client` returning a :class:`unittest.mock.MagicMock`.

Coverage axes:

* sub-app wiring (subcommands registered),
* request shape (path, body, query params, headers),
* output shape (JSON on stdout under ``-o json``),
* ``--dry-run`` truly skips HTTP,
* friendly 4xx surface (no stack trace, exit code != 0),
* tenant enforcement on tenant-scoped commands,
* ``execute`` polls ``GET /tasks/{id}`` until terminal status,
* ``execute --no-wait`` returns immediately after POST,
* ``execute --worker`` sets the pin field on the body.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from typer.testing import CliRunner

TENANT = "11111111-1111-1111-1111-111111111111"
WORKER_ID = "22222222-2222-2222-2222-222222222222"
TASK_ID = "33333333-3333-3333-3333-333333333333"
INSTALL_TOKEN = "install-tok-secret"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def _resp(status_code: int = 200, payload: object | None = None) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.json.return_value = payload
    r.text = json.dumps(payload, default=str) if payload is not None else ""
    return r


def _fake(monkeypatch: pytest.MonkeyPatch, module: str) -> MagicMock:
    client = MagicMock(name=f"CliHttpClient[{module}]")
    client.aclose = AsyncMock(return_value=None)
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.delete = AsyncMock()
    client.request = AsyncMock()
    monkeypatch.setattr(f"bsgateway.cli.commands.{module}.build_client", lambda ctx: client)
    return client


def _base(*extra: str, tenant: bool = True) -> list[str]:
    args = ["--url", "http://gw.test", "--token", "tok", "-o", "json"]
    if tenant:
        args += ["--tenant", TENANT]
    args += list(extra)
    return args


# ===========================================================================
# workers
# ===========================================================================


def test_workers_subapp_help(runner: CliRunner) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, ["workers", "--help"])
    assert result.exit_code == 0, result.stderr
    for sub in ("list", "register", "revoke"):
        assert sub in result.stdout


def test_workers_list(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "workers")
    fake.get.return_value = _resp(
        200, [{"id": WORKER_ID, "name": "host1", "labels": [], "capabilities": ["claude_code"]}]
    )
    result = runner.invoke(app, _base("workers", "list"))
    assert result.exit_code == 0, result.stderr
    fake.get.assert_awaited_once_with("/workers")
    assert json.loads(result.stdout)[0]["id"] == WORKER_ID


def test_workers_list_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "workers")
    result = runner.invoke(
        app,
        [
            "--url",
            "http://gw.test",
            "--tenant",
            TENANT,
            "--dry-run",
            "-o",
            "json",
            "workers",
            "list",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake.get.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["method"] == "GET"
    assert payload["path"] == "/workers"


def test_workers_list_requires_tenant(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "workers")
    result = runner.invoke(app, ["--url", "http://gw.test", "-o", "json", "workers", "list"])
    assert result.exit_code != 0


def test_workers_register(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "workers")
    fake.post.return_value = _resp(201, {"id": WORKER_ID, "token": "wt-secret"})
    result = runner.invoke(
        app,
        _base(
            "workers",
            "register",
            "--name",
            "host1",
            "--install-token",
            INSTALL_TOKEN,
            "--label",
            "gpu",
            "--label",
            "x86",
            "--capability",
            "claude_code",
            "--capability",
            "codex",
        ),
    )
    assert result.exit_code == 0, result.stderr
    args, kwargs = fake.post.await_args
    assert args[0] == "/workers/register"
    assert kwargs["json"] == {
        "name": "host1",
        "labels": ["gpu", "x86"],
        "capabilities": ["claude_code", "codex"],
    }
    assert kwargs["headers"] == {"X-Install-Token": INSTALL_TOKEN}
    assert json.loads(result.stdout)["token"] == "wt-secret"


def test_workers_register_defaults(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "workers")
    fake.post.return_value = _resp(201, {"id": WORKER_ID, "token": "wt"})
    result = runner.invoke(
        app,
        _base("workers", "register", "--name", "h2", "--install-token", INSTALL_TOKEN),
    )
    assert result.exit_code == 0, result.stderr
    body = fake.post.await_args.kwargs["json"]
    assert body == {"name": "h2", "labels": [], "capabilities": []}


def test_workers_register_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "workers")
    result = runner.invoke(
        app,
        [
            "--url",
            "http://gw.test",
            "--tenant",
            TENANT,
            "--dry-run",
            "-o",
            "json",
            "workers",
            "register",
            "--name",
            "h",
            "--install-token",
            INSTALL_TOKEN,
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake.post.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["method"] == "POST"
    assert payload["path"] == "/workers/register"
    # install token must NOT leak into the dry-run preview
    assert INSTALL_TOKEN not in result.stdout


def test_workers_revoke(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "workers")
    fake.delete.return_value = _resp(204, None)
    result = runner.invoke(app, _base("workers", "revoke", WORKER_ID))
    assert result.exit_code == 0, result.stderr
    fake.delete.assert_awaited_once_with(f"/workers/{WORKER_ID}")


def test_workers_revoke_404_with_if_exists(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "workers")
    fake.delete.return_value = _resp(404, {"detail": "not found"})
    result = runner.invoke(app, _base("workers", "revoke", WORKER_ID, "--if-exists"))
    assert result.exit_code == 0, result.stderr


def test_workers_revoke_404_without_if_exists(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "workers")
    fake.delete.return_value = _resp(404, {"detail": "not found"})
    result = runner.invoke(app, _base("workers", "revoke", WORKER_ID))
    assert result.exit_code != 0


def test_workers_403_friendly(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "workers")
    fake.get.return_value = _resp(403, {"detail": "scope missing"})
    result = runner.invoke(app, _base("workers", "list"))
    assert result.exit_code != 0
    assert "scope missing" in (result.stdout + result.stderr)
    assert "Traceback" not in (result.stdout + result.stderr)


# ===========================================================================
# execute
# ===========================================================================


def test_execute_subapp_help(runner: CliRunner) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, ["execute", "--help"])
    assert result.exit_code == 0, result.stderr
    # Single-action sub-app — Typer renders Options/Arguments not subcommands.
    assert "--type" in result.stdout
    assert "PROMPT" in result.stdout.upper()


def test_execute_no_wait(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--no-wait`` returns the dispatched task immediately."""
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "execute")
    fake.post.return_value = _resp(201, {"task_id": TASK_ID, "status": "dispatched"})
    result = runner.invoke(
        app,
        _base("execute", "--type", "claude_code", "--no-wait", "do the thing"),
    )
    assert result.exit_code == 0, result.stderr
    args, kwargs = fake.post.await_args
    assert args[0] == "/execute"
    assert kwargs["json"] == {"executor_type": "claude_code", "prompt": "do the thing"}
    assert json.loads(result.stdout) == {"task_id": TASK_ID, "status": "dispatched"}
    fake.get.assert_not_awaited()


def test_execute_polls_until_done(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "execute")
    fake.post.return_value = _resp(201, {"task_id": TASK_ID, "status": "dispatched"})
    fake.get.side_effect = [
        _resp(200, {"id": TASK_ID, "status": "running", "output": None}),
        _resp(
            200,
            {
                "id": TASK_ID,
                "status": "done",
                "output": "hello world",
                "error_message": None,
            },
        ),
    ]
    monkeypatch.setattr("bsgateway.cli.commands.execute._POLL_INTERVAL_S", 0.0)
    result = runner.invoke(
        app, _base("execute", "--type", "claude_code", "--timeout", "5", "do it")
    )
    assert result.exit_code == 0, result.stderr
    assert fake.get.await_count == 2
    fake.get.assert_awaited_with(f"/tasks/{TASK_ID}")
    payload = json.loads(result.stdout)
    assert payload["status"] == "done"
    assert payload["output"] == "hello world"


def test_execute_failed_task_exits_nonzero(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "execute")
    fake.post.return_value = _resp(201, {"task_id": TASK_ID, "status": "dispatched"})
    fake.get.return_value = _resp(
        200, {"id": TASK_ID, "status": "failed", "output": "", "error_message": "boom"}
    )
    monkeypatch.setattr("bsgateway.cli.commands.execute._POLL_INTERVAL_S", 0.0)
    result = runner.invoke(
        app, _base("execute", "--type", "claude_code", "--timeout", "5", "do it")
    )
    assert result.exit_code != 0
    assert "boom" in (result.stdout + result.stderr)


def test_execute_pending_dispatch_no_worker(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When backend returns ``status='pending'`` (no available worker) and the
    user did not pass ``--no-wait``, surface a clear error rather than polling
    forever for a task that will never start."""
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "execute")
    fake.post.return_value = _resp(201, {"task_id": TASK_ID, "status": "pending"})
    monkeypatch.setattr("bsgateway.cli.commands.execute._POLL_INTERVAL_S", 0.0)
    result = runner.invoke(
        app, _base("execute", "--type", "claude_code", "--timeout", "1", "do it")
    )
    assert result.exit_code != 0
    fake.get.assert_not_awaited()
    err = result.stdout + result.stderr
    assert "no worker" in err.lower() or "pending" in err.lower()


def test_execute_worker_pin(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--worker`` adds ``worker_id`` to the request body for forward
    compatibility (backend currently auto-assigns; see TODO in execute.py)."""
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "execute")
    fake.post.return_value = _resp(201, {"task_id": TASK_ID, "status": "dispatched"})
    fake.get.return_value = _resp(200, {"id": TASK_ID, "status": "done", "output": "ok"})
    monkeypatch.setattr("bsgateway.cli.commands.execute._POLL_INTERVAL_S", 0.0)
    result = runner.invoke(
        app,
        _base(
            "execute",
            "--type",
            "claude_code",
            "--worker",
            WORKER_ID,
            "--no-wait",
            "do it",
        ),
    )
    assert result.exit_code == 0, result.stderr
    body = fake.post.await_args.kwargs["json"]
    assert body == {
        "executor_type": "claude_code",
        "prompt": "do it",
        "worker_id": WORKER_ID,
    }


def test_execute_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "execute")
    result = runner.invoke(
        app,
        [
            "--url",
            "http://gw.test",
            "--tenant",
            TENANT,
            "--dry-run",
            "-o",
            "json",
            "execute",
            "--type",
            "claude_code",
            "do it",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake.post.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["method"] == "POST"
    assert payload["path"] == "/execute"
    assert payload["body"]["executor_type"] == "claude_code"
    assert payload["body"]["prompt"] == "do it"


def test_execute_requires_tenant(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "execute")
    result = runner.invoke(
        app,
        ["--url", "http://gw.test", "-o", "json", "execute", "--type", "claude_code", "p"],
    )
    assert result.exit_code != 0


def test_execute_403_friendly(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "execute")
    fake.post.return_value = _resp(403, {"detail": "scope missing"})
    result = runner.invoke(app, _base("execute", "--type", "claude_code", "--no-wait", "p"))
    assert result.exit_code != 0
    assert "scope missing" in (result.stdout + result.stderr)
    assert "Traceback" not in (result.stdout + result.stderr)


def test_execute_timeout(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    """If polling exceeds ``--timeout`` and task is still running, exit nonzero."""
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "execute")
    fake.post.return_value = _resp(201, {"task_id": TASK_ID, "status": "dispatched"})
    fake.get.return_value = _resp(200, {"id": TASK_ID, "status": "running", "output": None})
    # Force a single poll and then timeout: zero interval, zero timeout.
    monkeypatch.setattr("bsgateway.cli.commands.execute._POLL_INTERVAL_S", 0.0)
    result = runner.invoke(app, _base("execute", "--type", "claude_code", "--timeout", "0", "p"))
    assert result.exit_code != 0
    assert "timeout" in (result.stdout + result.stderr).lower()
