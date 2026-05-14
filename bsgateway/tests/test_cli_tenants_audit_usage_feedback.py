"""TASK-010 — ``bsgateway tenants / audit / usage / feedback`` CLI sub-apps.

Same exercise pattern as TASK-009 — :class:`typer.testing.CliRunner` with
``build_client`` monkey-patched per module to a ``MagicMock``. Tests assert:

* sub-app wiring (subcommands registered),
* request shape (path / body / query params on the mocked client),
* output shape (JSON on stdout under ``-o json``),
* ``--dry-run`` truly skipping HTTP,
* friendly 4xx surface (no stack trace, exit code != 0),
* tenant enforcement on tenant-scoped commands (audit / usage / feedback),
* tenants sub-app does NOT require --tenant for ``list``/``add``/``show``
  since those target ``/tenants`` (the resource), not a per-tenant subtree.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from typer.testing import CliRunner

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "44444444-4444-4444-4444-444444444444"
ROUTING_ID = "55555555-5555-5555-5555-555555555555"
AUDIT_ID = "66666666-6666-6666-6666-666666666666"


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
# tenants
# ===========================================================================


def test_tenants_subapp_help(runner: CliRunner) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, ["tenants", "--help"])
    assert result.exit_code == 0, result.stderr
    for sub in ("list", "add", "update", "delete", "show"):
        assert sub in result.stdout


def test_tenants_list(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "tenants")
    fake.get.return_value = _resp(200, [{"id": TENANT, "name": "Acme", "slug": "acme"}])
    result = runner.invoke(app, _base("tenants", "list", tenant=False))
    assert result.exit_code == 0, result.stderr
    fake.get.assert_awaited_once()
    args, kwargs = fake.get.await_args
    assert args[0] == "/tenants"
    assert kwargs["params"] == {"limit": 50, "offset": 0}


def test_tenants_list_pagination(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "tenants")
    fake.get.return_value = _resp(200, [])
    result = runner.invoke(
        app, _base("tenants", "list", "--limit", "10", "--offset", "20", tenant=False)
    )
    assert result.exit_code == 0, result.stderr
    assert fake.get.await_args.kwargs["params"] == {"limit": 10, "offset": 20}


def test_tenants_list_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "tenants")
    result = runner.invoke(
        app,
        ["--url", "http://gw.test", "--dry-run", "-o", "json", "tenants", "list"],
    )
    assert result.exit_code == 0, result.stderr
    fake.get.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["method"] == "GET"
    assert payload["path"] == "/tenants"


def test_tenants_add(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "tenants")
    fake.post.return_value = _resp(201, {"id": TENANT, "name": "Acme", "slug": "acme"})
    result = runner.invoke(
        app,
        _base("tenants", "add", "--name", "Acme", "--slug", "acme", tenant=False),
    )
    assert result.exit_code == 0, result.stderr
    fake.post.assert_awaited_once()
    args, kwargs = fake.post.await_args
    assert args[0] == "/tenants"
    assert kwargs["json"] == {"name": "Acme", "slug": "acme", "settings": {}}


def test_tenants_add_with_settings(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "tenants")
    fake.post.return_value = _resp(201, {"id": TENANT})
    settings = json.dumps({"rate_limit": {"requests_per_minute": 60}})
    result = runner.invoke(
        app,
        _base(
            "tenants",
            "add",
            "--name",
            "Acme",
            "--slug",
            "acme",
            "--settings",
            settings,
            tenant=False,
        ),
    )
    assert result.exit_code == 0, result.stderr
    body = fake.post.await_args.kwargs["json"]
    assert body["settings"] == {"rate_limit": {"requests_per_minute": 60}}


def test_tenants_add_invalid_settings_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "tenants")
    result = runner.invoke(
        app,
        _base(
            "tenants",
            "add",
            "--name",
            "Acme",
            "--slug",
            "acme",
            "--settings",
            "not-json",
            tenant=False,
        ),
    )
    assert result.exit_code != 0


def test_tenants_add_settings_must_be_object(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "tenants")
    result = runner.invoke(
        app,
        _base(
            "tenants",
            "add",
            "--name",
            "Acme",
            "--slug",
            "acme",
            "--settings",
            "[1,2,3]",
            tenant=False,
        ),
    )
    assert result.exit_code != 0


def test_tenants_show(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "tenants")
    fake.get.return_value = _resp(200, {"id": OTHER_TENANT, "name": "X", "slug": "x"})
    result = runner.invoke(app, _base("tenants", "show", OTHER_TENANT, tenant=False))
    assert result.exit_code == 0, result.stderr
    fake.get.assert_awaited_once_with(f"/tenants/{OTHER_TENANT}")
    assert json.loads(result.stdout)["id"] == OTHER_TENANT


def test_tenants_update_only_provided(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "tenants")
    fake.request.return_value = _resp(200, {"id": OTHER_TENANT, "name": "Renamed"})
    result = runner.invoke(
        app, _base("tenants", "update", OTHER_TENANT, "--name", "Renamed", tenant=False)
    )
    assert result.exit_code == 0, result.stderr
    method, path = fake.request.await_args.args
    assert method == "PATCH"
    assert path == f"/tenants/{OTHER_TENANT}"
    assert fake.request.await_args.kwargs["json"] == {"name": "Renamed"}


def test_tenants_update_no_args_rejected(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "tenants")
    result = runner.invoke(app, _base("tenants", "update", OTHER_TENANT, tenant=False))
    assert result.exit_code != 0


def test_tenants_delete(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "tenants")
    fake.delete.return_value = _resp(204, None)
    result = runner.invoke(app, _base("tenants", "delete", OTHER_TENANT, tenant=False))
    assert result.exit_code == 0, result.stderr
    fake.delete.assert_awaited_once_with(f"/tenants/{OTHER_TENANT}")


def test_tenants_delete_404_with_if_exists(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "tenants")
    fake.delete.return_value = _resp(404, {"detail": "not found"})
    result = runner.invoke(
        app, _base("tenants", "delete", OTHER_TENANT, "--if-exists", tenant=False)
    )
    assert result.exit_code == 0, result.stderr


def test_tenants_403_friendly(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "tenants")
    fake.get.return_value = _resp(403, {"detail": "scope missing: bsgateway:tenants:read"})
    result = runner.invoke(app, _base("tenants", "list", tenant=False))
    assert result.exit_code != 0
    assert "scope missing" in (result.stdout + result.stderr)
    assert "Traceback" not in (result.stdout + result.stderr)


# ===========================================================================
# audit
# ===========================================================================


def test_audit_subapp_help(runner: CliRunner) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, ["audit", "--help"])
    assert result.exit_code == 0, result.stderr
    assert "list" in result.stdout


def test_audit_list(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "audit")
    fake.get.return_value = _resp(
        200, {"items": [{"id": AUDIT_ID, "action": "model.created"}], "total": 1}
    )
    result = runner.invoke(app, _base("audit", "list"))
    assert result.exit_code == 0, result.stderr
    args, kwargs = fake.get.await_args
    assert args[0] == f"/tenants/{TENANT}/audit"
    assert kwargs["params"] == {"limit": 50, "offset": 0}
    assert json.loads(result.stdout)["total"] == 1


def test_audit_list_pagination(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "audit")
    fake.get.return_value = _resp(200, {"items": [], "total": 0})
    result = runner.invoke(app, _base("audit", "list", "--limit", "5", "--offset", "100"))
    assert result.exit_code == 0, result.stderr
    assert fake.get.await_args.kwargs["params"] == {"limit": 5, "offset": 100}


def test_audit_list_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "audit")
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
            "audit",
            "list",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake.get.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["path"] == f"/tenants/{TENANT}/audit"


def test_audit_requires_tenant(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "audit")
    result = runner.invoke(app, ["--url", "http://gw.test", "-o", "json", "audit", "list"])
    assert result.exit_code != 0
    assert "tenant" in (result.stdout + result.stderr).lower()


def test_audit_403_friendly(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "audit")
    fake.get.return_value = _resp(403, {"detail": "scope missing: bsgateway:audit:read"})
    result = runner.invoke(app, _base("audit", "list"))
    assert result.exit_code != 0
    assert "Traceback" not in (result.stdout + result.stderr)


# ===========================================================================
# usage
# ===========================================================================


def test_usage_subapp_help(runner: CliRunner) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, ["usage", "--help"])
    assert result.exit_code == 0, result.stderr
    for sub in ("report", "sparklines"):
        assert sub in result.stdout


def test_usage_report_default(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "usage")
    fake.get.return_value = _resp(
        200,
        {
            "total_requests": 42,
            "total_tokens": 100,
            "by_model": {"gpt-4o": {"requests": 42, "tokens": 100}},
            "by_rule": {},
            "daily_breakdown": [],
        },
    )
    result = runner.invoke(app, _base("usage", "report"))
    assert result.exit_code == 0, result.stderr
    args, kwargs = fake.get.await_args
    assert args[0] == f"/tenants/{TENANT}/usage"
    assert kwargs["params"] == {"period": "day"}
    assert json.loads(result.stdout)["total_requests"] == 42


def test_usage_report_custom_window(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "usage")
    fake.get.return_value = _resp(
        200,
        {
            "total_requests": 0,
            "total_tokens": 0,
            "by_model": {},
            "by_rule": {},
            "daily_breakdown": [],
        },
    )
    result = runner.invoke(
        app,
        _base(
            "usage",
            "report",
            "--period",
            "week",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-07",
        ),
    )
    assert result.exit_code == 0, result.stderr
    params = fake.get.await_args.kwargs["params"]
    assert params["period"] == "week"
    assert params["from"] == "2026-01-01"
    assert params["to"] == "2026-01-07"


def test_usage_report_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "usage")
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
            "usage",
            "report",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake.get.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["path"] == f"/tenants/{TENANT}/usage"


def test_usage_sparklines(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "usage")
    fake.get.return_value = _resp(200, {"gpt-4o": [0, 1, 2, 3, 4, 5, 6]})
    result = runner.invoke(app, _base("usage", "sparklines", "--days", "7"))
    assert result.exit_code == 0, result.stderr
    args, kwargs = fake.get.await_args
    assert args[0] == f"/tenants/{TENANT}/usage/sparklines"
    assert kwargs["params"] == {"days": 7}


def test_usage_requires_tenant(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "usage")
    result = runner.invoke(app, ["--url", "http://gw.test", "-o", "json", "usage", "report"])
    assert result.exit_code != 0


def test_usage_403_friendly(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "usage")
    fake.get.return_value = _resp(403, {"detail": "tenant scope missing"})
    result = runner.invoke(app, _base("usage", "report"))
    assert result.exit_code != 0
    assert "Traceback" not in (result.stdout + result.stderr)


# ===========================================================================
# feedback
# ===========================================================================


def test_feedback_subapp_help(runner: CliRunner) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, ["feedback", "--help"])
    assert result.exit_code == 0, result.stderr
    for sub in ("add", "list"):
        assert sub in result.stdout


def test_feedback_add(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "feedback")
    fake.post.return_value = _resp(
        201,
        {
            "id": "ff",
            "tenant_id": TENANT,
            "routing_id": ROUTING_ID,
            "rating": 5,
            "comment": "great",
            "created_at": "2026-01-01T00:00:00",
        },
    )
    result = runner.invoke(
        app,
        _base(
            "feedback",
            "add",
            "--routing-id",
            ROUTING_ID,
            "--rating",
            "5",
            "--comment",
            "great",
        ),
    )
    assert result.exit_code == 0, result.stderr
    args, kwargs = fake.post.await_args
    assert args[0] == f"/tenants/{TENANT}/feedback"
    body = kwargs["json"]
    assert body["routing_id"] == ROUTING_ID
    assert body["rating"] == 5
    assert body["comment"] == "great"


def test_feedback_add_default_comment(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "feedback")
    fake.post.return_value = _resp(201, {"id": "ff", "rating": 4})
    result = runner.invoke(
        app, _base("feedback", "add", "--routing-id", ROUTING_ID, "--rating", "4")
    )
    assert result.exit_code == 0, result.stderr
    body = fake.post.await_args.kwargs["json"]
    assert body["comment"] == ""


def test_feedback_add_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "feedback")
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
            "feedback",
            "add",
            "--routing-id",
            ROUTING_ID,
            "--rating",
            "3",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake.post.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["method"] == "POST"
    assert payload["body"]["rating"] == 3


def test_feedback_list(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "feedback")
    fake.get.return_value = _resp(200, [{"id": "ff", "rating": 5}])
    result = runner.invoke(app, _base("feedback", "list"))
    assert result.exit_code == 0, result.stderr
    args, kwargs = fake.get.await_args
    assert args[0] == f"/tenants/{TENANT}/feedback"
    assert kwargs["params"] == {"limit": 50, "offset": 0}


def test_feedback_requires_tenant(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "feedback")
    result = runner.invoke(app, ["--url", "http://gw.test", "-o", "json", "feedback", "list"])
    assert result.exit_code != 0


def test_feedback_403_friendly(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "feedback")
    fake.post.return_value = _resp(403, {"detail": "tenant scope missing"})
    result = runner.invoke(
        app,
        _base("feedback", "add", "--routing-id", ROUTING_ID, "--rating", "5"),
    )
    assert result.exit_code != 0
    assert "Traceback" not in (result.stdout + result.stderr)
