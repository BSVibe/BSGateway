from __future__ import annotations

import struct
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.routing.collector import RoutingCollector, SqlLoader
from bsgateway.routing.models import EmbeddingConfig, NexusMetadata, RoutingDecision


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
        await collector.record(sample_data, sample_result, sample_decision)
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
        await collector.record(sample_data, sample_result, sample_decision)

        call_args = mock_pool.conn.execute.call_args[0]
        # args[0] = query, args[1:] = parameters
        assert "INSERT INTO routing_logs" in call_args[0]
        assert "microservices architecture" in call_args[1]  # user_text
        assert "expert architect" in call_args[2]  # system_prompt
        assert call_args[9] == "complex"  # tier
        assert call_args[10] == "llm"  # strategy
        assert call_args[12] == "auto"  # original_model
        assert call_args[13] == "claude-opus"  # resolved_model
        assert call_args[14] is None  # embedding (disabled)

    @pytest.mark.asyncio
    async def test_no_embedding_when_disabled(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        await collector.record(sample_data, sample_result, sample_decision)
        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[14] is None  # embedding

    @pytest.mark.asyncio
    async def test_multiple_records(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        await collector.record(sample_data, sample_result, sample_decision)
        await collector.record(sample_data, sample_result, sample_decision)
        await collector.record(sample_data, sample_result, sample_decision)
        assert mock_pool.conn.execute.call_count == 3


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
            await collector_with_embedding.record(sample_data, sample_result, sample_decision)

        call_args = mock_pool.conn.execute.call_args[0]
        embedding_blob = call_args[14]
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
            await collector_with_embedding.record(sample_data, sample_result, sample_decision)

        mock_pool.conn.execute.assert_called_once()
        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[14] is None  # embedding should be None on failure

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
            await collector_with_embedding.record(data, sample_result, sample_decision)
            mock_litellm.aembedding.assert_not_called()

        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[14] is None


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
        await collector.record(sample_data, sample_result, decision)

        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[15] == "code-review"  # nexus_task_type
        assert call_args[16] == "high"  # nexus_priority
        assert call_args[17] == 75  # nexus_complexity_hint
        assert call_args[18] == "blend"  # decision_source

    @pytest.mark.asyncio
    async def test_nexus_metadata_none_when_absent(
        self,
        collector: RoutingCollector,
        mock_pool: _MockPool,
        sample_data: dict,
        sample_result: ClassificationResult,
        sample_decision: RoutingDecision,
    ) -> None:
        await collector.record(sample_data, sample_result, sample_decision)

        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[15] is None  # nexus_task_type
        assert call_args[16] is None  # nexus_priority
        assert call_args[17] is None  # nexus_complexity_hint
        assert call_args[18] is None  # decision_source

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
        await collector.record(sample_data, sample_result, decision)

        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[15] is None  # nexus_task_type (not set)
        assert call_args[16] == "critical"  # nexus_priority
        assert call_args[17] is None  # nexus_complexity_hint (not set)
        assert call_args[18] == "priority_override"  # decision_source

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
        await collector.record(sample_data, sample_result, decision)

        call_args = mock_pool.conn.execute.call_args[0]
        assert call_args[15] is None  # nexus_task_type
        assert call_args[16] is None  # nexus_priority
        assert call_args[17] is None  # nexus_complexity_hint
        assert call_args[18] == "classifier"  # decision_source


class TestClose:
    @pytest.mark.asyncio
    async def test_close_pool(self, collector: RoutingCollector, mock_pool: _MockPool) -> None:
        await collector.close()
        mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_no_pool(self) -> None:
        collector = RoutingCollector(database_url="postgresql://test:test@localhost/test")
        await collector.close()  # Should not raise
