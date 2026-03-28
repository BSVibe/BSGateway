"""End-to-end integration tests for X-BSNexus-* metadata routing.

Verifies the full flow: request with X-BSNexus-* headers
→ hook extracts headers
→ routing decision influenced
→ collector logs metadata

All scenarios: no headers (backward compat), only priority, only hint,
both headers, and critical override.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.routing.collector import RoutingCollector
from bsgateway.routing.hook import BSGatewayRouter
from bsgateway.routing.models import (
    ClassifierConfig,
    ClassifierWeights,
    CollectorConfig,
    RoutingConfig,
    TierConfig,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def routing_config() -> RoutingConfig:
    return RoutingConfig(
        tiers=[
            TierConfig(name="simple", score_range=(0, 30), model="local/llama3"),
            TierConfig(name="medium", score_range=(31, 65), model="gpt-4o-mini"),
            TierConfig(name="complex", score_range=(66, 100), model="claude-opus"),
        ],
        aliases={"auto": "auto_route"},
        passthrough_models={"local/llama3", "gpt-4o-mini", "gpt-4o", "claude-opus"},
        classifier=ClassifierConfig(
            weights=ClassifierWeights(),
            complex_keywords=["architect", "refactor", "optimize"],
            simple_keywords=["hello", "thanks"],
        ),
        fallback_tier="medium",
        classifier_strategy="static",
        # collector disabled so __init__ skips settings import
        collector=CollectorConfig(enabled=False),
    )


@pytest.fixture
def mock_collector() -> MagicMock:
    collector = MagicMock(spec=RoutingCollector)
    collector.record = AsyncMock()
    return collector


@pytest.fixture
def router(routing_config: RoutingConfig, mock_collector: MagicMock) -> BSGatewayRouter:
    """Router with collector injected after construction."""
    r = BSGatewayRouter(config=routing_config)
    r.collector = mock_collector
    return r


async def _flush(router: BSGatewayRouter) -> None:
    """Await all pending background collector tasks."""
    if router._background_tasks:
        await asyncio.gather(*list(router._background_tasks), return_exceptions=True)


# ---------------------------------------------------------------------------
# Backward compatibility — no X-BSNexus-* headers
# ---------------------------------------------------------------------------


class TestE2EBackwardCompatibility:
    """Without X-BSNexus-* headers, routing behaviour must be identical to before."""

    @pytest.mark.asyncio
    async def test_passthrough_model_unaffected(self, router: BSGatewayRouter) -> None:
        data = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]}
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        assert result["model"] == "gpt-4o-mini"
        assert result["metadata"]["routing_decision"]["method"] == "passthrough"
        assert result["metadata"]["routing_decision"]["nexus_metadata"] is None

    @pytest.mark.asyncio
    async def test_auto_routing_works_without_headers(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello, what is Python?"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        decision = result["metadata"]["routing_decision"]
        assert decision["method"] == "auto"
        assert decision["nexus_metadata"] is None
        assert decision["decision_source"] == "classifier"

    @pytest.mark.asyncio
    async def test_collector_called_with_no_nexus_metadata(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        mock_collector.record.assert_called_once()
        _, _, decision = mock_collector.record.call_args[0]
        assert decision.nexus_metadata is None
        assert decision.decision_source == "classifier"

    @pytest.mark.asyncio
    async def test_non_completion_call_type_skipped(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        """Embeddings and other non-completion calls must not be routed or collected."""
        data = {"model": "auto", "messages": []}
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "embeddings")

        assert result["model"] == "auto"  # unchanged
        await _flush(router)
        mock_collector.record.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_metadata_preserved(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"user_id": "u-123"},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        assert result["metadata"]["user_id"] == "u-123"
        assert "routing_decision" in result["metadata"]


# ---------------------------------------------------------------------------
# Header extraction influence on routing
# ---------------------------------------------------------------------------


class TestE2EHeaderInfluencesRouting:
    """X-BSNexus-* headers are extracted and influence the routing decision."""

    @pytest.mark.asyncio
    async def test_only_task_type_header_uses_classifier(self, router: BSGatewayRouter) -> None:
        """task_type alone does not change routing logic — classifier is still used."""
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-task-type": "summarize"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        decision = result["metadata"]["routing_decision"]
        assert decision["decision_source"] == "classifier"
        assert decision["nexus_metadata"]["task_type"] == "summarize"

    @pytest.mark.asyncio
    async def test_non_critical_priority_uses_classifier(self, router: BSGatewayRouter) -> None:
        """Non-critical priority (high/medium/low) does not bypass the classifier."""
        for priority in ("low", "medium", "high"):
            data = {
                "model": "auto",
                "messages": [{"role": "user", "content": "hello"}],
                "metadata": {"headers": {"x-bsnexus-priority": priority}},
            }
            result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
            decision = result["metadata"]["routing_decision"]
            assert decision["decision_source"] == "classifier", f"priority={priority}"
            assert decision["nexus_metadata"]["priority"] == priority

    @pytest.mark.asyncio
    async def test_only_hint_header_uses_blend(self, router: BSGatewayRouter) -> None:
        """complexity_hint alone should trigger blending with the classifier score."""

        # Force classifier to return a known score
        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=0)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-complexity-hint": "100"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        decision = result["metadata"]["routing_decision"]
        assert decision["decision_source"] == "blend"
        # 0.7 * 0 + 0.3 * 100 = 30
        assert decision["complexity_score"] == 30
        assert decision["nexus_metadata"]["complexity_hint"] == 100

    @pytest.mark.asyncio
    async def test_priority_and_hint_uses_blend(self, router: BSGatewayRouter) -> None:
        """Non-critical priority + hint together should trigger blending."""

        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=10)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {
                "headers": {
                    "x-bsnexus-priority": "high",
                    "x-bsnexus-complexity-hint": "100",
                }
            },
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        decision = result["metadata"]["routing_decision"]
        assert decision["decision_source"] == "blend"
        # 0.7 * 10 + 0.3 * 100 = 7 + 30 = 37
        assert decision["complexity_score"] == 37
        assert decision["tier"] == "medium"
        assert result["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_all_headers_case_insensitive(self, router: BSGatewayRouter) -> None:
        """Header names are matched case-insensitively across the full flow."""

        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=0)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {
                "headers": {
                    "X-BSNexus-Task-Type": "translation",
                    "X-BSNEXUS-PRIORITY": "medium",
                    "X-BSNexus-Complexity-Hint": "60",
                }
            },
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        nexus = result["metadata"]["routing_decision"]["nexus_metadata"]
        assert nexus["task_type"] == "translation"
        assert nexus["priority"] == "medium"
        assert nexus["complexity_hint"] == 60


# ---------------------------------------------------------------------------
# Critical priority override
# ---------------------------------------------------------------------------


class TestE2ECriticalPriorityOverride:
    """Critical priority bypasses classification and routes to the highest tier."""

    @pytest.mark.asyncio
    async def test_critical_routes_to_highest_tier(self, router: BSGatewayRouter) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-priority": "critical"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        assert result["model"] == "claude-opus"
        decision = result["metadata"]["routing_decision"]
        assert decision["tier"] == "complex"
        assert decision["decision_source"] == "priority_override"

    @pytest.mark.asyncio
    async def test_critical_skips_classifier(self, router: BSGatewayRouter) -> None:
        classify_mock = AsyncMock()
        router.classifier.classify = classify_mock

        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-priority": "critical"}},
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        classify_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_critical_does_not_call_collector(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        """Critical priority returns early before the collector call."""
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-priority": "critical"}},
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        mock_collector.record.assert_not_called()

    @pytest.mark.asyncio
    async def test_critical_on_passthrough_model_is_still_passthrough(
        self, router: BSGatewayRouter
    ) -> None:
        """Critical priority on a passthrough model does not change routing."""
        data = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-priority": "critical"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        assert result["model"] == "gpt-4o-mini"
        assert result["metadata"]["routing_decision"]["method"] == "passthrough"

    @pytest.mark.asyncio
    async def test_critical_with_hint_still_overrides(self, router: BSGatewayRouter) -> None:
        """Critical priority takes precedence even when hint is also provided."""
        classify_mock = AsyncMock()
        router.classifier.classify = classify_mock

        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {
                "headers": {
                    "x-bsnexus-priority": "critical",
                    "x-bsnexus-complexity-hint": "10",
                }
            },
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        assert result["model"] == "claude-opus"
        assert result["metadata"]["routing_decision"]["decision_source"] == "priority_override"
        classify_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Collector receives correct metadata
# ---------------------------------------------------------------------------


class TestE2ECollectorLogsMetadata:
    """Collector receives the correct NexusMetadata and decision_source in each scenario."""

    @pytest.mark.asyncio
    async def test_collector_receives_full_nexus_metadata(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=20)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {
                "headers": {
                    "x-bsnexus-task-type": "code-review",
                    "x-bsnexus-priority": "high",
                    "x-bsnexus-complexity-hint": "80",
                }
            },
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        mock_collector.record.assert_called_once()
        _, _, decision = mock_collector.record.call_args[0]
        assert decision.nexus_metadata is not None
        assert decision.nexus_metadata.task_type == "code-review"
        assert decision.nexus_metadata.priority == "high"
        assert decision.nexus_metadata.complexity_hint == 80
        assert decision.decision_source == "blend"

    @pytest.mark.asyncio
    async def test_collector_receives_classifier_source_without_hint(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-task-type": "summarize"}},
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        mock_collector.record.assert_called_once()
        _, _, decision = mock_collector.record.call_args[0]
        assert decision.nexus_metadata.task_type == "summarize"
        assert decision.decision_source == "classifier"

    @pytest.mark.asyncio
    async def test_collector_receives_none_nexus_when_no_headers(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        mock_collector.record.assert_called_once()
        _, _, decision = mock_collector.record.call_args[0]
        assert decision.nexus_metadata is None

    @pytest.mark.asyncio
    async def test_collector_receives_correct_models(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=10)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-complexity-hint": "100"}},
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        _, _, decision = mock_collector.record.call_args[0]
        assert decision.original_model == "auto"
        # blended = 0.7*10 + 0.3*100 = 37 → medium tier
        assert decision.resolved_model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_collector_not_called_for_passthrough(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        """Passthrough requests do not trigger the collector."""
        data = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        mock_collector.record.assert_not_called()


# ---------------------------------------------------------------------------
# Complete scenario tests
# ---------------------------------------------------------------------------


class TestE2EScenarios:
    """Scenario-level integration tests covering every header combination end-to-end."""

    @pytest.mark.asyncio
    async def test_scenario_no_headers(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        """Scenario: request with no X-BSNexus-* headers (baseline)."""
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello, what is Python?"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        decision = result["metadata"]["routing_decision"]
        assert decision["method"] == "auto"
        assert decision["nexus_metadata"] is None
        assert decision["decision_source"] == "classifier"
        mock_collector.record.assert_called_once()
        _, _, rec_decision = mock_collector.record.call_args[0]
        assert rec_decision.nexus_metadata is None

    @pytest.mark.asyncio
    async def test_scenario_only_priority_non_critical(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        """Scenario: only priority=high header."""
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-priority": "high"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        decision = result["metadata"]["routing_decision"]
        assert decision["decision_source"] == "classifier"
        assert decision["nexus_metadata"]["priority"] == "high"
        mock_collector.record.assert_called_once()
        _, _, rec_decision = mock_collector.record.call_args[0]
        assert rec_decision.nexus_metadata.priority == "high"
        assert rec_decision.nexus_metadata.complexity_hint is None

    @pytest.mark.asyncio
    async def test_scenario_only_hint(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        """Scenario: only complexity_hint header."""

        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=0)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-complexity-hint": "50"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        decision = result["metadata"]["routing_decision"]
        assert decision["decision_source"] == "blend"
        # 0.7*0 + 0.3*50 = 15 → simple tier
        assert decision["complexity_score"] == 15
        assert decision["tier"] == "simple"
        mock_collector.record.assert_called_once()
        _, _, rec_decision = mock_collector.record.call_args[0]
        assert rec_decision.nexus_metadata.complexity_hint == 50
        assert rec_decision.decision_source == "blend"

    @pytest.mark.asyncio
    async def test_scenario_both_priority_and_hint(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        """Scenario: both priority=high and complexity_hint=90."""

        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=20)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {
                "headers": {
                    "x-bsnexus-priority": "high",
                    "x-bsnexus-complexity-hint": "90",
                }
            },
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        decision = result["metadata"]["routing_decision"]
        # 0.7*20 + 0.3*90 = 14 + 27 = 41 → medium tier
        assert decision["decision_source"] == "blend"
        assert decision["complexity_score"] == 41
        assert decision["tier"] == "medium"
        mock_collector.record.assert_called_once()
        _, _, rec_decision = mock_collector.record.call_args[0]
        assert rec_decision.nexus_metadata.priority == "high"
        assert rec_decision.nexus_metadata.complexity_hint == 90

    @pytest.mark.asyncio
    async def test_scenario_critical_override(
        self, router: BSGatewayRouter, mock_collector: MagicMock
    ) -> None:
        """Scenario: critical priority overrides everything."""
        classify_mock = AsyncMock()
        router.classifier.classify = classify_mock

        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "urgent task"}],
            "metadata": {
                "headers": {
                    "x-bsnexus-task-type": "incident-response",
                    "x-bsnexus-priority": "critical",
                }
            },
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _flush(router)

        assert result["model"] == "claude-opus"
        decision = result["metadata"]["routing_decision"]
        assert decision["method"] == "auto"
        assert decision["tier"] == "complex"
        assert decision["decision_source"] == "priority_override"
        assert decision["nexus_metadata"]["priority"] == "critical"
        assert decision["nexus_metadata"]["task_type"] == "incident-response"
        # Classifier was never called
        classify_mock.assert_not_called()
        # Collector was NOT called (critical path returns early)
        mock_collector.record.assert_not_called()
