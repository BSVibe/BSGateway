"""End-to-end integration tests for X-BSNexus-* header routing flow (TASK-004).

Tests the complete pipeline:
  1. Request with X-BSNexus-* headers enters async_pre_call_hook
  2. Hook extracts NexusMetadata from headers
  3. Routing decision is influenced (priority override / hint blend / classifier)
  4. Collector records the routing decision including NexusMetadata fields

These differ from unit tests in test_hook.py in that they:
  - Enable the collector (via mock injection)
  - Verify collector receives correct NexusMetadata in the RoutingDecision
  - Cover all header combinations end-to-end in a single cohesive suite
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.routing.hook import BSGatewayRouter
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
        aliases={"auto": "auto_route"},
        passthrough_models={
            "local/llama3",
            "gpt-4o-mini",
            "gpt-4o",
            "claude-opus",
            "claude-sonnet",
        },
        classifier=ClassifierConfig(
            weights=ClassifierWeights(),
            complex_keywords=["architect", "design"],
            simple_keywords=["hello", "what is"],
        ),
        fallback_tier="medium",
        classifier_strategy="static",
        collector=CollectorConfig(enabled=False),  # Disabled; mock injected below
    )


@pytest.fixture
def mock_collector() -> AsyncMock:
    collector = AsyncMock()
    collector.record = AsyncMock()
    return collector


@pytest.fixture
def router(routing_config: RoutingConfig, mock_collector: AsyncMock) -> BSGatewayRouter:
    r = BSGatewayRouter(config=routing_config)
    r.collector = mock_collector  # Inject mock collector to capture calls
    return r


async def _drain(router: BSGatewayRouter) -> None:
    """Wait for pending background collector tasks to complete."""
    pending = list(router._background_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.sleep(0)  # Extra yield for safety


# ---------------------------------------------------------------------------
# Scenario 1: No headers — backward compatibility
# ---------------------------------------------------------------------------


class TestE2ENoHeaders:
    """Without X-BSNexus-* headers, behavior must be identical to before."""

    @pytest.mark.asyncio
    async def test_routing_uses_classifier(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello world"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        decision = result["metadata"]["routing_decision"]
        assert decision["method"] == "auto"
        assert decision["decision_source"] == "classifier"
        assert decision["nexus_metadata"] is None

    @pytest.mark.asyncio
    async def test_collector_receives_null_nexus_fields(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello world"}],
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        mock_collector.record.assert_called_once()
        _, _, decision = mock_collector.record.call_args[0]
        assert decision.nexus_metadata is None
        assert decision.decision_source == "classifier"

    @pytest.mark.asyncio
    async def test_passthrough_no_collector_call(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        """Passthrough path doesn't go through auto-routing; collector is not called."""
        data = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        mock_collector.record.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 2: Only X-BSNexus-Priority (non-critical)
# ---------------------------------------------------------------------------


class TestE2EOnlyPriority:
    """Non-critical priority doesn't override routing, but is recorded."""

    @pytest.mark.asyncio
    async def test_high_priority_uses_classifier(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-priority": "high"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        decision = result["metadata"]["routing_decision"]
        assert decision["decision_source"] == "classifier"
        assert decision["nexus_metadata"]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_high_priority_collector_records_priority(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-priority": "high"}},
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        mock_collector.record.assert_called_once()
        _, _, decision = mock_collector.record.call_args[0]
        assert decision.nexus_metadata is not None
        assert decision.nexus_metadata.priority == "high"
        assert decision.nexus_metadata.complexity_hint is None
        assert decision.decision_source == "classifier"

    @pytest.mark.asyncio
    async def test_low_priority_uses_classifier(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-priority": "low"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        decision = result["metadata"]["routing_decision"]
        assert decision["decision_source"] == "classifier"
        assert decision["nexus_metadata"]["priority"] == "low"


# ---------------------------------------------------------------------------
# Scenario 3: Only X-BSNexus-Complexity-Hint
# ---------------------------------------------------------------------------


class TestE2EOnlyHint:
    """Complexity hint alone triggers blending with classifier score."""

    @pytest.mark.asyncio
    async def test_hint_triggers_blend_decision_source(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=10)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-complexity-hint": "90"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        decision = result["metadata"]["routing_decision"]
        assert decision["decision_source"] == "blend"
        # 0.7 * 10 + 0.3 * 90 = 7 + 27 = 34 → medium tier
        assert decision["complexity_score"] == 34
        assert decision["tier"] == "medium"
        assert result["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_hint_collector_records_hint_and_blend(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=10)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-complexity-hint": "90"}},
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        mock_collector.record.assert_called_once()
        _, _, decision = mock_collector.record.call_args[0]
        assert decision.nexus_metadata is not None
        assert decision.nexus_metadata.complexity_hint == 90
        assert decision.nexus_metadata.priority is None
        assert decision.decision_source == "blend"

    @pytest.mark.asyncio
    async def test_low_hint_keeps_simple_tier(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        """Low hint + classifier score=0 → still simple tier after blending."""
        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=0)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-complexity-hint": "10"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        decision = result["metadata"]["routing_decision"]
        # 0.7 * 0 + 0.3 * 10 = 3 → simple tier
        assert decision["decision_source"] == "blend"
        assert decision["complexity_score"] == 3
        assert decision["tier"] == "simple"
        assert result["model"] == "local/llama3"


# ---------------------------------------------------------------------------
# Scenario 4: Both headers (non-critical priority + hint)
# ---------------------------------------------------------------------------


class TestE2EBothHeaders:
    """Both priority (non-critical) and hint → blend applies."""

    @pytest.mark.asyncio
    async def test_high_priority_with_hint_blends(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=20)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {
                "headers": {"x-bsnexus-priority": "high", "x-bsnexus-complexity-hint": "80"}
            },
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        decision = result["metadata"]["routing_decision"]
        # 0.7 * 20 + 0.3 * 80 = 14 + 24 = 38 → medium tier
        assert decision["decision_source"] == "blend"
        assert decision["complexity_score"] == 38
        assert decision["tier"] == "medium"
        assert result["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_all_three_headers_collector_records_all_fields(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        """Collector records all nexus fields when all three headers are present."""
        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=20)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "code review task"}],
            "metadata": {
                "headers": {
                    "x-bsnexus-task-type": "code-review",
                    "x-bsnexus-priority": "high",
                    "x-bsnexus-complexity-hint": "80",
                }
            },
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        mock_collector.record.assert_called_once()
        _, _, decision = mock_collector.record.call_args[0]
        assert decision.nexus_metadata is not None
        assert decision.nexus_metadata.task_type == "code-review"
        assert decision.nexus_metadata.priority == "high"
        assert decision.nexus_metadata.complexity_hint == 80
        assert decision.decision_source == "blend"

    @pytest.mark.asyncio
    async def test_medium_priority_with_hint_blend_to_complex(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="complex", strategy="static", score=70)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "architecture task"}],
            "metadata": {
                "headers": {
                    "x-bsnexus-task-type": "architecture",
                    "x-bsnexus-priority": "medium",
                    "x-bsnexus-complexity-hint": "60",
                }
            },
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        decision = result["metadata"]["routing_decision"]
        # 0.7 * 70 + 0.3 * 60 = 49 + 18 = 67 → complex tier
        assert decision["decision_source"] == "blend"
        assert decision["complexity_score"] == 67
        assert decision["tier"] == "complex"
        assert result["model"] == "claude-opus"

        mock_collector.record.assert_called_once()
        _, _, recorded = mock_collector.record.call_args[0]
        assert recorded.nexus_metadata.task_type == "architecture"
        assert recorded.nexus_metadata.priority == "medium"
        assert recorded.nexus_metadata.complexity_hint == 60
        assert recorded.decision_source == "blend"


# ---------------------------------------------------------------------------
# Scenario 5: Critical priority override
# ---------------------------------------------------------------------------


class TestE2ECriticalOverride:
    """X-BSNexus-Priority: critical routes to the highest tier unconditionally."""

    @pytest.mark.asyncio
    async def test_critical_routes_to_highest_tier(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "simple question"}],
            "metadata": {"headers": {"x-bsnexus-priority": "critical"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        assert result["model"] == "claude-opus"
        decision = result["metadata"]["routing_decision"]
        assert decision["tier"] == "complex"
        assert decision["decision_source"] == "priority_override"
        assert decision["nexus_metadata"]["priority"] == "critical"

    @pytest.mark.asyncio
    async def test_critical_bypasses_classifier(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        classify_mock = AsyncMock()
        router.classifier.classify = classify_mock
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "simple question"}],
            "metadata": {"headers": {"x-bsnexus-priority": "critical"}},
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        classify_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_critical_with_hint_still_overrides(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        """Critical + hint → priority_override wins; hint is ignored."""
        classify_mock = AsyncMock()
        router.classifier.classify = classify_mock
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "simple question"}],
            "metadata": {
                "headers": {"x-bsnexus-priority": "critical", "x-bsnexus-complexity-hint": "5"}
            },
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        assert result["model"] == "claude-opus"
        assert result["metadata"]["routing_decision"]["decision_source"] == "priority_override"
        classify_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_critical_override_collector_not_called(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        """Critical override returns early before the collector call; collector is not invoked."""
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "simple question"}],
            "metadata": {"headers": {"x-bsnexus-priority": "critical"}},
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        mock_collector.record.assert_not_called()

    @pytest.mark.asyncio
    async def test_critical_on_passthrough_model_unaffected(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        """Critical priority on a direct model must not change routing; passthrough wins."""
        data = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-priority": "critical"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        assert result["model"] == "gpt-4o-mini"
        assert result["metadata"]["routing_decision"]["method"] == "passthrough"
        mock_collector.record.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 6: Edge cases and additional coverage
# ---------------------------------------------------------------------------


class TestE2EEdgeCases:
    """Additional combinations and edge cases."""

    @pytest.mark.asyncio
    async def test_task_type_only_uses_classifier_no_routing_change(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        """Task type alone doesn't change routing; still uses classifier."""
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-task-type": "translation"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        decision = result["metadata"]["routing_decision"]
        assert decision["decision_source"] == "classifier"
        assert decision["nexus_metadata"]["task_type"] == "translation"

        mock_collector.record.assert_called_once()
        _, _, recorded = mock_collector.record.call_args[0]
        assert recorded.nexus_metadata.task_type == "translation"
        assert recorded.nexus_metadata.priority is None
        assert recorded.nexus_metadata.complexity_hint is None

    @pytest.mark.asyncio
    async def test_non_completion_call_type_skips_routing(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        """Embeddings and other non-completion calls are passed through unchanged."""
        data = {
            "model": "auto",
            "messages": [],
            "metadata": {"headers": {"x-bsnexus-priority": "critical"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "embeddings")
        await _drain(router)

        assert result["model"] == "auto"
        mock_collector.record.assert_not_called()

    @pytest.mark.asyncio
    async def test_hint_100_from_simple_stays_simple(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        """Hint=100, classifier score=0 → 0.7*0 + 0.3*100 = 30 → simple (boundary)."""
        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="simple", strategy="static", score=0)
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"headers": {"x-bsnexus-complexity-hint": "100"}},
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        await _drain(router)

        decision = result["metadata"]["routing_decision"]
        assert decision["decision_source"] == "blend"
        assert decision["complexity_score"] == 30  # Boundary: simple (0-30)
        assert decision["tier"] == "simple"

    @pytest.mark.asyncio
    async def test_routing_decision_always_has_required_keys(
        self, router: BSGatewayRouter, mock_collector: AsyncMock
    ) -> None:
        """routing_decision dict must always include nexus_metadata and decision_source keys."""
        for model, headers in [
            ("auto", {}),
            ("auto", {"x-bsnexus-priority": "high"}),
            ("gpt-4o-mini", {}),
        ]:
            data_item: dict = {"model": model, "messages": [{"role": "user", "content": "hello"}]}
            if headers:
                data_item["metadata"] = {"headers": headers}
            result = await router.async_pre_call_hook(
                MagicMock(), MagicMock(), data_item, "completion"
            )
            rd = result["metadata"]["routing_decision"]
            assert "nexus_metadata" in rd, f"nexus_metadata missing for model={model}"
            assert "decision_source" in rd, f"decision_source missing for model={model}"
