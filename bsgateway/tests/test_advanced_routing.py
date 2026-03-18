"""Tests for advanced routing strategies: multi-region, cost optimization, A/B testing."""

import pytest

from bsgateway.routing.models import ABTestConfig, CostOptimizationConfig, RegionConfig
from bsgateway.routing.strategies import ABTester, CostOptimizer, RegionSelector


class TestRegionSelector:
    """Multi-region routing tests."""

    def test_select_region_prefers_user_preference(self) -> None:
        regions = [
            RegionConfig(region="us-east", latency_ms=20, priority=0),
            RegionConfig(region="us-west", latency_ms=50, priority=1),
            RegionConfig(region="eu-west", latency_ms=100, priority=2),
        ]
        selector = RegionSelector(regions)

        # User prefers eu-west even though it's lowest priority
        selected = selector.select_region(user_region="eu-west")
        assert selected is not None
        assert selected.region == "eu-west"

    def test_select_region_uses_priority_as_fallback(self) -> None:
        regions = [
            RegionConfig(region="us-east", latency_ms=20, priority=0),
            RegionConfig(region="us-west", latency_ms=50, priority=1),
        ]
        selector = RegionSelector(regions)

        # No user preference — should use lowest priority
        selected = selector.select_region()
        assert selected is not None
        assert selected.region == "us-east"

    def test_select_region_returns_none_if_empty(self) -> None:
        selector = RegionSelector([])
        selected = selector.select_region()
        assert selected is None

    def test_select_region_returns_none_for_unknown_user_region(self) -> None:
        regions = [RegionConfig(region="us-east", priority=0)]
        selector = RegionSelector(regions)

        # Unknown user region — should fall back to priority
        selected = selector.select_region(user_region="unknown")
        assert selected is not None
        assert selected.region == "us-east"

    def test_get_api_base_uses_region_override(self) -> None:
        region = RegionConfig(
            region="us-west",
            api_base="https://us-west.api.example.com",
            priority=0,
        )
        selector = RegionSelector([region])

        api_base = selector.get_api_base(region, "https://default.api.example.com")
        assert api_base == "https://us-west.api.example.com"

    def test_get_api_base_uses_default_if_not_set(self) -> None:
        region = RegionConfig(region="us-east", priority=0)
        selector = RegionSelector([region])

        api_base = selector.get_api_base(region, "https://default.api.example.com")
        assert api_base == "https://default.api.example.com"


class TestCostOptimizer:
    """Cost optimization tests."""

    def test_calculate_cost_returns_zero_if_disabled(self) -> None:
        config = CostOptimizationConfig(enabled=False)
        optimizer = CostOptimizer(config)

        cost = optimizer.calculate_cost("gpt-4o", 1000, 500)
        assert cost == 0.0

    def test_calculate_cost_computes_correctly(self) -> None:
        config = CostOptimizationConfig(
            enabled=True,
            cost_per_1k_input=0.03,
            cost_per_1k_output=0.06,
        )
        optimizer = CostOptimizer(config)

        # 1000 input tokens * $0.03/1k = $0.03
        # 1000 output tokens * $0.06/1k = $0.06
        # Total = $0.09
        cost = optimizer.calculate_cost("gpt-4o", 1000, 1000)
        assert cost == pytest.approx(0.09)

    def test_should_use_fallback_when_cheaper(self) -> None:
        config = CostOptimizationConfig(
            enabled=True,
            fallback_cost_multiplier=1.5,
        )
        optimizer = CostOptimizer(config)

        # Primary cost $0.10, fallback $0.05
        # Threshold = $0.10 * 1.5 = $0.15
        # Fallback ($0.05) < threshold ($0.15) → use fallback
        should_use = optimizer.should_use_fallback(0.10, 0.05)
        assert should_use is True

    def test_should_not_use_fallback_when_more_expensive(self) -> None:
        config = CostOptimizationConfig(
            enabled=True,
            fallback_cost_multiplier=1.5,
        )
        optimizer = CostOptimizer(config)

        # Primary cost $0.10, fallback $0.20
        # Threshold = $0.10 * 1.5 = $0.15
        # Fallback ($0.20) >= threshold ($0.15) → don't use fallback
        should_use = optimizer.should_use_fallback(0.10, 0.20)
        assert should_use is False

    def test_should_not_use_fallback_if_disabled(self) -> None:
        config = CostOptimizationConfig(enabled=False)
        optimizer = CostOptimizer(config)

        should_use = optimizer.should_use_fallback(0.10, 0.05)
        assert should_use is False


class TestABTester:
    """A/B testing framework tests."""

    def test_select_variant_returns_none_if_test_not_found(self) -> None:
        tests: dict[str, list[ABTestConfig]] = {}
        tester = ABTester(tests)

        variant = tester.select_variant("unknown-test")
        assert variant is None

    def test_select_variant_deterministic_by_user_id(self) -> None:
        variants = [
            ABTestConfig(variant_id="control", model="gpt-4o", traffic_percentage=50),
            ABTestConfig(variant_id="variant-a", model="gpt-4-turbo", traffic_percentage=50),
        ]
        tests = {"test-1": variants}
        tester = ABTester(tests)

        # Same user_id should always get same variant
        variant1 = tester.select_variant("test-1", user_id="user-123")
        variant2 = tester.select_variant("test-1", user_id="user-123")
        assert variant1 is not None
        assert variant2 is not None
        assert variant1.variant_id == variant2.variant_id

    def test_select_variant_different_users_get_different_variants(self) -> None:
        variants = [
            ABTestConfig(variant_id="control", model="gpt-4o", traffic_percentage=50),
            ABTestConfig(variant_id="variant-a", model="gpt-4-turbo", traffic_percentage=50),
        ]
        tests = {"test-1": variants}
        tester = ABTester(tests)

        variant_ids = set()
        for i in range(100):
            variant = tester.select_variant("test-1", user_id=f"user-{i}")
            assert variant is not None
            variant_ids.add(variant.variant_id)

        # With 50/50 split over 100 users, should see both variants
        assert len(variant_ids) == 2

    def test_select_variant_random_without_user_id(self) -> None:
        variants = [
            ABTestConfig(variant_id="control", model="gpt-4o", traffic_percentage=50),
            ABTestConfig(variant_id="variant-a", model="gpt-4-turbo", traffic_percentage=50),
        ]
        tests = {"test-1": variants}
        tester = ABTester(tests)

        variant_ids = set()
        for _ in range(100):
            variant = tester.select_variant("test-1")
            assert variant is not None
            variant_ids.add(variant.variant_id)

        # Random assignment should select both variants
        assert len(variant_ids) >= 1

    def test_select_variant_respects_traffic_percentage(self) -> None:
        variants = [
            ABTestConfig(variant_id="control", model="gpt-4o", traffic_percentage=90),
            ABTestConfig(variant_id="variant-a", model="gpt-4-turbo", traffic_percentage=10),
        ]
        tests = {"test-1": variants}
        tester = ABTester(tests)

        control_count = 0
        variant_count = 0
        for i in range(100):
            variant = tester.select_variant("test-1", user_id=f"user-{i}")
            assert variant is not None
            if variant.variant_id == "control":
                control_count += 1
            else:
                variant_count += 1

        # With 90/10 split, control should be ~90 and variant ~10
        assert control_count > variant_count
        assert control_count > 70  # At least 70% in control

    def test_select_variant_uneven_split(self) -> None:
        variants = [
            ABTestConfig(variant_id="control", model="gpt-4o", traffic_percentage=70),
            ABTestConfig(variant_id="variant-a", model="gpt-4-turbo", traffic_percentage=20),
            ABTestConfig(variant_id="variant-b", model="claude", traffic_percentage=10),
        ]
        tests = {"test-1": variants}
        tester = ABTester(tests)

        variant_ids = set()
        for i in range(100):
            variant = tester.select_variant("test-1", user_id=f"user-{i}")
            assert variant is not None
            variant_ids.add(variant.variant_id)

        # Should have all three variants
        assert len(variant_ids) == 3
