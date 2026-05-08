"""Phase 3 / TASK-012 — end-to-end dogfood loop.

Verifies that an AI agent (Claude Code, opencode) running the
``bsgateway`` CLI against a live control-plane sees the registry react
in real time, with no process restart between mutations:

  CLI add  → POST /admin/models → repo write → registry.invalidate
                                              → registry.list_models
                                              → router._effective_passthrough_set
                                                resolves the new name as
                                                passthrough.
  CLI rm   → DELETE /admin/models/{id}
                                              → registry.invalidate
                                              → router._effective_passthrough_set
                                                no longer carries it.

The wiring intentionally stays close to production:

* a real :class:`ModelRegistryService` with the default 60s LRU TTL,
  backed by an in-memory fake repo that mirrors the asyncpg
  :class:`ModelsRepository` surface,
* the real :mod:`bsgateway.api.routers.models` router mounted on a
  :class:`fastapi.testclient.TestClient` app,
* a real :class:`bsvibe_cli_base.CliHttpClient` whose underlying
  :class:`httpx.AsyncClient` is bound to :class:`httpx.ASGITransport` so
  the CLI talks directly to the in-memory FastAPI app — no live
  socket, no extra mocking layer between the CLI surface and the REST
  surface,
* a real :class:`BSGatewayRouter` with ``attach_registry`` pointing at
  the same registry instance the admin REST writes through, exercising
  the actual passthrough resolution path.

Step "POST /v1/chat/completions resolves it" is expressed via the
router's ``_effective_passthrough_set`` rather than the FastAPI
``/v1/chat/completions`` endpoint because that endpoint resolves
through ``ChatService.complete`` which keys off the legacy
``tenant_models`` table — a separate registry from the Phase 3
yaml-union-DB merge. The contract under test ("registry mutations
reach the routing decision without a process restart") lives in the
router's passthrough check, so we exercise it directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from bsvibe_cli_base import CliHttpClient
from bsvibe_core import configure_logging
from typer.testing import CliRunner

from bsgateway.api.app import create_app
from bsgateway.api.deps import get_auth_context, get_model_registry
from bsgateway.routing.hook import BSGatewayRouter
from bsgateway.routing.models import (
    ClassifierConfig,
    ClassifierWeights,
    CollectorConfig,
    RoutingConfig,
    TierConfig,
)
from bsgateway.routing.registry import DbModelRow, ModelRegistryService
from bsgateway.tests.conftest import make_gateway_auth_context, make_mock_pool

ENCRYPTION_KEY_HEX = os.urandom(32).hex()


@pytest.fixture(autouse=True)
def _redirect_structlog_to_stderr():
    """Pin structlog output to stderr for these tests.

    The default structlog factory writes to ``sys.stdout``. CliRunner
    captures stdout, so log lines pollute the JSON the CLI emits and
    break ``json.loads(result.stdout)``. Redirecting to stderr keeps
    the CLI surface clean while still letting test output show logs
    via pytest's ``-s`` mode.
    """

    configure_logging(level="warning", json_output=True, stream=sys.stderr)
    yield


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _InMemoryModelsRepo:
    """In-memory fake matching :class:`ModelsRepository`'s surface.

    Both the admin router (writes) and :class:`ModelRegistryService`
    (reads) point at the *same* instance so a CLI-driven mutation is
    visible to the registry on its very next ``list_models`` call.
    """

    def __init__(self) -> None:
        self._rows: dict[UUID, dict[str, Any]] = {}

    async def list_for_tenant(self, tenant_id: UUID) -> list[DbModelRow]:
        out: list[DbModelRow] = []
        for row in self._rows.values():
            if row["tenant_id"] != tenant_id:
                continue
            out.append(
                DbModelRow(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    name=row["name"],
                    origin=row["origin"],
                    litellm_model=row["litellm_model"],
                    litellm_params=row["litellm_params"],
                    is_passthrough=row["is_passthrough"],
                )
            )
        return out

    async def get_model(self, model_id: UUID, tenant_id: UUID) -> dict | None:
        row = self._rows.get(model_id)
        if row is None or row["tenant_id"] != tenant_id:
            return None
        return dict(row)

    async def create_model(
        self,
        *,
        tenant_id: UUID,
        name: str,
        origin: str,
        litellm_model: str | None,
        litellm_params: dict | None,
        is_passthrough: bool,
    ) -> dict:
        new_id = uuid4()
        now = datetime.now(UTC)
        row: dict[str, Any] = {
            "id": new_id,
            "tenant_id": tenant_id,
            "name": name,
            "origin": origin,
            "litellm_model": litellm_model,
            "litellm_params": litellm_params,
            "is_passthrough": is_passthrough,
            "created_at": now,
            "updated_at": now,
        }
        self._rows[new_id] = row
        return dict(row)

    async def update_model(
        self,
        *,
        model_id: UUID,
        tenant_id: UUID,
        name: str | None = None,
        origin: str | None = None,
        litellm_model: str | None = None,
        litellm_params: dict | None = None,
        is_passthrough: bool | None = None,
        litellm_model_set: bool = False,
        litellm_params_set: bool = False,
    ) -> dict | None:
        row = self._rows.get(model_id)
        if row is None or row["tenant_id"] != tenant_id:
            return None
        if name is not None:
            row["name"] = name
        if origin is not None:
            row["origin"] = origin
        if litellm_model_set:
            row["litellm_model"] = litellm_model
        if litellm_params_set:
            row["litellm_params"] = litellm_params
        if is_passthrough is not None:
            row["is_passthrough"] = is_passthrough
        row["updated_at"] = datetime.now(UTC)
        return dict(row)

    async def delete_model(self, model_id: UUID, tenant_id: UUID) -> bool:
        row = self._rows.get(model_id)
        if row is None or row["tenant_id"] != tenant_id:
            return False
        del self._rows[model_id]
        return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant_id() -> UUID:
    return uuid4()


@pytest.fixture
def fake_repo(monkeypatch: pytest.MonkeyPatch) -> _InMemoryModelsRepo:
    repo = _InMemoryModelsRepo()
    # Both the create-path and the read-path on the admin router resolve
    # the repo via this helper. Pinning it to the same instance the
    # registry consumes is what makes the e2e meaningful.
    monkeypatch.setattr(
        "bsgateway.api.routers.models._get_repo",
        lambda request: repo,
    )
    return repo


@pytest.fixture
def registry(fake_repo: _InMemoryModelsRepo) -> ModelRegistryService:
    # No yaml entries — keeps the assertion surface tight: every
    # passthrough name in the effective set is one the CLI just added.
    return ModelRegistryService(yaml_models=[], repo=fake_repo, cache_ttl_s=60)


@pytest.fixture
def app(
    tenant_id: UUID,
    registry: ModelRegistryService,
    fake_repo: _InMemoryModelsRepo,
    monkeypatch: pytest.MonkeyPatch,
):
    """FastAPI app wired with admin auth + shared registry + fake repo.

    AuditService.record + audit_publisher.emit_event are patched to
    AsyncMock — the e2e contract is the registry mutation, not the
    audit row, and the audit machinery has its own dedicated suite.
    """

    monkeypatch.setattr(
        "bsgateway.audit.service.AuditService.record",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "bsgateway.api.routers.models.emit_event",
        AsyncMock(return_value=None),
    )

    pool, _ = make_mock_pool()
    app = create_app()
    app.state.db_pool = pool
    app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    app.state.redis = None
    app.state.model_registry = registry

    admin_ctx = make_gateway_auth_context(tenant_id=tenant_id, is_admin=True)
    app.dependency_overrides[get_auth_context] = lambda: admin_ctx
    app.dependency_overrides[get_model_registry] = lambda: registry
    return app


@pytest.fixture
def make_cli_http(app):
    """Return a callable that builds a fresh ``CliHttpClient`` per CLI invocation.

    ``CliHttpClient.aclose`` is awaited inside each sub-command's ``_go``
    helper, so the client is single-use. The ASGI transport itself is
    stateless w.r.t. the FastAPI app instance, so reusing ``app`` across
    invocations is safe.
    """

    def _factory(_ctx: object) -> CliHttpClient:
        # The admin REST is mounted under ``/api/v1`` in ``create_app``.
        # The CLI sub-commands send paths like ``/admin/models`` (no
        # version prefix), so the base_url must absorb the ``/api/v1``
        # half — exactly how operators configure ``--url`` in production.
        transport = httpx.ASGITransport(app=app)
        http = httpx.AsyncClient(transport=transport, base_url="http://gw.test/api/v1")
        return CliHttpClient(base_url="http://gw.test/api/v1", token="tok", http=http)

    return _factory


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


@pytest.fixture
def cli_app(make_cli_http, monkeypatch: pytest.MonkeyPatch):
    """Patch ``build_client`` on the models sub-app to the in-memory factory.

    ``models`` is the only sub-app the e2e exercises; pinning the patch
    to that one module keeps the blast radius small.
    """

    monkeypatch.setattr(
        "bsgateway.cli.commands.models.build_client",
        make_cli_http,
    )

    from bsgateway.cli.main import app as cli_root

    return cli_root


def _routing_config() -> RoutingConfig:
    """Minimal RoutingConfig for a router that consults the registry."""

    return RoutingConfig(
        tiers=[
            TierConfig(name="simple", score_range=(0, 30), model="local/llama3"),
            TierConfig(name="medium", score_range=(31, 65), model="gpt-4o-mini"),
            TierConfig(name="complex", score_range=(66, 100), model="claude-opus"),
        ],
        aliases={"auto": "auto_route"},
        passthrough_models={"local/llama3", "gpt-4o-mini", "claude-opus"},
        classifier=ClassifierConfig(
            weights=ClassifierWeights(),
            complex_keywords=["architect"],
            simple_keywords=["hello"],
        ),
        fallback_tier="medium",
        classifier_strategy="static",
        collector=CollectorConfig(enabled=False),
        yaml_model_list=[],
    )


# ---------------------------------------------------------------------------
# E2E
# ---------------------------------------------------------------------------


def _base_args(*extra: str) -> list[str]:
    return ["--url", "http://gw.test", "--token", "tok", "-o", "json", *extra]


def _run(coro: Any) -> Any:
    """Bridge async helpers into the sync test body.

    The CLI sub-commands themselves call ``asyncio.run`` internally, so
    the test must be synchronous; we drive registry / router assertions
    through a small ``asyncio.run`` shim here.
    """

    return asyncio.run(coro)


def test_cli_add_invalidates_and_router_resolves(
    runner: CliRunner,
    cli_app: Any,
    registry: ModelRegistryService,
    tenant_id: UUID,
) -> None:
    """End-to-end loop: CLI add → registry → router passthrough decision."""

    # Sanity: starting state — no custom models → router does NOT consider
    # the soon-to-be-added name as a passthrough yet.
    initial_set = _run(registry.get_passthrough_set(tenant_id))
    assert "custom/foo" not in initial_set

    # 1. `bsgateway models add` — POST /admin/models via the in-memory
    # ASGI transport. Returns the freshly created row as JSON.
    add_result = runner.invoke(
        cli_app,
        _base_args(
            "models",
            "add",
            "--name",
            "custom/foo",
            "--provider",
            "ollama_chat/qwen3",
        ),
    )
    assert add_result.exit_code == 0, add_result.stderr
    created = json.loads(add_result.stdout)
    assert created["name"] == "custom/foo"
    assert created["origin"] == "custom"
    assert created["is_passthrough"] is True
    model_id = created["id"]

    # 2. The router's passthrough decision now includes the new model
    # without an app restart — i.e. registry.invalidate + next read
    # picked up the row.
    refreshed = _run(registry.get_passthrough_set(tenant_id))
    assert "custom/foo" in refreshed

    # 3. Hook-level passthrough resolution mirrors the registry. The
    # router constructed here shares the same registry instance.
    router = BSGatewayRouter(config=_routing_config())
    router.attach_registry(registry)
    request_data = {
        "model": "custom/foo",
        "messages": [{"role": "user", "content": "hello"}],
        "metadata": {"tenant_id": str(tenant_id)},
    }
    decision = _run(
        router._route(
            requested_model="custom/foo",
            data=request_data,
        )
    )
    assert decision.method == "passthrough"
    assert decision.resolved_model == "custom/foo"

    # 4. `bsgateway models list -o json` — JSON pipeline survives `jq`.
    list_result = runner.invoke(cli_app, _base_args("models", "list"))
    assert list_result.exit_code == 0, list_result.stderr
    listed = json.loads(list_result.stdout)
    assert isinstance(listed, list)
    assert any(m["name"] == "custom/foo" for m in listed)
    # Provider credentials must never round-trip through the list response.
    assert "litellm_params" not in listed[0]

    # 5. `bsgateway models remove <id>` — DELETE /admin/models/{id}.
    remove_result = runner.invoke(cli_app, _base_args("models", "remove", model_id))
    assert remove_result.exit_code == 0, remove_result.stderr

    # 6. After delete the registry reflects the absence on the next read
    # — the router no longer treats the name as passthrough.
    cleared = _run(registry.get_passthrough_set(tenant_id))
    assert "custom/foo" not in cleared

    decision_after_remove = _run(
        router._route(
            requested_model="custom/foo",
            data={
                "model": "custom/foo",
                "messages": [{"role": "user", "content": "hello"}],
                "metadata": {"tenant_id": str(tenant_id)},
            },
        )
    )
    # Falls into auto-route since "custom/foo" is no longer passthrough
    # and there's no alias for it.
    assert decision_after_remove.method != "passthrough"


def test_cli_remove_idempotent_with_if_exists(
    runner: CliRunner,
    cli_app: Any,
) -> None:
    """``--if-exists`` swallows a 404 so the dogfood loop is replay-safe."""

    bogus_id = "00000000-0000-0000-0000-000000000999"
    result = runner.invoke(cli_app, _base_args("models", "remove", bogus_id, "--if-exists"))
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"deleted": False, "id": bogus_id, "reason": "not_found"}


def test_cli_dry_run_skips_http(
    runner: CliRunner,
    cli_app: Any,
    fake_repo: _InMemoryModelsRepo,
) -> None:
    """``--dry-run`` short-circuits the HTTP layer entirely.

    The repo MUST be untouched after a dry-run add — proves the CLI
    surface honors ``--dry-run`` even with a fully wired in-memory app
    behind ``build_client``.
    """

    result = runner.invoke(
        cli_app,
        [
            "--url",
            "http://gw.test",
            "--token",
            "tok",
            "--dry-run",
            "-o",
            "json",
            "models",
            "add",
            "--name",
            "custom/never-persists",
            "--provider",
            "ollama_chat/foo",
        ],
    )
    assert result.exit_code == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["dry_run"] is True
    assert body["method"] == "POST"
    assert body["body"]["name"] == "custom/never-persists"
    # The repo MUST NOT have been written to.
    assert fake_repo._rows == {}
