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


# ---------------------------------------------------------------------------
# CRUD tests (TASK-005) — every write filters by tenant_id for isolation.
# ---------------------------------------------------------------------------


def _full_record(
    *,
    tenant: uuid4,
    name: str = "custom/foo",
    origin: str = "custom",
    litellm_model: str | None = "ollama/foo",
    litellm_params=None,
    is_passthrough: bool = True,
    model_id=None,
) -> dict:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return {
        "id": model_id or uuid4(),
        "tenant_id": tenant,
        "name": name,
        "origin": origin,
        "litellm_model": litellm_model,
        "litellm_params": litellm_params,
        "is_passthrough": is_passthrough,
        "created_at": now,
        "updated_at": now,
    }


@pytest.mark.asyncio
async def test_get_model_filters_by_tenant_id(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    tenant = uuid4()
    model_id = uuid4()
    conn.fetchrow = AsyncMock(return_value=_full_record(tenant=tenant, model_id=model_id))

    row = await ModelsRepository(pool).get_model(model_id, tenant)

    assert row is not None
    assert row["id"] == model_id
    sql, *args = conn.fetchrow.call_args[0]
    assert "tenant_id = $2" in sql
    assert args == [model_id, tenant]


@pytest.mark.asyncio
async def test_get_model_returns_none_when_missing(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    conn.fetchrow = AsyncMock(return_value=None)

    row = await ModelsRepository(pool).get_model(uuid4(), uuid4())

    assert row is None


@pytest.mark.asyncio
async def test_create_model_serialises_params_to_json(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    tenant = uuid4()
    expected = _full_record(tenant=tenant, litellm_params={"api_base": "http://x"})
    conn.fetchrow = AsyncMock(return_value=expected)

    row = await ModelsRepository(pool).create_model(
        tenant_id=tenant,
        name="custom/foo",
        origin="custom",
        litellm_model="ollama/foo",
        litellm_params={"api_base": "http://x"},
        is_passthrough=True,
    )

    assert row["name"] == "custom/foo"
    args = conn.fetchrow.call_args[0]
    # Args order: sql, tenant_id, name, origin, litellm_model, params_json, is_passthrough.
    assert args[1] == tenant
    assert args[5] == json.dumps({"api_base": "http://x"})


@pytest.mark.asyncio
async def test_create_model_passes_null_params_unchanged(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    tenant = uuid4()
    conn.fetchrow = AsyncMock(
        return_value=_full_record(
            tenant=tenant, origin="hide_system", litellm_model=None, litellm_params=None
        )
    )

    await ModelsRepository(pool).create_model(
        tenant_id=tenant,
        name="claude-haiku",
        origin="hide_system",
        litellm_model=None,
        litellm_params=None,
        is_passthrough=True,
    )

    assert conn.fetchrow.call_args[0][5] is None


@pytest.mark.asyncio
async def test_update_model_filters_by_tenant_and_handles_set_flags(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    tenant = uuid4()
    model_id = uuid4()
    conn.fetchrow = AsyncMock(
        return_value=_full_record(tenant=tenant, model_id=model_id, litellm_model="ollama/bar")
    )

    row = await ModelsRepository(pool).update_model(
        model_id=model_id,
        tenant_id=tenant,
        litellm_model="ollama/bar",
        litellm_model_set=True,
    )

    assert row is not None
    args = conn.fetchrow.call_args[0]
    assert args[1] == model_id
    assert args[2] == tenant
    # _set flags at $7/$8 → True for litellm_model, False for litellm_params.
    assert args[7] is True
    assert args[8] is False


@pytest.mark.asyncio
async def test_update_model_returns_none_when_missing(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    conn.fetchrow = AsyncMock(return_value=None)

    row = await ModelsRepository(pool).update_model(
        model_id=uuid4(),
        tenant_id=uuid4(),
        name="renamed",
    )

    assert row is None


@pytest.mark.asyncio
async def test_delete_model_returns_true_on_hit(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    conn.execute = AsyncMock(return_value="DELETE 1")

    deleted = await ModelsRepository(pool).delete_model(uuid4(), uuid4())

    assert deleted is True


@pytest.mark.asyncio
async def test_delete_model_returns_false_when_missing(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    conn.execute = AsyncMock(return_value="DELETE 0")

    deleted = await ModelsRepository(pool).delete_model(uuid4(), uuid4())

    assert deleted is False


@pytest.mark.asyncio
async def test_delete_model_falls_back_to_false_on_unexpected_status(
    mock_pool_with_conn: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool_with_conn
    conn.execute = AsyncMock(return_value="OOPS")

    deleted = await ModelsRepository(pool).delete_model(uuid4(), uuid4())

    assert deleted is False
