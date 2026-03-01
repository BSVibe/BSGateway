from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.routing.classifiers.static import StaticClassifier
from bsgateway.routing.hook import BSGatewayRouter, load_routing_config
from bsgateway.routing.models import (
    ClassifierConfig,
    ClassifierWeights,
    CollectorConfig,
    RoutingConfig,
    TierConfig,
)


@pytest.fixture
def routing_config() -> RoutingConfig:
    return RoutingConfig(
        tiers=[
            TierConfig(name="simple", score_range=(0, 30), model="local/llama3"),
            TierConfig(name="medium", score_range=(31, 65), model="gpt-4o-mini"),
            TierConfig(name="complex", score_range=(66, 100), model="claude-opus"),
        ],
        aliases={
            "auto": "auto_route",
            "local": "local/llama3",
            "fast": "gpt-4o-mini",
            "opus": "claude-opus",
        },
        passthrough_models={"local/llama3", "gpt-4o-mini", "gpt-4o", "claude-opus", "claude-sonnet"},
        classifier=ClassifierConfig(
            weights=ClassifierWeights(),
            complex_keywords=["architect", "design system", "refactor", "optimize"],
            simple_keywords=["hello", "thanks", "what is"],
        ),
        fallback_tier="medium",
        classifier_strategy="static",
        collector=CollectorConfig(enabled=False),
    )


@pytest.fixture
def router(routing_config: RoutingConfig) -> BSGatewayRouter:
    return BSGatewayRouter(config=routing_config)


class TestPassthrough:
    @pytest.mark.asyncio
    async def test_known_model_passes_through(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        assert result["model"] == "gpt-4o-mini"
        assert result["metadata"]["routing_decision"]["method"] == "passthrough"

    @pytest.mark.asyncio
    async def test_non_completion_call_type_skipped(self, router: BSGatewayRouter) -> None:
        data = {"model": "auto", "messages": []}
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "embeddings"
        )
        assert result["model"] == "auto"  # Unchanged


class TestAliasResolution:
    @pytest.mark.asyncio
    async def test_local_alias(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "local",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        assert result["model"] == "local/llama3"
        assert result["metadata"]["routing_decision"]["method"] == "alias"

    @pytest.mark.asyncio
    async def test_fast_alias(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "fast",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        assert result["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_opus_alias(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "opus",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        assert result["model"] == "claude-opus"


class TestAutoRouting:
    @pytest.mark.asyncio
    async def test_auto_routes_simple_to_local(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello, what is Python?"}],
        }
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        decision = result["metadata"]["routing_decision"]
        assert decision["method"] == "auto"
        assert decision["tier"] == "simple"
        assert result["model"] == "local/llama3"

    @pytest.mark.asyncio
    async def test_auto_routes_complex_to_claude(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [
                {"role": "user", "content": (
                    "Design a microservices architect for e-commerce. "
                    "Optimize for performance and scalability. "
                    "Refactor the existing monolith."
                )}
            ],
        }
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        decision = result["metadata"]["routing_decision"]
        assert decision["method"] == "auto"
        assert decision["tier"] == "complex"
        assert result["model"] == "claude-opus"

    @pytest.mark.asyncio
    async def test_unknown_model_triggers_auto(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "unknown-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        decision = result["metadata"]["routing_decision"]
        assert decision["method"] == "auto"

    @pytest.mark.asyncio
    async def test_auto_alias_triggers_auto(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        assert result["metadata"]["routing_decision"]["method"] == "auto"


class TestFallback:
    @pytest.mark.asyncio
    async def test_classifier_error_falls_back(self, router: BSGatewayRouter) -> None:
        router.classifier.classify = AsyncMock(side_effect=RuntimeError("boom"))
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        assert result["model"] == "gpt-4o-mini"  # fallback tier is medium
        assert result["metadata"]["routing_decision"]["tier"] == "medium"


class TestRoutingMetadata:
    @pytest.mark.asyncio
    async def test_metadata_included(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        decision = result["metadata"]["routing_decision"]
        assert "method" in decision
        assert "original_model" in decision
        assert "resolved_model" in decision
        assert "complexity_score" in decision
        assert "tier" in decision

    @pytest.mark.asyncio
    async def test_existing_metadata_preserved(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"user_id": "test-user"},
        }
        result = await router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        assert result["metadata"]["user_id"] == "test-user"
        assert "routing_decision" in result["metadata"]


class TestLoadRoutingConfig:
    def test_loads_from_yaml(self, tmp_path: Path) -> None:
        config_data = {
            "model_list": [
                {"model_name": "local/llama3", "litellm_params": {"model": "ollama_chat/llama3"}},
                {"model_name": "gpt-4o-mini", "litellm_params": {"model": "openai/gpt-4o-mini"}},
                {"model_name": "gpt-4o", "litellm_params": {"model": "openai/gpt-4o"}},
            ],
            "routing": {
                "tiers": {
                    "simple": {"score_range": [0, 30], "model": "local/llama3"},
                    "medium": {"score_range": [31, 65], "model": "gpt-4o-mini"},
                },
                "aliases": {"auto": "auto_route", "local": "local/llama3"},
                "classifier": {
                    "strategy": "static",
                    "static": {
                        "weights": {"token_count": 0.3},
                        "complex_keywords": ["architect"],
                    },
                    "llm": {
                        "api_base": "http://localhost:11434",
                        "model": "llama3",
                        "timeout": 2.0,
                    },
                },
                "collector": {
                    "enabled": False,
                },
            },
        }
        config_file = tmp_path / "gateway.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_routing_config(str(config_file))
        assert len(config.tiers) == 2
        assert config.aliases["auto"] == "auto_route"
        assert config.classifier.weights.token_count == 0.3
        assert config.classifier_strategy == "static"
        assert config.llm_classifier.timeout == 2.0
        assert config.collector.enabled is False

    def test_passthrough_auto_derived_from_model_list(self, tmp_path: Path) -> None:
        config_data = {
            "model_list": [
                {"model_name": "local/llama3", "litellm_params": {"model": "ollama_chat/llama3"}},
                {"model_name": "gpt-4o-mini", "litellm_params": {"model": "openai/gpt-4o-mini"}},
                {"model_name": "gpt-4o", "litellm_params": {"model": "openai/gpt-4o"}},
                {"model_name": "claude-opus", "litellm_params": {"model": "anthropic/claude-opus-4-0"}},
            ],
            "routing": {
                "tiers": {
                    "simple": {"score_range": [0, 30], "model": "local/llama3"},
                },
            },
        }
        config_file = tmp_path / "gateway.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_routing_config(str(config_file))
        assert "local/llama3" in config.passthrough_models
        assert "gpt-4o-mini" in config.passthrough_models
        assert "gpt-4o" in config.passthrough_models
        assert "claude-opus" in config.passthrough_models

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        config = load_routing_config(str(tmp_path / "nonexistent.yaml"))
        assert isinstance(config, RoutingConfig)
        assert len(config.tiers) == 0

    def test_loads_collector_config(self, tmp_path: Path) -> None:
        config_data = {
            "routing": {
                "tiers": {},
                "collector": {
                    "enabled": True,
                    "embedding": {
                        "model": "custom-embed",
                        "timeout": 10.0,
                    },
                },
            }
        }
        config_file = tmp_path / "gateway.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_routing_config(str(config_file))
        assert config.collector.enabled is True
        assert config.collector.embedding.model == "custom-embed"
        assert config.collector.embedding.timeout == 10.0
