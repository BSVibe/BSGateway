"""Phase 3 / TASK-004 — ``BSGatewayRouter`` x ``ModelRegistryService`` wiring.

The router consumes the operator-managed yaml passthrough set today.
TASK-004 attaches the per-tenant registry on top so a tenant can:

* see its own ``custom`` rows resolved as passthrough,
* have ``hide_system`` rows blank a yaml entry from the passthrough set,
* and observe model adds **without an app restart** — once the admin
  router (TASK-005) writes a row and calls ``registry.invalidate``, the
  next request through the hook re-reads the catalog.

These tests pin the contract:

* Registry attached + tenant_id in request metadata → registry decides.
* Registry attached but no tenant_id → fall back to yaml-only baseline
  so existing proxy-direct traffic does not regress.
* Registry detached → behavior identical to the pre-Phase-3 baseline
  (verified implicitly by the entire ``test_hook.py`` suite continuing
  to pass; the explicit ``test_router_without_registry_uses_yaml_only``
  case below pins the same invariant in this file).
* Tier models always pass through — hiding them via ``hide_system`` is
  not a supported subtraction (operator policy beats tenant override).
* Tier models override registry — even if a tenant adds a `custom` row
  for the same name, dispatching to that model resolves to the tier's
  litellm payload because routing decision happens upstream of the
  registry. Registry only governs whether the name is passthrough.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from bsgateway.routing.hook import BSGatewayRouter
from bsgateway.routing.models import (
    ClassifierConfig,
    ClassifierWeights,
    CollectorConfig,
    RoutingConfig,
    TierConfig,
)
from bsgateway.routing.registry import DbModelRow, ModelRegistryService

YAML_MODELS = [
    {"name": "gpt-4o-mini", "litellm_model": "openai/gpt-4o-mini"},
    {"name": "claude-haiku", "litellm_model": "anthropic/claude-haiku-4-5"},
]


class _FakeRepo:
    """Minimal ModelsRepository stub backed by an in-memory dict.

    The Phase 3 admin router (TASK-005) will write through a real
    asyncpg-backed repo. For TASK-004 we only need to exercise the
    read path the registry consumes.
    """

    def __init__(self) -> None:
        self._rows: dict[UUID, list[DbModelRow]] = {}

    def add(self, row: DbModelRow) -> None:
        self._rows.setdefault(row.tenant_id, []).append(row)

    def clear(self, tenant_id: UUID) -> None:
        self._rows.pop(tenant_id, None)

    async def list_for_tenant(self, tenant_id: UUID) -> list[DbModelRow]:
        return list(self._rows.get(tenant_id, []))


@pytest.fixture
def routing_config() -> RoutingConfig:
    return RoutingConfig(
        tiers=[
            TierConfig(name="simple", score_range=(0, 30), model="local/llama3"),
            TierConfig(name="medium", score_range=(31, 65), model="gpt-4o-mini"),
            TierConfig(name="complex", score_range=(66, 100), model="claude-opus"),
        ],
        aliases={"auto": "auto_route"},
        passthrough_models={
            "local/llama3",
            "gpt-4o-mini",
            "claude-opus",
            "claude-haiku",
        },
        classifier=ClassifierConfig(
            weights=ClassifierWeights(),
            complex_keywords=["architect"],
            simple_keywords=["hello"],
        ),
        fallback_tier="medium",
        classifier_strategy="static",
        collector=CollectorConfig(enabled=False),
        yaml_model_list=YAML_MODELS,
    )


@pytest.fixture
def router(routing_config: RoutingConfig) -> BSGatewayRouter:
    return BSGatewayRouter(config=routing_config)


def _build_registry(
    repo: _FakeRepo,
    *,
    yaml_models: list[dict] | None = None,
) -> ModelRegistryService:
    return ModelRegistryService(
        yaml_models=yaml_models if yaml_models is not None else YAML_MODELS,
        repo=repo,
    )


@pytest.mark.asyncio
async def test_router_without_registry_uses_yaml_only(
    router: BSGatewayRouter,
) -> None:
    """No registry attached → behavior matches the pre-Phase-3 baseline."""
    data = {
        "model": "claude-haiku",
        "messages": [{"role": "user", "content": "hi"}],
    }

    result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

    assert result["model"] == "claude-haiku"
    assert result["metadata"]["routing_decision"]["method"] == "passthrough"


@pytest.mark.asyncio
async def test_attach_registry_idempotent_on_none(
    router: BSGatewayRouter,
) -> None:
    """``attach_registry(None)`` is a no-op so lifespan can re-run safely."""
    router.attach_registry(None)
    assert router.registry is None

    repo = _FakeRepo()
    registry = _build_registry(repo)
    router.attach_registry(registry)
    assert router.registry is registry

    router.attach_registry(None)
    assert router.registry is registry


@pytest.mark.asyncio
async def test_registry_attached_no_tenant_falls_back_to_yaml(
    router: BSGatewayRouter,
) -> None:
    """Registry attached + no tenant in metadata → yaml-only baseline.

    Proxy-direct traffic that does not carry a tenant_id (e.g. the local
    devserver master-key path) MUST keep working; we never block
    requests on a missing per-tenant view.
    """
    repo = _FakeRepo()
    router.attach_registry(_build_registry(repo))

    data = {
        "model": "claude-haiku",
        "messages": [{"role": "user", "content": "hi"}],
    }

    result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

    assert result["metadata"]["routing_decision"]["method"] == "passthrough"


@pytest.mark.asyncio
async def test_custom_model_invalidate_then_resolved_no_restart(
    router: BSGatewayRouter,
) -> None:
    """The Phase 3 dogfood promise: add a model, invalidate, route to it.

    1. New tenant has no custom rows → custom name is unknown → auto-route.
    2. Insert a ``custom`` row directly in the repo (the TASK-005 admin
       router will do this in production).
    3. ``registry.invalidate(tenant_id)`` evicts the cached entry — the
       next request triggers a fresh merge and the name passes through.
    """
    tenant = uuid4()
    repo = _FakeRepo()
    registry = _build_registry(repo)
    router.attach_registry(registry)

    data_before = {
        "model": "custom/foo",
        "messages": [{"role": "user", "content": "hello"}],
        "metadata": {"tenant_id": str(tenant)},
    }
    before = await router.async_pre_call_hook(MagicMock(), MagicMock(), data_before, "completion")
    assert before["metadata"]["routing_decision"]["method"] == "auto"

    repo.add(
        DbModelRow(
            id=uuid4(),
            tenant_id=tenant,
            name="custom/foo",
            origin="custom",
            litellm_model="ollama/foo",
            litellm_params=None,
            is_passthrough=True,
        )
    )
    await registry.invalidate(tenant)

    data_after = {
        "model": "custom/foo",
        "messages": [{"role": "user", "content": "hello"}],
        "metadata": {"tenant_id": str(tenant)},
    }
    after = await router.async_pre_call_hook(MagicMock(), MagicMock(), data_after, "completion")
    assert after["model"] == "custom/foo"
    assert after["metadata"]["routing_decision"]["method"] == "passthrough"


@pytest.mark.asyncio
async def test_hide_system_drops_model_from_tenant_passthrough(
    router: BSGatewayRouter,
) -> None:
    """A ``hide_system`` row removes the yaml entry for one tenant.

    The yaml entry stays passthrough for every other tenant; the hiding
    tenant's request falls through to alias/auto-route instead.
    """
    tenant = uuid4()
    other = uuid4()
    repo = _FakeRepo()
    registry = _build_registry(repo)
    router.attach_registry(registry)

    repo.add(
        DbModelRow(
            id=uuid4(),
            tenant_id=tenant,
            name="claude-haiku",
            origin="hide_system",
            litellm_model=None,
            litellm_params=None,
            is_passthrough=True,
        )
    )

    hidden = await router.async_pre_call_hook(
        MagicMock(),
        MagicMock(),
        {
            "model": "claude-haiku",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"tenant_id": str(tenant)},
        },
        "completion",
    )
    assert hidden["metadata"]["routing_decision"]["method"] == "auto"

    visible = await router.async_pre_call_hook(
        MagicMock(),
        MagicMock(),
        {
            "model": "claude-haiku",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"tenant_id": str(other)},
        },
        "completion",
    )
    assert visible["metadata"]["routing_decision"]["method"] == "passthrough"


@pytest.mark.asyncio
async def test_tier_models_always_passthrough_regardless_of_registry(
    router: BSGatewayRouter,
) -> None:
    """Operator tier policy beats tenant override.

    Even if a tenant tries to ``hide_system`` a tier model the routing
    layer keeps it as passthrough — tier models are routing targets, not
    just catalog entries, and removing them would brick auto-routing.
    """
    tenant = uuid4()
    repo = _FakeRepo()
    # Note: yaml here intentionally omits tier models so we know the
    # only reason 'gpt-4o-mini' stays passthrough is the tier override.
    registry = _build_registry(repo, yaml_models=[])
    router.attach_registry(registry)

    repo.add(
        DbModelRow(
            id=uuid4(),
            tenant_id=tenant,
            name="gpt-4o-mini",
            origin="hide_system",
            litellm_model=None,
            litellm_params=None,
            is_passthrough=True,
        )
    )

    result = await router.async_pre_call_hook(
        MagicMock(),
        MagicMock(),
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"tenant_id": str(tenant)},
        },
        "completion",
    )

    assert result["metadata"]["routing_decision"]["method"] == "passthrough"


@pytest.mark.asyncio
async def test_invalid_tenant_id_in_metadata_falls_back_to_yaml(
    router: BSGatewayRouter,
) -> None:
    """Garbage tenant_id in metadata → no registry hit, yaml baseline only."""
    repo = _FakeRepo()
    router.attach_registry(_build_registry(repo))

    data = {
        "model": "claude-haiku",
        "messages": [{"role": "user", "content": "hi"}],
        "metadata": {"tenant_id": "not-a-uuid"},
    }

    result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
    assert result["metadata"]["routing_decision"]["method"] == "passthrough"
