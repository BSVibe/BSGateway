from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from bsgateway.routing.hook import BSGatewayRouter, load_routing_config
from bsgateway.routing.models import (
    ClassifierConfig,
    ClassifierWeights,
    CollectorConfig,
    NexusMetadata,
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
        passthrough_models={
            "local/llama3",
            "gpt-4o-mini",
            "gpt-4o",
            "claude-opus",
            "claude-sonnet",
        },
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
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["model"] == "gpt-4o-mini"
        assert result["metadata"]["routing_decision"]["method"] == "passthrough"

    @pytest.mark.asyncio
    async def test_non_completion_call_type_skipped(self, router: BSGatewayRouter) -> None:
        data = {"model": "auto", "messages": []}
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "embeddings")
        assert result["model"] == "auto"  # Unchanged


class TestAliasResolution:
    @pytest.mark.asyncio
    async def test_local_alias(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "local",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["model"] == "local/llama3"
        assert result["metadata"]["routing_decision"]["method"] == "alias"

    @pytest.mark.asyncio
    async def test_fast_alias(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "fast",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_opus_alias(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "opus",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["model"] == "claude-opus"


class TestAutoRouting:
    @pytest.mark.asyncio
    async def test_auto_routes_simple_to_local(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello, what is Python?"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        decision = result["metadata"]["routing_decision"]
        assert decision["method"] == "auto"
        assert decision["tier"] == "simple"
        assert result["model"] == "local/llama3"

    @pytest.mark.asyncio
    async def test_auto_routes_complex_to_claude(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Design a microservices architect for e-commerce. "
                        "Optimize for performance and scalability. "
                        "Refactor the existing monolith."
                    ),
                }
            ],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
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
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        decision = result["metadata"]["routing_decision"]
        assert decision["method"] == "auto"

    @pytest.mark.asyncio
    async def test_auto_alias_triggers_auto(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["metadata"]["routing_decision"]["method"] == "auto"


class TestFallback:
    @pytest.mark.asyncio
    async def test_classifier_error_falls_back(self, router: BSGatewayRouter) -> None:
        router.classifier.classify = AsyncMock(side_effect=RuntimeError("boom"))
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["model"] == "gpt-4o-mini"  # fallback tier is medium
        assert result["metadata"]["routing_decision"]["tier"] == "medium"


class TestRoutingMetadata:
    @pytest.mark.asyncio
    async def test_metadata_included(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
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
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["metadata"]["user_id"] == "test-user"
        assert "routing_decision" in result["metadata"]


class TestAutoRoutePatterns:
    @pytest.fixture
    def pattern_config(self) -> RoutingConfig:
        return RoutingConfig(
            tiers=[
                TierConfig(name="simple", score_range=(0, 30), model="local/llama3"),
                TierConfig(name="medium", score_range=(31, 65), model="gpt-4o-mini"),
                TierConfig(name="complex", score_range=(66, 100), model="claude-opus"),
            ],
            aliases={"auto": "auto_route"},
            auto_route_patterns=["claude-*"],
            passthrough_models={"local/llama3", "gpt-4o-mini", "claude-opus"},
            classifier=ClassifierConfig(
                weights=ClassifierWeights(),
                complex_keywords=["architect", "refactor"],
                simple_keywords=["hello", "thanks"],
            ),
            fallback_tier="medium",
            classifier_strategy="static",
            collector=CollectorConfig(enabled=False),
        )

    @pytest.fixture
    def pattern_router(self, pattern_config: RoutingConfig) -> BSGatewayRouter:
        return BSGatewayRouter(config=pattern_config)

    @pytest.mark.asyncio
    async def test_claude_code_model_auto_routed(self, pattern_router: BSGatewayRouter) -> None:
        """Claude Code's default model IDs should be auto-routed, not rejected."""
        data = {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await pattern_router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        decision = result["metadata"]["routing_decision"]
        assert decision["method"] == "auto"
        assert decision["original_model"] == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_future_claude_model_auto_routed(self, pattern_router: BSGatewayRouter) -> None:
        """Future Claude model IDs should also match without config changes."""
        data = {
            "model": "claude-opus-5-0",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await pattern_router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        assert result["metadata"]["routing_decision"]["method"] == "auto"

    @pytest.mark.asyncio
    async def test_non_matching_model_still_auto_routes(
        self,
        pattern_router: BSGatewayRouter,
    ) -> None:
        """Unknown models that don't match patterns should still auto-route."""
        data = {
            "model": "some-unknown-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await pattern_router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        assert result["metadata"]["routing_decision"]["method"] == "auto"

    @pytest.mark.asyncio
    async def test_passthrough_takes_priority_over_pattern(
        self,
        pattern_router: BSGatewayRouter,
    ) -> None:
        """Passthrough models should not be intercepted by patterns."""
        data = {
            "model": "claude-opus",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await pattern_router.async_pre_call_hook(
            MagicMock(), MagicMock(), data, "completion"
        )
        assert result["metadata"]["routing_decision"]["method"] == "passthrough"


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
                {
                    "model_name": "claude-opus",
                    "litellm_params": {"model": "anthropic/claude-opus-4-0"},
                },
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

    def test_loads_auto_route_patterns(self, tmp_path: Path) -> None:
        config_data = {
            "routing": {
                "tiers": {},
                "auto_route_patterns": ["claude-*", "gpt-*"],
                "collector": {"enabled": False},
            },
        }
        config_file = tmp_path / "gateway.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_routing_config(str(config_file))
        assert config.auto_route_patterns == ["claude-*", "gpt-*"]

    def test_missing_auto_route_patterns_defaults_empty(self, tmp_path: Path) -> None:
        config_data = {
            "routing": {
                "tiers": {},
                "collector": {"enabled": False},
            },
        }
        config_file = tmp_path / "gateway.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_routing_config(str(config_file))
        assert config.auto_route_patterns == []

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
        assert config.collector.embedding is not None
        assert config.collector.embedding.model == "custom-embed"
        assert config.collector.embedding.timeout == 10.0


class TestNexusMetadataExtraction:
    """Tests for X-BSNexus-* header extraction into NexusMetadata."""

    @pytest.mark.asyncio
    async def test_extracts_all_headers(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {
                "headers": {
                    "x-bsnexus-task-type": "summarize",
                    "x-bsnexus-priority": "high",
                    "x-bsnexus-complexity-hint": "75",
                }
            },
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        nexus = result["metadata"]["routing_decision"]["nexus_metadata"]
        assert nexus is not None
        assert nexus["task_type"] == "summarize"
        assert nexus["priority"] == "high"
        assert nexus["complexity_hint"] == 75

    @pytest.mark.asyncio
    async def test_no_headers_nexus_metadata_is_none(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["metadata"]["routing_decision"]["nexus_metadata"] is None

    @pytest.mark.asyncio
    async def test_empty_headers_nexus_metadata_is_none(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["metadata"]["routing_decision"]["nexus_metadata"] is None

    @pytest.mark.asyncio
    async def test_partial_headers_priority_only(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-priority": "critical"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        nexus = result["metadata"]["routing_decision"]["nexus_metadata"]
        assert nexus is not None
        assert nexus["task_type"] is None
        assert nexus["priority"] == "critical"
        assert nexus["complexity_hint"] is None

    @pytest.mark.asyncio
    async def test_partial_headers_task_type_only(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-task-type": "code-review"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        nexus = result["metadata"]["routing_decision"]["nexus_metadata"]
        assert nexus is not None
        assert nexus["task_type"] == "code-review"
        assert nexus["priority"] is None
        assert nexus["complexity_hint"] is None

    @pytest.mark.asyncio
    async def test_invalid_complexity_hint_yields_none(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {
                "headers": {
                    "x-bsnexus-priority": "low",
                    "x-bsnexus-complexity-hint": "not-a-number",
                }
            },
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        nexus = result["metadata"]["routing_decision"]["nexus_metadata"]
        assert nexus is not None
        assert nexus["complexity_hint"] is None

    @pytest.mark.asyncio
    async def test_header_names_case_insensitive(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {
                "headers": {
                    "X-BSNexus-Task-Type": "translation",
                    "X-BSNEXUS-PRIORITY": "medium",
                    "X-BSNexus-Complexity-Hint": "50",
                }
            },
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        nexus = result["metadata"]["routing_decision"]["nexus_metadata"]
        assert nexus is not None
        assert nexus["task_type"] == "translation"
        assert nexus["priority"] == "medium"
        assert nexus["complexity_hint"] == 50

    @pytest.mark.asyncio
    async def test_backward_compat_passthrough_unaffected(self, router: BSGatewayRouter) -> None:
        """Without X-BSNexus-* headers, passthrough behavior must be identical."""
        data = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["model"] == "gpt-4o-mini"
        assert result["metadata"]["routing_decision"]["method"] == "passthrough"
        assert result["metadata"]["routing_decision"]["nexus_metadata"] is None

    @pytest.mark.asyncio
    async def test_nexus_metadata_in_routing_decision_keys(self, router: BSGatewayRouter) -> None:
        """routing_decision dict must always include nexus_metadata key."""
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert "nexus_metadata" in result["metadata"]["routing_decision"]

    def test_nexus_metadata_dataclass_fields(self) -> None:
        """NexusMetadata dataclass should have correct fields and defaults."""
        meta = NexusMetadata()
        assert meta.task_type is None
        assert meta.priority is None
        assert meta.complexity_hint is None

        meta2 = NexusMetadata(task_type="qa", priority="high", complexity_hint=80)
        assert meta2.task_type == "qa"
        assert meta2.priority == "high"
        assert meta2.complexity_hint == 80
