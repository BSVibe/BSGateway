"""Phase 3 / TASK-003 — yaml-union-DB model registry.

The Phase 3 control plane treats ``gateway.yaml`` as the operator-managed
**system** half of the model catalog and the new ``models`` table
(alembic ``0004_models_and_tenant_isolation``) as the per-tenant half.
``ModelRegistryService`` merges the two for every routing decision and
hides the merge cost behind a 60-second per-tenant TTL cache.

Merge contract — keep these invariants in sync with §Phase 3 of the
*BSVibe AI-Native Control Plane Plan*:

* yaml entries are visible to every tenant unless that tenant has shadowed
  them with a ``hide_system`` row or replaced them with a ``custom`` row
  of the same name.
* DB rows with ``origin='custom'`` add (or override) entries for one
  tenant. They carry a full litellm payload (``litellm_model`` /
  ``litellm_params``) and an explicit ``is_passthrough`` flag.
* DB rows with ``origin='hide_system'`` subtract the matching yaml entry
  for one tenant. They carry no payload — the row only exists to remove a
  name from the effective set.
* If a tenant has both a ``custom`` row and a ``hide_system`` row for the
  same name, the ``custom`` row wins (the visible-by-replacement read of
  the merge: hiding only matters for entries we did *not* override).

Cache contract:

* Per-tenant entry, TTL = ``cache_ttl_s`` seconds (default 60). Reads use
  the entry as long as ``expires_at`` lies in the future per the injected
  ``clock``.
* ``invalidate(tenant_id)`` evicts a single tenant's entry. The Phase 3
  REST surface (TASK-005) and CLI (TASK-008+) call this on every mutation
  so a model add becomes visible without an app restart.
* Concurrent misses for the same tenant are coalesced through a per-
  tenant ``asyncio.Lock`` — one DB round trip per miss, not N.

Logging:

* ``model_registry_cache_miss`` and ``model_registry_cache_invalidate``
  via structlog. ``litellm_params`` is **never** logged — it can hold
  provider credentials. Only counts and the tenant id leave this module.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)


VALID_DB_ORIGINS = frozenset({"custom", "hide_system"})


@dataclass(frozen=True)
class DbModelRow:
    """One row out of the per-tenant ``models`` table."""

    id: UUID
    tenant_id: UUID
    name: str
    origin: str
    litellm_model: str | None
    litellm_params: dict | None
    is_passthrough: bool


@dataclass(frozen=True)
class ModelEntry:
    """An effective model entry visible to a tenant.

    ``origin`` is ``'system'`` for yaml-sourced entries and ``'custom'``
    for tenant-specific rows. ``hide_system`` rows never appear here —
    they only remove yaml entries from the merge.
    """

    name: str
    origin: str
    is_passthrough: bool
    litellm_model: str | None
    litellm_params: dict | None
    id: UUID | None = None
    tenant_id: UUID | None = None


class ModelsRepositoryProtocol(Protocol):
    """Minimal surface the registry needs from the per-tenant ``models`` table.

    TASK-005 will extend the concrete repo with CRUD; the registry only
    consumes reads here.
    """

    async def list_for_tenant(self, tenant_id: UUID) -> list[DbModelRow]: ...


@dataclass
class _CacheEntry:
    expires_at: float
    models: tuple[ModelEntry, ...]


class ModelRegistryService:
    """yaml-union-DB merge with a TTL cache."""

    def __init__(
        self,
        yaml_models: list[dict],
        repo: ModelsRepositoryProtocol,
        *,
        cache_ttl_s: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._yaml: tuple[ModelEntry, ...] = tuple(
            self._normalize_yaml(entry) for entry in yaml_models
        )
        self._repo = repo
        self._cache_ttl_s = cache_ttl_s
        self._clock = clock
        self._cache: dict[UUID, _CacheEntry] = {}
        self._tenant_locks: dict[UUID, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    @staticmethod
    def _normalize_yaml(entry: dict) -> ModelEntry:
        return ModelEntry(
            name=entry["name"],
            origin="system",
            is_passthrough=True,
            litellm_model=entry.get("litellm_model"),
            litellm_params=entry.get("litellm_params"),
        )

    async def _lock_for(self, tenant_id: UUID) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._tenant_locks.get(tenant_id)
            if lock is None:
                lock = asyncio.Lock()
                self._tenant_locks[tenant_id] = lock
            return lock

    def _fresh(self, entry: _CacheEntry | None) -> bool:
        return entry is not None and entry.expires_at > self._clock()

    async def list_models(self, tenant_id: UUID) -> list[ModelEntry]:
        cached = self._cache.get(tenant_id)
        if self._fresh(cached):
            return list(cached.models)  # type: ignore[union-attr]

        lock = await self._lock_for(tenant_id)
        async with lock:
            cached = self._cache.get(tenant_id)
            if self._fresh(cached):
                return list(cached.models)  # type: ignore[union-attr]

            models = await self._compute(tenant_id)
            self._cache[tenant_id] = _CacheEntry(
                expires_at=self._clock() + self._cache_ttl_s,
                models=tuple(models),
            )
            return list(models)

    async def get_passthrough_set(self, tenant_id: UUID) -> set[str]:
        return {m.name for m in await self.list_models(tenant_id) if m.is_passthrough}

    async def invalidate(self, tenant_id: UUID) -> None:
        lock = await self._lock_for(tenant_id)
        async with lock:
            self._cache.pop(tenant_id, None)
        logger.info("model_registry_cache_invalidate", tenant_id=str(tenant_id))

    async def _compute(self, tenant_id: UUID) -> list[ModelEntry]:
        rows = await self._repo.list_for_tenant(tenant_id)
        custom_by_name: dict[str, DbModelRow] = {}
        hidden_names: set[str] = set()
        for row in rows:
            if row.origin == "custom":
                custom_by_name[row.name] = row
            elif row.origin == "hide_system":
                hidden_names.add(row.name)
            # Unknown origins are ignored — the alembic CHECK constraint
            # makes them unreachable from production but keeping this
            # branch defensive avoids a single bad row taking the
            # registry down.

        merged: list[ModelEntry] = []
        for sys_entry in self._yaml:
            if sys_entry.name in custom_by_name:
                continue
            if sys_entry.name in hidden_names:
                continue
            merged.append(sys_entry)

        for row in custom_by_name.values():
            merged.append(
                ModelEntry(
                    name=row.name,
                    origin="custom",
                    is_passthrough=row.is_passthrough,
                    litellm_model=row.litellm_model,
                    litellm_params=row.litellm_params,
                    id=row.id,
                    tenant_id=row.tenant_id,
                )
            )

        logger.info(
            "model_registry_cache_miss",
            tenant_id=str(tenant_id),
            yaml_count=len(self._yaml),
            db_row_count=len(rows),
            visible_count=len(merged),
            custom_count=len(custom_by_name),
            hidden_count=len(hidden_names),
        )
        return merged
