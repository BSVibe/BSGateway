"""Tests for bsgateway.rules.repository — RulesRepository CRUD + caching."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import asyncpg
import pytest

from bsgateway.core.cache import CACHE_TTL_RULES, cache_key_rules
from bsgateway.core.exceptions import DuplicateError
from bsgateway.rules.repository import RulesRepository
from bsgateway.tests.conftest import MockAcquire, MockTransaction

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_conn() -> AsyncMock:
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=MockTransaction())
    return conn


@pytest.fixture
def mock_pool(mock_conn: AsyncMock) -> MagicMock:
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=MockAcquire(mock_conn))
    return pool


@pytest.fixture
def mock_cache() -> AsyncMock:
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=True)
    cache.delete = AsyncMock(return_value=True)
    return cache


@pytest.fixture
def repo(mock_pool: MagicMock) -> RulesRepository:
    """Repository without cache."""
    with patch("bsgateway.rules.repository.sql") as sql_mock:
        sql_mock.schema.return_value = "CREATE TABLE test (id int)"
        sql_mock.query.return_value = "SELECT 1"
        r = RulesRepository(mock_pool, cache=None)
        r._sql = sql_mock
        yield r


@pytest.fixture
def cached_repo(mock_pool: MagicMock, mock_cache: AsyncMock) -> RulesRepository:
    """Repository with cache."""
    with patch("bsgateway.rules.repository.sql") as sql_mock:
        sql_mock.schema.return_value = "CREATE TABLE test (id int)"
        sql_mock.query.return_value = "SELECT 1"
        r = RulesRepository(mock_pool, cache=mock_cache)
        r._sql = sql_mock
        yield r


# ---------------------------------------------------------------------------
# TestRulesCRUD
# ---------------------------------------------------------------------------


class TestRulesCRUD:
    """Tests for rule create / get / list / update / delete."""

    @pytest.mark.asyncio
    async def test_create_rule_returns_row(self, repo, mock_conn):
        tenant_id = uuid4()
        expected = {"id": uuid4(), "name": "fast-model", "priority": 1}
        mock_conn.fetchrow.return_value = expected

        row = await repo.create_rule(
            tenant_id=tenant_id,
            name="fast-model",
            priority=1,
            target_model="gpt-4o-mini",
        )

        assert row == expected
        mock_conn.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_rule_duplicate_raises(self, repo, mock_conn):
        mock_conn.fetchrow.side_effect = asyncpg.UniqueViolationError("")

        with pytest.raises(DuplicateError, match="already exists"):
            await repo.create_rule(
                tenant_id=uuid4(),
                name="dup",
                priority=1,
                target_model="gpt-4o",
            )

    @pytest.mark.asyncio
    async def test_create_rule_with_is_default(self, repo, mock_conn):
        tenant_id = uuid4()
        mock_conn.fetchrow.return_value = {"id": uuid4(), "is_default": True}

        row = await repo.create_rule(
            tenant_id=tenant_id,
            name="default-rule",
            priority=100,
            target_model="gpt-4o",
            is_default=True,
        )

        assert row["is_default"] is True

    @pytest.mark.asyncio
    async def test_get_rule_found(self, repo, mock_conn):
        rule_id, tenant_id = uuid4(), uuid4()
        mock_conn.fetchrow.return_value = {"id": rule_id, "name": "r1"}

        row = await repo.get_rule(rule_id, tenant_id)

        assert row is not None
        assert row["id"] == rule_id

    @pytest.mark.asyncio
    async def test_get_rule_not_found(self, repo, mock_conn):
        mock_conn.fetchrow.return_value = None

        row = await repo.get_rule(uuid4(), uuid4())

        assert row is None

    @pytest.mark.asyncio
    async def test_list_rules_from_db(self, repo, mock_conn):
        tenant_id = uuid4()
        mock_conn.fetch.return_value = [
            {"id": uuid4(), "priority": 1},
            {"id": uuid4(), "priority": 2},
        ]

        rows = await repo.list_rules(tenant_id)

        assert len(rows) == 2
        mock_conn.fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_rule_returns_updated(self, repo, mock_conn):
        rule_id, tenant_id = uuid4(), uuid4()
        mock_conn.fetchrow.return_value = {"id": rule_id, "name": "updated"}

        row = await repo.update_rule(
            rule_id=rule_id,
            tenant_id=tenant_id,
            name="updated",
            priority=2,
            is_default=False,
            target_model="gpt-4o",
        )

        assert row["name"] == "updated"

    @pytest.mark.asyncio
    async def test_update_rule_not_found(self, repo, mock_conn):
        mock_conn.fetchrow.return_value = None

        row = await repo.update_rule(
            rule_id=uuid4(),
            tenant_id=uuid4(),
            name="x",
            priority=1,
            is_default=False,
            target_model="gpt-4o",
        )

        assert row is None

    @pytest.mark.asyncio
    async def test_delete_rule(self, repo, mock_conn):
        rule_id, tenant_id = uuid4(), uuid4()

        await repo.delete_rule(rule_id, tenant_id)

        mock_conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reorder_rules(self, repo, mock_conn):
        tenant_id = uuid4()
        priorities = {uuid4(): 1, uuid4(): 2, uuid4(): 3}

        await repo.reorder_rules(tenant_id, priorities)

        assert mock_conn.execute.await_count == len(priorities)


# ---------------------------------------------------------------------------
# TestConditionsCRUD
# ---------------------------------------------------------------------------


class TestConditionsCRUD:
    """Tests for condition create / list / replace / list_for_tenant."""

    @pytest.mark.asyncio
    async def test_create_condition(self, repo, mock_conn):
        rule_id = uuid4()
        expected = {"id": uuid4(), "condition_type": "header"}
        mock_conn.fetchrow.return_value = expected

        row = await repo.create_condition(
            rule_id=rule_id,
            condition_type="header",
            operator="eq",
            field="x-custom",
            value="val",
        )

        assert row["condition_type"] == "header"
        # value must be JSON-encoded (arg order: sql, rule_id, type, op, field, value, negate)
        call_args = mock_conn.fetchrow.call_args
        assert call_args[0][5] == json.dumps("val")

    @pytest.mark.asyncio
    async def test_create_condition_with_negate(self, repo, mock_conn):
        mock_conn.fetchrow.return_value = {"id": uuid4(), "negate": True}

        row = await repo.create_condition(
            rule_id=uuid4(),
            condition_type="metadata",
            operator="contains",
            field="tags",
            value=["important"],
            negate=True,
        )

        assert row["negate"] is True

    @pytest.mark.asyncio
    async def test_create_condition_value_json_encoded(self, repo, mock_conn):
        """Complex values (dicts, lists) must be JSON-serialized."""
        mock_conn.fetchrow.return_value = {"id": uuid4()}
        complex_value = {"min": 10, "max": 100}

        await repo.create_condition(
            rule_id=uuid4(),
            condition_type="metadata",
            operator="range",
            field="tokens",
            value=complex_value,
        )

        call_args = mock_conn.fetchrow.call_args
        assert call_args[0][5] == json.dumps(complex_value)

    @pytest.mark.asyncio
    async def test_list_conditions(self, repo, mock_conn):
        rule_id = uuid4()
        mock_conn.fetch.return_value = [
            {"id": uuid4(), "field": "model"},
            {"id": uuid4(), "field": "user"},
        ]

        rows = await repo.list_conditions(rule_id)

        assert len(rows) == 2
        mock_conn.fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_replace_conditions(self, repo, mock_conn):
        rule_id = uuid4()
        new_conditions = [
            {"condition_type": "header", "field": "x-a", "value": "1"},
            {
                "condition_type": "header",
                "field": "x-b",
                "value": "2",
                "operator": "neq",
                "negate": True,
            },
        ]
        mock_conn.fetchrow.return_value = {"id": uuid4()}

        results = await repo.replace_conditions(rule_id, new_conditions)

        # 1 delete + N inserts => execute called once, fetchrow called N times
        mock_conn.execute.assert_awaited_once()  # delete_conditions_for_rule
        assert mock_conn.fetchrow.await_count == 2
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_replace_conditions_empty_list(self, repo, mock_conn):
        """Replacing with an empty list should only delete."""
        results = await repo.replace_conditions(uuid4(), [])

        mock_conn.execute.assert_awaited_once()
        mock_conn.fetchrow.assert_not_awaited()
        assert results == []

    @pytest.mark.asyncio
    async def test_replace_conditions_defaults(self, repo, mock_conn):
        """Conditions without operator/negate should use defaults."""
        mock_conn.fetchrow.return_value = {"id": uuid4()}

        await repo.replace_conditions(
            uuid4(),
            [
                {"condition_type": "header", "field": "x-a", "value": "v"},
            ],
        )

        call_args = mock_conn.fetchrow.call_args[0]
        # arg order: sql, rule_id, condition_type, operator, field, value, negate
        assert call_args[3] == "eq"
        assert call_args[6] is False

    @pytest.mark.asyncio
    async def test_list_conditions_for_tenant(self, repo, mock_conn):
        tenant_id = uuid4()
        mock_conn.fetch.return_value = [{"id": uuid4()}]

        rows = await repo.list_conditions_for_tenant(tenant_id)

        assert len(rows) == 1


# ---------------------------------------------------------------------------
# TestIntentsCRUD
# ---------------------------------------------------------------------------


class TestIntentsCRUD:
    """Tests for intent create / get / list / update / delete."""

    @pytest.mark.asyncio
    async def test_create_intent(self, repo, mock_conn):
        tenant_id = uuid4()
        expected = {"id": uuid4(), "name": "greeting"}
        mock_conn.fetchrow.return_value = expected

        row = await repo.create_intent(tenant_id, "greeting", "Hello intent", 0.8)

        assert row["name"] == "greeting"

    @pytest.mark.asyncio
    async def test_create_intent_defaults(self, repo, mock_conn):
        """description defaults to '', threshold defaults to 0.7."""
        mock_conn.fetchrow.return_value = {"id": uuid4()}

        await repo.create_intent(uuid4(), "test")

        args = mock_conn.fetchrow.call_args[0]
        # positional: sql, tenant_id, name, description, threshold
        assert args[3] == ""  # description default
        assert args[4] == 0.7  # threshold default

    @pytest.mark.asyncio
    async def test_get_intent(self, repo, mock_conn):
        intent_id, tenant_id = uuid4(), uuid4()
        mock_conn.fetchrow.return_value = {"id": intent_id}

        row = await repo.get_intent(intent_id, tenant_id)

        assert row["id"] == intent_id

    @pytest.mark.asyncio
    async def test_get_intent_not_found(self, repo, mock_conn):
        mock_conn.fetchrow.return_value = None

        row = await repo.get_intent(uuid4(), uuid4())

        assert row is None

    @pytest.mark.asyncio
    async def test_list_intents(self, repo, mock_conn):
        mock_conn.fetch.return_value = [{"id": uuid4()}, {"id": uuid4()}]

        rows = await repo.list_intents(uuid4())

        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_list_intents_empty(self, repo, mock_conn):
        mock_conn.fetch.return_value = []

        rows = await repo.list_intents(uuid4())

        assert rows == []

    @pytest.mark.asyncio
    async def test_update_intent(self, repo, mock_conn):
        intent_id, tenant_id = uuid4(), uuid4()
        mock_conn.fetchrow.return_value = {"id": intent_id, "name": "updated"}

        row = await repo.update_intent(intent_id, tenant_id, "updated", "desc", 0.9)

        assert row["name"] == "updated"

    @pytest.mark.asyncio
    async def test_update_intent_not_found(self, repo, mock_conn):
        mock_conn.fetchrow.return_value = None

        row = await repo.update_intent(uuid4(), uuid4(), "x", "d", 0.5)

        assert row is None

    @pytest.mark.asyncio
    async def test_delete_intent(self, repo, mock_conn):
        await repo.delete_intent(uuid4(), uuid4())

        mock_conn.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestIntentExamples
# ---------------------------------------------------------------------------


class TestIntentExamples:
    """Tests for intent example add / list / delete / list_for_tenant."""

    @pytest.mark.asyncio
    async def test_add_example(self, repo, mock_conn):
        intent_id = uuid4()
        mock_conn.fetchrow.return_value = {"id": uuid4(), "text": "hi"}

        row = await repo.add_example(intent_id, "hi")

        assert row["text"] == "hi"

    @pytest.mark.asyncio
    async def test_add_example_with_embedding(self, repo, mock_conn):
        embedding = b"\x00\x01\x02"
        mock_conn.fetchrow.return_value = {"id": uuid4()}

        await repo.add_example(uuid4(), "hello", embedding=embedding)

        args = mock_conn.fetchrow.call_args[0]
        assert args[3] == embedding

    @pytest.mark.asyncio
    async def test_add_example_default_embedding_none(self, repo, mock_conn):
        mock_conn.fetchrow.return_value = {"id": uuid4()}

        await repo.add_example(uuid4(), "hello")

        args = mock_conn.fetchrow.call_args[0]
        assert args[3] is None

    @pytest.mark.asyncio
    async def test_list_examples(self, repo, mock_conn):
        mock_conn.fetch.return_value = [{"id": uuid4(), "text": "a"}]

        rows = await repo.list_examples(uuid4())

        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_list_examples_empty(self, repo, mock_conn):
        mock_conn.fetch.return_value = []

        rows = await repo.list_examples(uuid4())

        assert rows == []

    @pytest.mark.asyncio
    async def test_delete_example(self, repo, mock_conn):
        await repo.delete_example(uuid4(), uuid4())

        mock_conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_examples_for_tenant(self, repo, mock_conn):
        mock_conn.fetch.return_value = [{"id": uuid4()}, {"id": uuid4()}]

        rows = await repo.list_examples_for_tenant(uuid4())

        assert len(rows) == 2


# ---------------------------------------------------------------------------
# TestCacheInvalidation
# ---------------------------------------------------------------------------


class TestCacheInvalidation:
    """Tests for cache hit, miss, and invalidation on mutations."""

    @pytest.mark.asyncio
    async def test_list_rules_cache_hit(self, cached_repo, mock_cache, mock_conn):
        tenant_id = uuid4()
        cached_data = [{"id": str(uuid4()), "priority": 1}]
        mock_cache.get.return_value = cached_data

        rows = await cached_repo.list_rules(tenant_id)

        # Should return from cache — DB should NOT be called
        mock_conn.fetch.assert_not_awaited()
        assert rows == [dict(r) for r in cached_data]
        mock_cache.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_rules_cache_miss_populates_cache(self, cached_repo, mock_cache, mock_conn):
        tenant_id = uuid4()
        mock_cache.get.return_value = None
        db_rows = [MagicMock(), MagicMock()]
        # Make MagicMock iterable as dict for [dict(row) for row in rows]
        for i, row in enumerate(db_rows):
            row.__iter__ = MagicMock(return_value=iter([("id", i), ("p", i)]))
            row.keys = MagicMock(return_value=["id", "p"])
            row.__getitem__ = MagicMock(side_effect=lambda k, _i=i: _i)
        mock_conn.fetch.return_value = db_rows

        rows = await cached_repo.list_rules(tenant_id)

        assert len(rows) == 2
        mock_conn.fetch.assert_awaited_once()
        # Cache should be populated
        mock_cache.set.assert_awaited_once()
        set_args = mock_cache.set.call_args
        assert set_args[0][0] == cache_key_rules(str(tenant_id))
        assert set_args[0][2] == CACHE_TTL_RULES

    @pytest.mark.asyncio
    async def test_list_rules_cache_miss_empty_does_not_cache(
        self, cached_repo, mock_cache, mock_conn
    ):
        """Empty results should NOT be cached."""
        mock_cache.get.return_value = None
        mock_conn.fetch.return_value = []

        rows = await cached_repo.list_rules(uuid4())

        assert rows == []
        mock_cache.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_rule_invalidates_cache(self, cached_repo, mock_cache, mock_conn):
        tenant_id = uuid4()
        mock_conn.fetchrow.return_value = {"id": uuid4()}

        await cached_repo.create_rule(tenant_id, "r", 1, "gpt-4o")

        mock_cache.delete.assert_awaited_once_with(cache_key_rules(str(tenant_id)))

    @pytest.mark.asyncio
    async def test_update_rule_invalidates_cache(self, cached_repo, mock_cache, mock_conn):
        tenant_id = uuid4()
        mock_conn.fetchrow.return_value = {"id": uuid4()}

        await cached_repo.update_rule(uuid4(), tenant_id, "u", 1, False, "gpt-4o")

        mock_cache.delete.assert_awaited_once_with(cache_key_rules(str(tenant_id)))

    @pytest.mark.asyncio
    async def test_delete_rule_invalidates_cache(self, cached_repo, mock_cache, mock_conn):
        tenant_id = uuid4()

        await cached_repo.delete_rule(uuid4(), tenant_id)

        mock_cache.delete.assert_awaited_once_with(cache_key_rules(str(tenant_id)))

    @pytest.mark.asyncio
    async def test_reorder_rules_invalidates_cache(self, cached_repo, mock_cache, mock_conn):
        tenant_id = uuid4()

        await cached_repo.reorder_rules(tenant_id, {uuid4(): 1})

        mock_cache.delete.assert_awaited_once_with(cache_key_rules(str(tenant_id)))

    @pytest.mark.asyncio
    async def test_no_cache_no_invalidation(self, repo, mock_conn):
        """When cache is None, mutations should not error."""
        tenant_id = uuid4()
        mock_conn.fetchrow.return_value = {"id": uuid4()}

        # Should succeed without cache
        await repo.create_rule(tenant_id, "r", 1, "gpt-4o")
        await repo.update_rule(uuid4(), tenant_id, "u", 1, False, "gpt-4o")
        await repo.delete_rule(uuid4(), tenant_id)
        await repo.reorder_rules(tenant_id, {uuid4(): 1})

    @pytest.mark.asyncio
    async def test_list_rules_no_cache_always_hits_db(self, repo, mock_conn):
        """Without cache, list_rules should always query the DB."""
        mock_conn.fetch.return_value = [{"id": uuid4()}]

        await repo.list_rules(uuid4())
        await repo.list_rules(uuid4())

        assert mock_conn.fetch.await_count == 2


# ---------------------------------------------------------------------------
# TestInitSchema
# ---------------------------------------------------------------------------


class TestInitSchema:
    """Tests for init_schema method."""

    @pytest.mark.asyncio
    async def test_init_schema_executes_statements(self, repo, mock_conn):
        repo._sql.schema.return_value = "CREATE TABLE a (id int);\nCREATE TABLE b (id int)"

        await repo.init_schema()

        assert mock_conn.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_init_schema_skips_empty_statements(self, repo, mock_conn):
        repo._sql.schema.return_value = "CREATE TABLE a (id int); ;  ;"

        await repo.init_schema()

        # Only non-empty statements should be executed
        mock_conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_init_schema_runs_in_transaction(self, repo, mock_conn):
        repo._sql.schema.return_value = "CREATE TABLE x (id int)"

        await repo.init_schema()

        mock_conn.transaction.assert_called_once()
