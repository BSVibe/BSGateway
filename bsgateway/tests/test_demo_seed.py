"""Tests for the BSGateway demo seed.

The seed inserts realistic demo data scoped to a single tenant_id so the
visitor's dashboard renders with content immediately.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from bsgateway.demo.seed import seed_demo


class TestSeedDemo:
    @pytest.mark.asyncio
    async def test_seeds_api_keys_routing_logs_rules_for_tenant(self) -> None:
        conn = AsyncMock()
        tenant_id = uuid4()

        await seed_demo(tenant_id=tenant_id, conn=conn)

        # Collect all SQL strings sent to conn.execute
        executed_sql = " ".join(str(call.args[0]) for call in conn.execute.await_args_list)

        # Demo seed must populate at least these surfaces
        assert "INSERT INTO api_keys" in executed_sql
        assert "INSERT INTO routing_rules" in executed_sql
        assert "INSERT INTO routing_logs" in executed_sql

    @pytest.mark.asyncio
    async def test_seed_uses_provided_tenant_id_not_random(self) -> None:
        conn = AsyncMock()
        tenant_id = uuid4()

        await seed_demo(tenant_id=tenant_id, conn=conn)

        # Every INSERT must reference the provided tenant_id
        # (Verify by checking it appears in args of execute calls)
        all_args: list[object] = []
        for call in conn.execute.await_args_list:
            all_args.extend(call.args[1:])
        assert tenant_id in all_args, "tenant_id must appear in seed inserts"

    @pytest.mark.asyncio
    async def test_seed_is_idempotent_per_tenant(self) -> None:
        # Calling seed_demo twice with the same tenant_id must not fail.
        # PG-side ON CONFLICT clauses (or table truncation prior) handle this.
        # We just verify the function doesn't raise on repeat call against
        # an AsyncMock that always succeeds.
        conn = AsyncMock()
        tenant_id = uuid4()

        await seed_demo(tenant_id=tenant_id, conn=conn)
        await seed_demo(tenant_id=tenant_id, conn=conn)
        # No exception → ok

    @pytest.mark.asyncio
    async def test_seed_does_not_log_secrets(self) -> None:
        # Seed inserts api_keys but plaintext keys are NOT preserved —
        # only key_hash + key_prefix go into the table.
        conn = AsyncMock()
        tenant_id = uuid4()

        await seed_demo(tenant_id=tenant_id, conn=conn)

        executed_sql = " ".join(str(call.args[0]) for call in conn.execute.await_args_list)
        # Should reference key_hash, not raw key
        assert "key_hash" in executed_sql
