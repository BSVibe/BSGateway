"""Phase 3 / TASK-004+005 — asyncpg-backed implementation of
:class:`ModelsRepositoryProtocol` plus admin CRUD.

TASK-004 added the read path that feeds ``ModelRegistryService``.
TASK-005 layers on the CRUD surface consumed by the
``/admin/models`` router. Every write filters by ``tenant_id`` —
the tenant-isolation invariant keeps a row owned by tenant A
invisible to tenant B even with a guessed model UUID.

Notes:

* asyncpg returns JSONB columns as raw strings by default
  (see TODO in ``bsgateway/core/database.py``). We decode
  ``litellm_params`` defensively here so callers always see ``dict | None``.
* ``litellm_params`` may carry provider credentials (api_base, api_key
  references). It is **never** logged from this module.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from bsgateway.routing.registry import DbModelRow

logger = structlog.get_logger(__name__)


_LIST_FOR_TENANT_SQL = """
SELECT id, tenant_id, name, origin, litellm_model, litellm_params, is_passthrough
FROM models
WHERE tenant_id = $1
ORDER BY name ASC
"""

_GET_BY_ID_SQL = """
SELECT id, tenant_id, name, origin, litellm_model, litellm_params,
       is_passthrough, created_at, updated_at
FROM models
WHERE id = $1 AND tenant_id = $2
"""

_INSERT_SQL = """
INSERT INTO models (tenant_id, name, origin, litellm_model, litellm_params, is_passthrough)
VALUES ($1, $2, $3, $4, $5::jsonb, $6)
RETURNING id, tenant_id, name, origin, litellm_model, litellm_params,
          is_passthrough, created_at, updated_at
"""

_UPDATE_SQL = """
UPDATE models
SET name           = COALESCE($3, name),
    origin         = COALESCE($4, origin),
    litellm_model  = CASE WHEN $7::bool THEN $5 ELSE litellm_model END,
    litellm_params = CASE WHEN $8::bool THEN $6::jsonb ELSE litellm_params END,
    is_passthrough = COALESCE($9, is_passthrough),
    updated_at     = NOW()
WHERE id = $1 AND tenant_id = $2
RETURNING id, tenant_id, name, origin, litellm_model, litellm_params,
          is_passthrough, created_at, updated_at
"""

_DELETE_SQL = "DELETE FROM models WHERE id = $1 AND tenant_id = $2"


class ModelsRepository:
    """Tenant-scoped CRUD against the ``models`` table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_for_tenant(self, tenant_id: UUID) -> list[DbModelRow]:
        async with self._pool.acquire() as conn:
            records = await conn.fetch(_LIST_FOR_TENANT_SQL, tenant_id)
        return [_record_to_row(record) for record in records]

    async def get_model(self, model_id: UUID, tenant_id: UUID) -> dict | None:
        """Fetch a single row, scoped to ``tenant_id`` for isolation.

        Returns the raw record (with ``created_at`` / ``updated_at``) so
        the router can shape the response — different from
        :meth:`list_for_tenant` which strips timestamps for the cache.
        """
        async with self._pool.acquire() as conn:
            record = await conn.fetchrow(_GET_BY_ID_SQL, model_id, tenant_id)
        if record is None:
            return None
        return _record_to_dict(record)

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
        params_json = json.dumps(litellm_params) if litellm_params is not None else None
        async with self._pool.acquire() as conn:
            record = await conn.fetchrow(
                _INSERT_SQL,
                tenant_id,
                name,
                origin,
                litellm_model,
                params_json,
                is_passthrough,
            )
        # asyncpg INSERT … RETURNING never returns NULL when the insert
        # succeeded; a None here would be a server-side bug.
        assert record is not None
        return _record_to_dict(record)

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
        """Patch a row. ``*_set`` flags distinguish "not provided" from
        "explicitly set to NULL" since both surface as ``None`` here."""
        params_json = (
            json.dumps(litellm_params)
            if (litellm_params_set and litellm_params is not None)
            else None
        )
        async with self._pool.acquire() as conn:
            record = await conn.fetchrow(
                _UPDATE_SQL,
                model_id,
                tenant_id,
                name,
                origin,
                litellm_model,
                params_json,
                litellm_model_set,
                litellm_params_set,
                is_passthrough,
            )
        if record is None:
            return None
        return _record_to_dict(record)

    async def delete_model(self, model_id: UUID, tenant_id: UUID) -> bool:
        """Return ``True`` if a row was deleted, ``False`` otherwise."""
        async with self._pool.acquire() as conn:
            result: str = await conn.execute(_DELETE_SQL, model_id, tenant_id)
        # asyncpg returns "DELETE <count>" — parse the numeric tail.
        try:
            return int(result.split()[-1]) > 0
        except (ValueError, IndexError):
            return False


def _record_to_dict(record: asyncpg.Record) -> dict[str, Any]:
    """Translate a record into a dict with ``litellm_params`` decoded."""
    params_raw = record["litellm_params"]
    if params_raw is None:
        params: dict | None = None
    elif isinstance(params_raw, str):
        try:
            params = json.loads(params_raw)
        except json.JSONDecodeError:
            logger.warning(
                "models_repo_invalid_jsonb",
                model_id=str(record["id"]),
                tenant_id=str(record["tenant_id"]),
            )
            params = None
    else:
        params = dict(params_raw)
    return {
        "id": record["id"],
        "tenant_id": record["tenant_id"],
        "name": record["name"],
        "origin": record["origin"],
        "litellm_model": record["litellm_model"],
        "litellm_params": params,
        "is_passthrough": record["is_passthrough"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def _record_to_row(record: asyncpg.Record) -> DbModelRow:
    """Translate an asyncpg ``Record`` into a typed :class:`DbModelRow`.

    JSONB columns can come back as ``str`` (no codec registered) or
    already-decoded ``dict`` (if the operator wires a codec). Handle both.
    """
    params_raw = record["litellm_params"]
    params: dict | None
    if params_raw is None:
        params = None
    elif isinstance(params_raw, str):
        try:
            params = json.loads(params_raw)
        except json.JSONDecodeError:
            logger.warning(
                "models_repo_invalid_jsonb",
                model_id=str(record["id"]),
                tenant_id=str(record["tenant_id"]),
            )
            params = None
    else:
        params = dict(params_raw)
    return DbModelRow(
        id=record["id"],
        tenant_id=record["tenant_id"],
        name=record["name"],
        origin=record["origin"],
        litellm_model=record["litellm_model"],
        litellm_params=params,
        is_passthrough=record["is_passthrough"],
    )
