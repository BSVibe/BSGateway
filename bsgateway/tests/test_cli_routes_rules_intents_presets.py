"""TASK-009 — ``bsgateway routes / rules / intents / presets`` CLI sub-apps.

Each sub-app is exercised through :class:`typer.testing.CliRunner` with
``build_client`` monkey-patched per module to a ``MagicMock``. The tests
focus on:

* sub-app wiring (subcommands registered + reachable),
* request shape (path / body / params on the mocked client),
* output shape (rendered JSON honours ``--output json``),
* ``--dry-run`` truly skipping HTTP,
* friendly error surface on 4xx (no stack trace, exit code != 0),
* ``--tenant`` enforcement on tenant-scoped commands.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from typer.testing import CliRunner

TENANT = "11111111-1111-1111-1111-111111111111"
RULE_ID = "22222222-2222-2222-2222-222222222222"
INTENT_ID = "33333333-3333-3333-3333-333333333333"


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


# ---------------------------------------------------------------------------
# routes test
# ---------------------------------------------------------------------------


def test_routes_subapp_help(runner: CliRunner) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, ["routes", "--help"])
    assert result.exit_code == 0, result.stderr
    assert "test" in result.stdout


def test_routes_test_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "routes")
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
            "routes",
            "test",
            "--prompt",
            "Explain quantum computing",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake.post.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["method"] == "POST"
    assert payload["path"] == f"/tenants/{TENANT}/rules/test"
    assert payload["body"]["model"] == "auto"
    assert payload["body"]["messages"][0]["content"] == "Explain quantum computing"


def test_routes_test_posts_request(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "routes")
    fake.post.return_value = _resp(
        200,
        {
            "matched_rule": {"id": RULE_ID, "name": "complex", "priority": 10},
            "target_model": "gpt-4o",
            "evaluation_trace": [],
            "context": {"estimated_tokens": 100},
        },
    )
    result = runner.invoke(
        app,
        _base("routes", "test", "--prompt", "hello", "--model", "auto"),
    )
    assert result.exit_code == 0, result.stderr
    fake.post.assert_awaited_once()
    args, kwargs = fake.post.await_args
    assert args[0] == f"/tenants/{TENANT}/rules/test"
    body = kwargs["json"]
    assert body["model"] == "auto"
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    payload = json.loads(result.stdout)
    assert payload["target_model"] == "gpt-4o"


def test_routes_test_with_profile_context(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "routes")
    fake.post.return_value = _resp(
        200, {"matched_rule": None, "target_model": None, "evaluation_trace": [], "context": {}}
    )
    extra = json.dumps([{"role": "system", "content": "be terse"}])
    result = runner.invoke(
        app,
        _base("routes", "test", "--prompt", "hi", "--profile-context", extra),
    )
    assert result.exit_code == 0, result.stderr
    body = fake.post.await_args.kwargs["json"]
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["content"] == "hi"


def test_routes_test_invalid_profile_context_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "routes")
    result = runner.invoke(
        app,
        _base("routes", "test", "--prompt", "x", "--profile-context", "not-json"),
    )
    assert result.exit_code != 0


def test_routes_test_requires_tenant(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "routes")
    result = runner.invoke(
        app,
        ["--url", "http://gw.test", "-o", "json", "routes", "test", "--prompt", "x"],
    )
    assert result.exit_code != 0
    assert "tenant" in (result.stdout + result.stderr).lower()


def test_routes_test_403_friendly(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "routes")
    fake.post.return_value = _resp(403, {"detail": "scope missing: gateway:routing:read"})
    result = runner.invoke(app, _base("routes", "test", "--prompt", "x"))
    assert result.exit_code != 0
    assert "scope missing" in (result.stdout + result.stderr)
    assert "Traceback" not in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------


def test_rules_subapp_help(runner: CliRunner) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, ["rules", "--help"])
    assert result.exit_code == 0, result.stderr
    for sub in ("list", "add", "update", "delete"):
        assert sub in result.stdout


def test_rules_list(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "rules")
    fake.get.return_value = _resp(200, [{"id": RULE_ID, "name": "r1"}])
    result = runner.invoke(app, _base("rules", "list"))
    assert result.exit_code == 0, result.stderr
    fake.get.assert_awaited_once_with(f"/tenants/{TENANT}/rules")
    assert json.loads(result.stdout)[0]["id"] == RULE_ID


def test_rules_list_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "rules")
    result = runner.invoke(
        app,
        ["--url", "http://gw.test", "--tenant", TENANT, "--dry-run", "-o", "json", "rules", "list"],
    )
    assert result.exit_code == 0, result.stderr
    fake.get.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["method"] == "GET"
    assert payload["path"] == f"/tenants/{TENANT}/rules"


def test_rules_add_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "rules")
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
            "rules",
            "add",
            "--name",
            "r1",
            "--priority",
            "10",
            "--target-model",
            "gpt-4o",
            "--default",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake.post.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["method"] == "POST"
    assert payload["path"] == f"/tenants/{TENANT}/rules"
    body = payload["body"]
    assert body["name"] == "r1"
    assert body["priority"] == 10
    assert body["target_model"] == "gpt-4o"
    assert body["is_default"] is True
    assert body["conditions"] == []


def test_rules_add_with_conditions(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "rules")
    fake.post.return_value = _resp(201, {"id": RULE_ID, "name": "r2"})
    conds = json.dumps(
        [
            {
                "condition_type": "token_count",
                "field": "estimated_tokens",
                "operator": "gt",
                "value": 500,
                "negate": False,
            }
        ]
    )
    result = runner.invoke(
        app,
        _base(
            "rules",
            "add",
            "--name",
            "r2",
            "--priority",
            "5",
            "--target-model",
            "gpt-4o",
            "--conditions",
            conds,
        ),
    )
    assert result.exit_code == 0, result.stderr
    body = fake.post.await_args.kwargs["json"]
    assert body["conditions"][0]["operator"] == "gt"


def test_rules_add_invalid_conditions_json(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "rules")
    result = runner.invoke(
        app,
        _base(
            "rules",
            "add",
            "--name",
            "r3",
            "--priority",
            "5",
            "--target-model",
            "gpt-4o",
            "--conditions",
            "not-json",
        ),
    )
    assert result.exit_code != 0


def test_rules_update_only_provided_fields(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "rules")
    fake.request.return_value = _resp(200, {"id": RULE_ID, "name": "r1", "priority": 99})
    result = runner.invoke(app, _base("rules", "update", RULE_ID, "--priority", "99"))
    assert result.exit_code == 0, result.stderr
    method, path = fake.request.await_args.args
    assert method == "PATCH"
    assert path == f"/tenants/{TENANT}/rules/{RULE_ID}"
    assert fake.request.await_args.kwargs["json"] == {"priority": 99}


def test_rules_update_no_args_rejected(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "rules")
    result = runner.invoke(app, _base("rules", "update", RULE_ID))
    assert result.exit_code != 0


def test_rules_delete(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "rules")
    fake.delete.return_value = _resp(204, None)
    result = runner.invoke(app, _base("rules", "delete", RULE_ID))
    assert result.exit_code == 0, result.stderr
    fake.delete.assert_awaited_once_with(f"/tenants/{TENANT}/rules/{RULE_ID}")


def test_rules_delete_404_without_if_exists(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "rules")
    fake.delete.return_value = _resp(404, {"detail": "not found"})
    result = runner.invoke(app, _base("rules", "delete", RULE_ID))
    assert result.exit_code != 0


def test_rules_delete_404_with_if_exists(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "rules")
    fake.delete.return_value = _resp(404, {"detail": "not found"})
    result = runner.invoke(app, _base("rules", "delete", RULE_ID, "--if-exists"))
    assert result.exit_code == 0, result.stderr


def test_rules_403_friendly(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "rules")
    fake.get.return_value = _resp(403, {"detail": "scope missing: gateway:routing:read"})
    result = runner.invoke(app, _base("rules", "list"))
    assert result.exit_code != 0
    assert "scope missing" in (result.stdout + result.stderr)
    assert "Traceback" not in (result.stdout + result.stderr)


def test_rules_requires_tenant(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "rules")
    result = runner.invoke(app, ["--url", "http://gw.test", "-o", "json", "rules", "list"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# intents
# ---------------------------------------------------------------------------


def test_intents_subapp_help(runner: CliRunner) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, ["intents", "--help"])
    assert result.exit_code == 0, result.stderr
    for sub in ("list", "add", "update", "delete"):
        assert sub in result.stdout


def test_intents_list(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "intents")
    fake.get.return_value = _resp(200, [{"id": INTENT_ID, "name": "code-help"}])
    result = runner.invoke(app, _base("intents", "list"))
    assert result.exit_code == 0, result.stderr
    fake.get.assert_awaited_once_with(f"/tenants/{TENANT}/intents")


def test_intents_add(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "intents")
    fake.post.return_value = _resp(
        201,
        {
            "id": INTENT_ID,
            "name": "x",
            "description": "",
            "threshold": 0.7,
            "is_active": True,
            "tenant_id": TENANT,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        },
    )
    result = runner.invoke(
        app,
        _base(
            "intents",
            "add",
            "--name",
            "x",
            "--description",
            "code questions",
            "--threshold",
            "0.8",
            "--example",
            "How do I do foo?",
            "--example",
            "What is bar?",
        ),
    )
    assert result.exit_code == 0, result.stderr
    body = fake.post.await_args.kwargs["json"]
    assert body["name"] == "x"
    assert body["description"] == "code questions"
    assert body["threshold"] == 0.8
    assert body["examples"] == ["How do I do foo?", "What is bar?"]


def test_intents_add_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "intents")
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
            "intents",
            "add",
            "--name",
            "x",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake.post.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["method"] == "POST"
    assert payload["path"] == f"/tenants/{TENANT}/intents"


def test_intents_update(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "intents")
    fake.request.return_value = _resp(200, {"id": INTENT_ID, "threshold": 0.9})
    result = runner.invoke(app, _base("intents", "update", INTENT_ID, "--threshold", "0.9"))
    assert result.exit_code == 0, result.stderr
    method, path = fake.request.await_args.args
    assert method == "PATCH"
    assert path == f"/tenants/{TENANT}/intents/{INTENT_ID}"
    assert fake.request.await_args.kwargs["json"] == {"threshold": 0.9}


def test_intents_update_no_args_rejected(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "intents")
    result = runner.invoke(app, _base("intents", "update", INTENT_ID))
    assert result.exit_code != 0


def test_intents_delete(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "intents")
    fake.delete.return_value = _resp(204, None)
    result = runner.invoke(app, _base("intents", "delete", INTENT_ID))
    assert result.exit_code == 0, result.stderr
    fake.delete.assert_awaited_once_with(f"/tenants/{TENANT}/intents/{INTENT_ID}")


def test_intents_403_friendly(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "intents")
    fake.get.return_value = _resp(403, {"detail": "scope missing: gateway:routing:read"})
    result = runner.invoke(app, _base("intents", "list"))
    assert result.exit_code != 0
    assert "Traceback" not in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# presets
# ---------------------------------------------------------------------------


def test_presets_subapp_help(runner: CliRunner) -> None:
    from bsgateway.cli.main import app

    result = runner.invoke(app, ["presets", "--help"])
    assert result.exit_code == 0, result.stderr
    for sub in ("list", "apply"):
        assert sub in result.stdout


def test_presets_list(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "presets")
    fake.get.return_value = _resp(
        200,
        [{"name": "starter", "description": "demo", "intent_count": 2, "rule_count": 1}],
    )
    result = runner.invoke(
        app,
        ["--url", "http://gw.test", "--token", "tok", "-o", "json", "presets", "list"],
    )
    assert result.exit_code == 0, result.stderr
    fake.get.assert_awaited_once_with("/presets")
    assert json.loads(result.stdout)[0]["name"] == "starter"


def test_presets_apply_dry_run(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "presets")
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
            "presets",
            "apply",
            "--preset",
            "starter",
            "--economy",
            "ollama_chat/qwen3:1b",
            "--balanced",
            "ollama_chat/qwen3:8b",
            "--premium",
            "gpt-4o",
        ],
    )
    assert result.exit_code == 0, result.stderr
    fake.post.assert_not_awaited()
    payload = json.loads(result.stdout)
    assert payload["method"] == "POST"
    assert payload["path"] == f"/tenants/{TENANT}/presets/apply"
    body = payload["body"]
    assert body["preset_name"] == "starter"
    assert body["model_mapping"] == {
        "economy": "ollama_chat/qwen3:1b",
        "balanced": "ollama_chat/qwen3:8b",
        "premium": "gpt-4o",
    }


def test_presets_apply_posts_request(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "presets")
    fake.post.return_value = _resp(
        201,
        {"preset_name": "starter", "rules_created": 1, "intents_created": 2, "examples_created": 5},
    )
    result = runner.invoke(
        app,
        _base(
            "presets",
            "apply",
            "--preset",
            "starter",
            "--economy",
            "a",
            "--balanced",
            "b",
            "--premium",
            "c",
        ),
    )
    assert result.exit_code == 0, result.stderr
    args, kwargs = fake.post.await_args
    assert args[0] == f"/tenants/{TENANT}/presets/apply"
    assert kwargs["json"]["preset_name"] == "starter"


def test_presets_apply_requires_tenant(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    _fake(monkeypatch, "presets")
    result = runner.invoke(
        app,
        [
            "--url",
            "http://gw.test",
            "-o",
            "json",
            "presets",
            "apply",
            "--preset",
            "x",
            "--economy",
            "a",
            "--balanced",
            "b",
            "--premium",
            "c",
        ],
    )
    assert result.exit_code != 0


def test_presets_apply_403_friendly(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from bsgateway.cli.main import app

    fake = _fake(monkeypatch, "presets")
    fake.post.return_value = _resp(403, {"detail": "scope missing: gateway:routing:write"})
    result = runner.invoke(
        app,
        _base(
            "presets",
            "apply",
            "--preset",
            "x",
            "--economy",
            "a",
            "--balanced",
            "b",
            "--premium",
            "c",
        ),
    )
    assert result.exit_code != 0
    assert "scope missing" in (result.stdout + result.stderr)
    assert "Traceback" not in (result.stdout + result.stderr)
