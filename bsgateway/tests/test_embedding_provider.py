"""Tests for the LiteLLM embedding provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bsgateway.embedding.provider import (
    EmbeddingProvider,
    LiteLLMEmbeddingProvider,
    build_provider,
)
from bsgateway.embedding.settings import EmbeddingSettings


def _settings(**overrides) -> EmbeddingSettings:
    base = {"model": "text-embedding-3-small"}
    base.update(overrides)
    return EmbeddingSettings(**base)


class TestLiteLLMEmbeddingProvider:
    def test_implements_protocol(self):
        provider = LiteLLMEmbeddingProvider(_settings())
        assert isinstance(provider, EmbeddingProvider)

    def test_exposes_model_name(self):
        provider = LiteLLMEmbeddingProvider(_settings(model="custom-model"))
        assert provider.model == "custom-model"

    @pytest.mark.asyncio
    async def test_embed_calls_litellm_with_settings(self):
        mock_response = MagicMock()
        mock_response.data = [{"embedding": [0.1, 0.2, 0.3]}]
        provider = LiteLLMEmbeddingProvider(
            _settings(
                model="text-embedding-3-small",
                api_base="https://api.openai.com/v1",
                timeout=7.0,
            )
        )
        with patch("litellm.aembedding", new=AsyncMock(return_value=mock_response)) as mock_embed:
            result = await provider.embed(["hello"])
        assert result == [[0.1, 0.2, 0.3]]
        mock_embed.assert_awaited_once()
        call_kwargs = mock_embed.call_args.kwargs
        assert call_kwargs["model"] == "text-embedding-3-small"
        assert call_kwargs["api_base"] == "https://api.openai.com/v1"
        assert call_kwargs["timeout"] == 7.0

    @pytest.mark.asyncio
    async def test_truncates_long_input(self):
        mock_response = MagicMock()
        mock_response.data = [{"embedding": [1.0]}]
        provider = LiteLLMEmbeddingProvider(_settings(max_input_length=10))
        with patch("litellm.aembedding", new=AsyncMock(return_value=mock_response)) as mock_embed:
            await provider.embed(["a" * 100])
        sent = mock_embed.call_args.kwargs["input"][0]
        assert len(sent) == 10

    @pytest.mark.asyncio
    async def test_batch_embed(self):
        mock_response = MagicMock()
        mock_response.data = [
            {"embedding": [0.1]},
            {"embedding": [0.2]},
        ]
        provider = LiteLLMEmbeddingProvider(_settings())
        with patch("litellm.aembedding", new=AsyncMock(return_value=mock_response)):
            result = await provider.embed(["a", "b"])
        assert result == [[0.1], [0.2]]

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        provider = LiteLLMEmbeddingProvider(_settings())
        # No litellm call should happen
        with patch("litellm.aembedding", new=AsyncMock()) as mock_embed:
            result = await provider.embed([])
        assert result == []
        mock_embed.assert_not_awaited()


class TestBuildProvider:
    def test_returns_none_when_settings_none(self):
        assert build_provider(None) is None

    def test_returns_provider_when_settings_present(self):
        provider = build_provider(_settings())
        assert provider is not None
        assert provider.model == "text-embedding-3-small"
