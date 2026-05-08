"""Tests for ``ModelRegistryService`` — Phase 3 / TASK-003.

The service merges the operator-managed yaml model list with per-tenant
DB rows (``custom`` additions and ``hide_system`` subtractions) behind a
60-second per-tenant cache. Tests cover the merge contract, cache hit /
miss / TTL behavior, invalidate semantics, and miss coalescing under
concurrent callers.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from bsgateway.routing.registry import (
    DbModelRow,
    ModelEntry,
    ModelRegistryService,
)

YAML_MODELS = [
    {"name": "claude-haiku", "litellm_model": "anthropic/claude-haiku-4-5"},
    {"name": "gpt-5", "litellm_model": "openai/gpt-5"},
]


class _FakeRepo:
    """Minimal repo stub that records every call."""

    def __init__(self, rows_per_tenant: dict[UUID, list[DbModelRow]] | None = None) -> None:
        self.calls: list[UUID] = []
        self._rows = rows_per_tenant or {}

    def set_rows(self, tenant_id: UUID, rows: list[DbModelRow]) -> None:
        self._rows[tenant_id] = rows

    async def list_for_tenant(self, tenant_id: UUID) -> list[DbModelRow]:
        self.calls.append(tenant_id)
        return list(self._rows.get(tenant_id, []))


def _row(
    *,
    tenant: UUID,
    name: str,
    origin: str,
    is_passthrough: bool = True,
    litellm_model: str | None = None,
    litellm_params: dict | None = None,
) -> DbModelRow:
    return DbModelRow(
        id=uuid4(),
        tenant_id=tenant,
        name=name,
        origin=origin,
        litellm_model=litellm_model,
        litellm_params=litellm_params,
        is_passthrough=is_passthrough,
    )


async def test_yaml_only_tenant_lists_every_system_model() -> None:
    tenant = uuid4()
    repo = _FakeRepo()
    svc = ModelRegistryService(yaml_models=YAML_MODELS, repo=repo)

    models = await svc.list_models(tenant)

    by_name = {m.name: m for m in models}
    assert set(by_name) == {"claude-haiku", "gpt-5"}
    assert all(m.origin == "system" for m in models)
    assert all(m.is_passthrough for m in models)
    assert by_name["gpt-5"].litellm_model == "openai/gpt-5"
    assert await svc.get_passthrough_set(tenant) == {"claude-haiku", "gpt-5"}


async def test_custom_addition_appears_alongside_system_models() -> None:
    tenant = uuid4()
    repo = _FakeRepo(
        {
            tenant: [
                _row(
                    tenant=tenant,
                    name="custom/foo",
                    origin="custom",
                    litellm_model="ollama_chat/foo",
                    litellm_params={"api_base": "http://x"},
                )
            ]
        }
    )
    svc = ModelRegistryService(yaml_models=YAML_MODELS, repo=repo)

    models = await svc.list_models(tenant)

    by_origin: dict[str, list[ModelEntry]] = {"system": [], "custom": []}
    for m in models:
        by_origin[m.origin].append(m)
    assert {m.name for m in by_origin["system"]} == {"claude-haiku", "gpt-5"}
    assert [m.name for m in by_origin["custom"]] == ["custom/foo"]
    assert "custom/foo" in await svc.get_passthrough_set(tenant)


async def test_hide_system_subtracts_yaml_entry_from_listing_and_passthrough() -> None:
    tenant = uuid4()
    repo = _FakeRepo(
        {
            tenant: [
                _row(
                    tenant=tenant,
                    name="gpt-5",
                    origin="hide_system",
                    is_passthrough=False,
                )
            ]
        }
    )
    svc = ModelRegistryService(yaml_models=YAML_MODELS, repo=repo)

    models = await svc.list_models(tenant)

    assert {m.name for m in models} == {"claude-haiku"}
    assert await svc.get_passthrough_set(tenant) == {"claude-haiku"}


async def test_custom_with_same_name_overrides_yaml_entry() -> None:
    tenant = uuid4()
    repo = _FakeRepo(
        {
            tenant: [
                _row(
                    tenant=tenant,
                    name="gpt-5",
                    origin="custom",
                    litellm_model="azure/gpt-5",
                    litellm_params={"api_base": "https://contoso"},
                )
            ]
        }
    )
    svc = ModelRegistryService(yaml_models=YAML_MODELS, repo=repo)

    models = await svc.list_models(tenant)

    by_name = {m.name: m for m in models}
    assert by_name["gpt-5"].origin == "custom"
    assert by_name["gpt-5"].litellm_model == "azure/gpt-5"
    assert by_name["claude-haiku"].origin == "system"
    assert "gpt-5" in await svc.get_passthrough_set(tenant)


async def test_non_passthrough_custom_excluded_from_passthrough_set() -> None:
    tenant = uuid4()
    repo = _FakeRepo(
        {
            tenant: [
                _row(
                    tenant=tenant,
                    name="custom/no-pass",
                    origin="custom",
                    is_passthrough=False,
                    litellm_model="ollama_chat/no-pass",
                ),
            ]
        }
    )
    svc = ModelRegistryService(yaml_models=YAML_MODELS, repo=repo)

    pset = await svc.get_passthrough_set(tenant)

    assert "custom/no-pass" not in pset
    assert pset == {"claude-haiku", "gpt-5"}


async def test_repeated_calls_within_ttl_hit_cache() -> None:
    tenant = uuid4()
    repo = _FakeRepo()
    svc = ModelRegistryService(yaml_models=YAML_MODELS, repo=repo)

    await svc.list_models(tenant)
    await svc.list_models(tenant)
    await svc.get_passthrough_set(tenant)

    assert repo.calls == [tenant]


async def test_cache_ttl_expiry_triggers_refetch() -> None:
    tenant = uuid4()
    repo = _FakeRepo()
    now = [1000.0]
    svc = ModelRegistryService(
        yaml_models=YAML_MODELS,
        repo=repo,
        cache_ttl_s=60,
        clock=lambda: now[0],
    )

    await svc.list_models(tenant)
    now[0] += 30
    await svc.list_models(tenant)
    assert len(repo.calls) == 1

    now[0] += 31
    await svc.list_models(tenant)
    assert len(repo.calls) == 2


async def test_invalidate_clears_only_target_tenant() -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    repo = _FakeRepo()
    svc = ModelRegistryService(yaml_models=YAML_MODELS, repo=repo)

    await svc.list_models(tenant_a)
    await svc.list_models(tenant_b)
    assert len(repo.calls) == 2

    await svc.invalidate(tenant_a)
    await svc.list_models(tenant_a)
    await svc.list_models(tenant_b)

    assert repo.calls.count(tenant_a) == 2
    assert repo.calls.count(tenant_b) == 1


async def test_invalidate_after_repo_change_returns_new_set() -> None:
    tenant = uuid4()
    repo = _FakeRepo()
    svc = ModelRegistryService(yaml_models=YAML_MODELS, repo=repo)

    assert "custom/late" not in await svc.get_passthrough_set(tenant)

    repo.set_rows(
        tenant,
        [
            _row(
                tenant=tenant,
                name="custom/late",
                origin="custom",
                litellm_model="ollama_chat/late",
            )
        ],
    )
    assert "custom/late" not in await svc.get_passthrough_set(tenant)

    await svc.invalidate(tenant)
    assert "custom/late" in await svc.get_passthrough_set(tenant)


async def test_concurrent_misses_coalesce_to_single_repo_call() -> None:
    tenant = uuid4()
    barrier = asyncio.Event()

    class _SlowRepo:
        def __init__(self) -> None:
            self.calls = 0

        async def list_for_tenant(self, tenant_id: UUID) -> list[DbModelRow]:
            self.calls += 1
            await barrier.wait()
            return []

    repo = _SlowRepo()
    svc = ModelRegistryService(yaml_models=YAML_MODELS, repo=repo)

    t1 = asyncio.create_task(svc.list_models(tenant))
    t2 = asyncio.create_task(svc.list_models(tenant))
    await asyncio.sleep(0.01)
    barrier.set()
    await asyncio.gather(t1, t2)

    assert repo.calls == 1


async def test_list_models_returns_immutable_snapshot_per_call() -> None:
    """Mutating a returned list MUST NOT corrupt the cached entry."""
    tenant = uuid4()
    repo = _FakeRepo()
    svc = ModelRegistryService(yaml_models=YAML_MODELS, repo=repo)

    first = await svc.list_models(tenant)
    first.clear()  # caller mutating its own copy

    second = await svc.list_models(tenant)
    assert {m.name for m in second} == {"claude-haiku", "gpt-5"}


@pytest.mark.parametrize("bad_origin", ["unknown", "hidden", ""])
async def test_unknown_origin_rows_are_ignored(bad_origin: str) -> None:
    tenant = uuid4()
    repo = _FakeRepo(
        {
            tenant: [
                _row(
                    tenant=tenant,
                    name="weird",
                    origin=bad_origin,
                    litellm_model="x/y",
                ),
            ]
        }
    )
    svc = ModelRegistryService(yaml_models=YAML_MODELS, repo=repo)

    models = await svc.list_models(tenant)

    assert "weird" not in {m.name for m in models}
