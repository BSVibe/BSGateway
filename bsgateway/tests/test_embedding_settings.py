"""Tests for per-tenant embedding configuration extraction."""

from __future__ import annotations

from bsgateway.embedding.settings import EmbeddingSettings


class TestFromTenantSettings:
    def test_full_config(self):
        result = EmbeddingSettings.from_tenant_settings(
            {
                "embedding": {
                    "model": "text-embedding-3-small",
                    "api_base": "https://api.openai.com/v1",
                    "timeout": 5.0,
                    "max_input_length": 4000,
                }
            }
        )
        assert result is not None
        assert result.model == "text-embedding-3-small"
        assert result.api_base == "https://api.openai.com/v1"
        assert result.timeout == 5.0
        assert result.max_input_length == 4000

    def test_minimal_config_uses_defaults(self):
        result = EmbeddingSettings.from_tenant_settings(
            {"embedding": {"model": "ollama/nomic-embed-text"}}
        )
        assert result is not None
        assert result.model == "ollama/nomic-embed-text"
        assert result.api_base is None
        assert result.timeout == 10.0
        assert result.max_input_length == 8000

    def test_missing_embedding_key_returns_none(self):
        assert EmbeddingSettings.from_tenant_settings({}) is None
        assert EmbeddingSettings.from_tenant_settings({"other": "stuff"}) is None

    def test_empty_settings_returns_none(self):
        assert EmbeddingSettings.from_tenant_settings(None) is None  # type: ignore[arg-type]

    def test_missing_model_returns_none(self):
        assert EmbeddingSettings.from_tenant_settings({"embedding": {}}) is None
        assert EmbeddingSettings.from_tenant_settings({"embedding": {"model": ""}}) is None
        assert EmbeddingSettings.from_tenant_settings({"embedding": {"model": None}}) is None

    def test_non_string_model_returns_none(self):
        assert EmbeddingSettings.from_tenant_settings({"embedding": {"model": 123}}) is None

    def test_non_dict_embedding_returns_none(self):
        assert EmbeddingSettings.from_tenant_settings({"embedding": "not a dict"}) is None

    def test_empty_api_base_normalized_to_none(self):
        result = EmbeddingSettings.from_tenant_settings(
            {"embedding": {"model": "m", "api_base": ""}}
        )
        assert result is not None
        assert result.api_base is None

    def test_to_dict_roundtrip(self):
        original = EmbeddingSettings(
            model="text-embedding-3-small",
            api_base="https://example.com",
            timeout=7.5,
            max_input_length=2000,
        )
        data = {"embedding": original.to_dict()}
        result = EmbeddingSettings.from_tenant_settings(data)
        assert result == original
