"""Phase 3 / TASK-004 — asyncpg-backed read implementation of
:class:`ModelsRepositoryProtocol`.

The Phase 3 admin REST surface (TASK-005) will extend this class with
CRUD methods. TASK-004 only needs the read path so the routing hook can
consume the per-tenant ``models`` table behind ``ModelRegistryService``.

Notes:

* asyncpg returns JSONB columns as raw strings by default
  (see TODO in ``bsgateway/core/database.py``). We decode
  ``litellm_params`` defensively here so callers always see ``dict | None``.
* ``litellm_params`` may carry provider credentials (api_base, api_key
  references). It is **never** logged from this module.
"""

from __future__ import annotations

import json
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


class ModelsRepository:
    """Read-only access to the per-tenant ``models`` table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_for_tenant(self, tenant_id: UUID) -> list[DbModelRow]:
        async with self._pool.acquire() as conn:
            records = await conn.fetch(_LIST_FOR_TENANT_SQL, tenant_id)
        return [_record_to_row(record) for record in records]


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
