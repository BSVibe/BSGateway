"""Phase 3 / TASK-004 — asyncpg-backed ``ModelsRepository`` read tests.

The repository feeds ``ModelRegistryService`` for the routing hook. We
mock the asyncpg pool/conn so the test stays a unit test (no live PG)
and pin two concerns:

* The SQL statement filters by ``tenant_id`` (tenant-isolation invariant
  — every routing-table query MUST carry it; cross-tenant leak risk
  otherwise).
* JSONB ``litellm_params`` is decoded to ``dict`` regardless of whether
  asyncpg returns it raw (default) or already-decoded (codec wired).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from bsgateway.routing.models_repository import ModelsRepository


@pytest.fixture
def mock_pool_with_conn() -> tuple[MagicMock, AsyncMock]:
    pool = MagicMock()
    conn = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    return pool, conn


@pytest.mark.asyncio
async def test_list_for_tenant_filters_by_tenant_id(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    conn.fetch = AsyncMock(return_value=[])
    repo = ModelsRepository(pool)
    tenant = uuid4()

    rows = await repo.list_for_tenant(tenant)

    assert rows == []
    sql, *args = conn.fetch.call_args[0]
    assert "tenant_id = $1" in sql.lower().replace("  ", " ")
    assert args == [tenant]


@pytest.mark.asyncio
async def test_list_for_tenant_decodes_jsonb_string(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    tenant = uuid4()
    record = {
        "id": uuid4(),
        "tenant_id": tenant,
        "name": "custom/foo",
        "origin": "custom",
        "litellm_model": "ollama/foo",
        "litellm_params": json.dumps({"api_base": "http://x"}),
        "is_passthrough": True,
    }
    conn.fetch = AsyncMock(return_value=[record])

    rows = await ModelsRepository(pool).list_for_tenant(tenant)

    assert len(rows) == 1
    assert rows[0].litellm_params == {"api_base": "http://x"}
    assert rows[0].name == "custom/foo"


@pytest.mark.asyncio
async def test_list_for_tenant_handles_already_decoded_dict(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    """If a connection-level codec is wired, asyncpg returns dict directly."""
    pool, conn = mock_pool_with_conn
    tenant = uuid4()
    record = {
        "id": uuid4(),
        "tenant_id": tenant,
        "name": "custom/foo",
        "origin": "custom",
        "litellm_model": "ollama/foo",
        "litellm_params": {"api_base": "http://x"},
        "is_passthrough": False,
    }
    conn.fetch = AsyncMock(return_value=[record])

    rows = await ModelsRepository(pool).list_for_tenant(tenant)

    assert rows[0].litellm_params == {"api_base": "http://x"}
    assert rows[0].is_passthrough is False


@pytest.mark.asyncio
async def test_list_for_tenant_handles_null_jsonb(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    tenant = uuid4()
    record = {
        "id": uuid4(),
        "tenant_id": tenant,
        "name": "claude-haiku",
        "origin": "hide_system",
        "litellm_model": None,
        "litellm_params": None,
        "is_passthrough": True,
    }
    conn.fetch = AsyncMock(return_value=[record])

    rows = await ModelsRepository(pool).list_for_tenant(tenant)

    assert rows[0].litellm_params is None
    assert rows[0].litellm_model is None
    assert rows[0].origin == "hide_system"


@pytest.mark.asyncio
async def test_list_for_tenant_invalid_jsonb_string_falls_back_to_none(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    """Defensive: a corrupt JSONB string must not crash routing decisions."""
    pool, conn = mock_pool_with_conn
    tenant = uuid4()
    record = {
        "id": uuid4(),
        "tenant_id": tenant,
        "name": "custom/foo",
        "origin": "custom",
        "litellm_model": "ollama/foo",
        "litellm_params": "{not-valid-json",
        "is_passthrough": True,
    }
    conn.fetch = AsyncMock(return_value=[record])

    rows = await ModelsRepository(pool).list_for_tenant(tenant)

    assert rows[0].litellm_params is None
