from __future__ import annotations

import struct
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.routing.collector import RoutingCollector, SqlLoader
from bsgateway.routing.models import EmbeddingConfig, NexusMetadata, RoutingDecision

# Column positions in the unified insert_routing_log query.
# args[0] is the SQL string; the rest are query parameters in order.
COL_TENANT_ID = 1
COL_RULE_ID = 2
COL_USER_TEXT = 3
COL_SYSTEM_PROMPT = 4
COL_TIER = 11
COL_STRATEGY = 12
COL_ORIGINAL_MODEL = 14
COL_RESOLVED_MODEL = 15
COL_EMBEDDING = 16
COL_NEXUS_TASK_TYPE = 17
COL_NEXUS_PRIORITY = 18
COL_NEXUS_COMPLEXITY_HINT = 19
COL_DECISION_SOURCE = 20

# Default tenant_id used in single-tenant tests below.
TENANT_ID = uuid4()


class _MockPool:
    """Mock asyncpg pool with proper async context manager for acquire()."""

    def __init__(self) -> None:
        self.conn = AsyncMock()
        self.close = AsyncMock()

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.fixture
def mock_pool() -> _MockPool:
    return _MockPool()


@pytest.fixture
def collector(mock_pool: _MockPool) -> RoutingCollector:
    c = RoutingCollector(database_url="postgresql://test:test@localhost/test")
    c._pool = mock_pool
    c._initialized = True
    return c


@pytest.fixture
def collector_with_embedding(mock_pool: _MockPool) -> RoutingCollector:
    c = RoutingCollector(
        database_url="postgresql://test:test@localhost/test",
        embedding_config=EmbeddingConfig(
            api_base="http://localhost:11434",
            model="nomic-embed-text",
            timeout=5.0,
            max_chars=1000,
        ),
    )
    c._pool = mock_pool
    c._initialized = True
    return c


@pytest.fixture
def sample_data() -> dict:
    return {
        "messages": [
            {"role": "user", "content": "Design a microservices architecture"},
        ],
        "system": "You are an expert architect.",
        "tools": [{"type": "function", "function": {"name": "read_file"}}],
    }


@pytest.fixture
def sample_result() -> ClassificationResult:
    return ClassificationResult(tier="complex", strategy="llm", score=None)


@pytest.fixture
def sample_decision() -> RoutingDecision:
    return RoutingDecision(
        method="auto",
        original_model="auto",
        resolved_model="claude-opus",
        complexity_score=None,
        tier="complex",
    )


class TestSqlLoader:
    def test_schema_loads(self) -> None:
        loader = SqlLoader()
        schema = loader.schema()
        assert "CREATE TABLE" in schema
        assert "routing_logs" in schema

    def test_query_loads(self) -> None:
        loader = SqlLoader()
        query = loader.query("insert_routing_log")
        assert "INSERT INTO routing_logs" in query

    def test_all_named_queries_load(self) -> None:
        loader = SqlLoader()
        for name in [
            "insert_routing_log",
            "get_logs_by_tier",
            "get_logs_with_embeddings",
            "count_by_tier",
        ]:
            query = loader.query(name)
            assert len(query) > 0, f"Query {name} should not be empty"

    def test_unknown_query_raises(self) -> None:
        loader = SqlLoader()
        with pytest.raises(KeyError):
            loader.query("nonexistent_query")


class TestEnsureDB:
    @pytest.mark.asyncio
    async def test_creates_pool_and_runs_schema(self) -> None:
        mock_conn = AsyncMock()

        @asynccontextmanager
        async def _acquire():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.acquire = _acquire

        collector = RoutingCollector(database_url="postgresql://test:test@localhost/test")

        with patch("bsgateway.routing.collector.asyncpg") as mock_asyncpg:
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            await collector._ensure_db()

        mock_asyncpg.create_pool.assert_called_once_with(
            "postgresql://test:test@localhost/test", min_size=1, max_size=5
        )
        assert mock_conn.execute.call_count >= 1
        assert collector._initialized is True

    @pytest.mark.asyncio
    async def test_skips_if_already_initialized(self) -> None:
        collector = RoutingCollector(database_url="postgresql://test:test@localhost/test")
        collector._initialized = True
        collector._pool = MagicMock()

        with patch("bsgateway.routing.collector.asyncpg") as mock_asyncpg:
            await collector._ensure_db()
            mock_asyncpg.create_pool.assert_not_called()


class TestRecording:
    @pytest.mark.asyncio
    async def test_inserts_record(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        await collector.record(sample_data, sample_result, sample_decision, tenant_id=TENANT_ID)
        mock_pool.conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_correct_args(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        await collector.record(sample_data, sample_result, sample_decision, tenant_id=TENANT_ID)

        call_args = mock_pool.conn.execute.call_args[0]
        # args[0] = query, args[1:] = parameters
        assert "INSERT INTO routing_logs" in call_args[0]
        assert call_args[COL_TENANT_ID] == TENANT_ID
        assert call_args[COL_RULE_ID] is None
        assert "microservices architecture" in call_args[COL_USER_TEXT]
        assert "expert architect" in call_args[COL_SYSTEM_PROMPT]
        assert call_args[COL_TIER] == "complex"
        assert call_args[COL_STRATEGY] == "llm"
        assert call_args[COL_ORIGINAL_MODEL] == "auto"
        assert call_args[COL_RESOLVED_MODEL] == "claude-opus"
        assert call_args[COL_EMBEDDING] is None  # embedding (disabled)

    @pytest.mark.asyncio
    async def test_no_embedding_when_disabled(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        await collector.record(sample_data, sample_result, sample_decision, tenant_id=TENANT_ID)
        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[COL_EMBEDDING] is None

    @pytest.mark.asyncio
    async def test_multiple_records(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        for _ in range(3):
            await collector.record(sample_data, sample_result, sample_decision, tenant_id=TENANT_ID)
        assert mock_pool.conn.execute.call_count == 3

    @pytest.mark.asyncio
    async def test_record_with_rule_id(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        rule_id = uuid4()
        await collector.record(
            sample_data,
            sample_result,
            sample_decision,
            tenant_id=TENANT_ID,
            rule_id=rule_id,
        )
        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[COL_RULE_ID] == rule_id

    @pytest.mark.asyncio
    async def test_no_record_without_tenant(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        """Without a tenant_id we MUST NOT write to routing_logs (C2)."""
        await collector.record(sample_data, sample_result, sample_decision, tenant_id=None)
        mock_pool.conn.execute.assert_not_called()


class TestEmbedding:
    @pytest.mark.asyncio
    async def test_embedding_stored_on_success(
        self,
        collector_with_embedding: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        fake_vector = [0.1, 0.2, 0.3]
        fake_response = MagicMock()
        fake_response.data = [{"embedding": fake_vector}]

        with patch("bsgateway.routing.collector.litellm") as mock_litellm:
            mock_litellm.aembedding = AsyncMock(return_value=fake_response)
            await collector_with_embedding.record(
                sample_data, sample_result, sample_decision, tenant_id=TENANT_ID
            )

        call_args = mock_pool.conn.execute.call_args[0]
        embedding_blob = call_args[COL_EMBEDDING]
        assert embedding_blob is not None
        values = struct.unpack(f"{len(fake_vector)}f", embedding_blob)
        assert len(values) == 3
        assert abs(values[0] - 0.1) < 1e-6

    @pytest.mark.asyncio
    async def test_embedding_failure_still_saves_record(
        self,
        collector_with_embedding: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        with patch("bsgateway.routing.collector.litellm") as mock_litellm:
            mock_litellm.aembedding = AsyncMock(side_effect=ConnectionError("cannot connect"))
            await collector_with_embedding.record(
                sample_data, sample_result, sample_decision, tenant_id=TENANT_ID
            )

        mock_pool.conn.execute.assert_called_once()
        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[COL_EMBEDDING] is None  # embedding should be None on failure

    @pytest.mark.asyncio
    async def test_empty_text_skips_embedding(
        self,
        collector_with_embedding: RoutingCollector,
        mock_pool: _MockPool,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        data = {"messages": [], "system": ""}

        with patch("bsgateway.routing.collector.litellm") as mock_litellm:
            await collector_with_embedding.record(
                data, sample_result, sample_decision, tenant_id=TENANT_ID
            )
            mock_litellm.aembedding.assert_not_called()

        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[COL_EMBEDDING] is None


class TestFeatureExtraction:
    def test_extract_features(self) -> None:
        data = {
            "messages": [
                {"role": "user", "content": "Fix this:\n```\nTraceback:\nError: bad\n```"},
                {"role": "assistant", "content": "Sure"},
                {"role": "user", "content": "More details"},
            ],
            "tools": [
                {"type": "function", "function": {"name": "a"}},
                {"type": "function", "function": {"name": "b"}},
            ],
        }
        features = RoutingCollector._extract_features(data, data["messages"])
        assert features["conversation_turns"] == 2
        assert features["code_block_count"] == 1
        assert features["has_error_trace"] is True
        assert features["tool_count"] == 2
        assert features["token_count"] > 0


class TestNexusMetadataRecording:
    @pytest.mark.asyncio
    async def test_nexus_metadata_saved_when_present(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
    ) -> None:
        decision = RoutingDecision(
            method="auto",
            original_model="auto",
            resolved_model="claude-opus",
            nexus_metadata=NexusMetadata(
                task_type="code-review",
                priority="high",
                complexity_hint=75,
            ),
            decision_source="blend",
        )
        await collector.record(sample_data, sample_result, decision, tenant_id=TENANT_ID)

        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[COL_NEXUS_TASK_TYPE] == "code-review"
        assert call_args[COL_NEXUS_PRIORITY] == "high"
        assert call_args[COL_NEXUS_COMPLEXITY_HINT] == 75
        assert call_args[COL_DECISION_SOURCE] == "blend"

    @pytest.mark.asyncio
    async def test_nexus_metadata_none_when_absent(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        await collector.record(sample_data, sample_result, sample_decision, tenant_id=TENANT_ID)

        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[COL_NEXUS_TASK_TYPE] is None
        assert call_args[COL_NEXUS_PRIORITY] is None
        assert call_args[COL_NEXUS_COMPLEXITY_HINT] is None
        assert call_args[COL_DECISION_SOURCE] is None

    @pytest.mark.asyncio
    async def test_partial_nexus_metadata_saved(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
    ) -> None:
        decision = RoutingDecision(
            method="auto",
            original_model="auto",
            resolved_model="claude-opus",
            nexus_metadata=NexusMetadata(priority="critical"),
            decision_source="priority_override",
        )
        await collector.record(sample_data, sample_result, decision, tenant_id=TENANT_ID)

        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[COL_NEXUS_TASK_TYPE] is None
        assert call_args[COL_NEXUS_PRIORITY] == "critical"
        assert call_args[COL_NEXUS_COMPLEXITY_HINT] is None
        assert call_args[COL_DECISION_SOURCE] == "priority_override"

    @pytest.mark.asyncio
    async def test_decision_source_without_nexus_metadata(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
    ) -> None:
        decision = RoutingDecision(
            method="auto",
            original_model="auto",
            resolved_model="claude-opus",
            decision_source="classifier",
        )
        await collector.record(sample_data, sample_result, decision, tenant_id=TENANT_ID)

        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[COL_NEXUS_TASK_TYPE] is None
        assert call_args[COL_NEXUS_PRIORITY] is None
        assert call_args[COL_NEXUS_COMPLEXITY_HINT] is None
        assert call_args[COL_DECISION_SOURCE] == "classifier"


class TestClose:
    @pytest.mark.asyncio
    async def test_close_pool(self, collector: RoutingCollector, mock_pool: _MockPool) -> None:
        await collector.close()
        mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_no_pool(self) -> None:
        collector = RoutingCollector(database_url="postgresql://test:test@localhost/test")
        await collector.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_is_idempotent(
        self, collector: RoutingCollector, mock_pool: _MockPool
    ) -> None:
        await collector.close()
        await collector.close()  # second call must not raise nor double-close
        mock_pool.close.assert_called_once()
        assert collector._pool is None
        assert collector._closed is True

    @pytest.mark.asyncio
    async def test_record_after_close_drops_silently(
        self,
        collector: RoutingCollector,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
        mock_pool: _MockPool,
    ) -> None:
        """Late record() after shutdown must not resurrect the closed pool."""
        await collector.close()
        # Should not raise nor try to acquire on the closed pool
        await collector.record(
            sample_data,
            sample_result,
            sample_decision,
            tenant_id=TENANT_ID,
        )
        mock_pool.conn.execute.assert_not_called()
