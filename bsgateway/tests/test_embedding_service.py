"""Tests for EmbeddingService — generation + serialization with degradation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bsgateway.embedding.serialization import deserialize_embedding
from bsgateway.embedding.service import EmbeddingService


def _make_provider(*, model: str = "test-model", embed_return=None, embed_side_effect=None):
    provider = AsyncMock()
    provider.model = model
    if embed_side_effect is not None:
        provider.embed = AsyncMock(side_effect=embed_side_effect)
    else:
        provider.embed = AsyncMock(return_value=embed_return or [])
    return provider


class TestEmbedOne:
    @pytest.mark.asyncio
    async def test_success_returns_serialized_with_model_tag(self):
        provider = _make_provider(model="m1", embed_return=[[0.1, 0.2, 0.3]])
        svc = EmbeddingService(provider)
        result = await svc.embed_one("hello")
        assert result.text == "hello"
        assert result.model == "m1"
        assert result.embedding is not None
        vec = deserialize_embedding(result.embedding)
        assert vec == pytest.approx([0.1, 0.2, 0.3], abs=1e-6)
        provider.embed.assert_awaited_once_with(["hello"])

    @pytest.mark.asyncio
    async def test_failure_returns_none_embedding(self):
        provider = _make_provider(embed_side_effect=RuntimeError("API down"))
        svc = EmbeddingService(provider)
        result = await svc.embed_one("hello")
        assert result.text == "hello"
        assert result.embedding is None
        assert result.model == "test-model"


class TestEmbedMany:
    @pytest.mark.asyncio
    async def test_batch_success(self):
        provider = _make_provider(embed_return=[[0.1, 0.2], [0.3, 0.4]])
        svc = EmbeddingService(provider)
        results = await svc.embed_many(["a", "b"])
        assert len(results) == 2
        assert all(r.embedding is not None for r in results)
        assert results[0].text == "a"
        assert results[1].text == "b"
        provider.embed.assert_awaited_once_with(["a", "b"])

    @pytest.mark.asyncio
    async def test_batch_failure_marks_all_as_none(self):
        provider = _make_provider(embed_side_effect=RuntimeError("down"))
        svc = EmbeddingService(provider)
        results = await svc.embed_many(["a", "b", "c"])
        assert [r.text for r in results] == ["a", "b", "c"]
        assert all(r.embedding is None for r in results)

    @pytest.mark.asyncio
    async def test_empty_batch(self):
        provider = _make_provider()
        svc = EmbeddingService(provider)
        results = await svc.embed_many([])
        assert results == []
        provider.embed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_records_provider_model_per_result(self):
        provider = _make_provider(model="text-embedding-3-small", embed_return=[[1.0]])
        svc = EmbeddingService(provider)
        results = await svc.embed_many(["x"])
        assert results[0].model == "text-embedding-3-small"
