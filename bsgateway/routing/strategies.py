"""Advanced routing strategies: multi-region, cost optimization, A/B testing."""

from __future__ import annotations

import random
from typing import Protocol

import structlog

from bsgateway.routing.models import ABTestConfig, CostOptimizationConfig, RegionConfig

logger = structlog.get_logger(__name__)


class RegionSelector:
    """Multi-region routing with latency-based selection."""

    def __init__(self, regions: list[RegionConfig]) -> None:
        """Initialize with region configurations.

        Regions are sorted by priority (lower = better).
        """
        self.regions = sorted(regions, key=lambda r: r.priority)

    def select_region(self, user_region: str | None = None) -> RegionConfig | None:
        """Select best region for request.

        If user_region is specified, prefer it. Otherwise select by priority/latency.
        """
        if not self.regions:
            return None

        # If user specifies preferred region, try to use it
        if user_region:
            for region in self.regions:
                if region.region == user_region:
                    logger.debug("region_selected", region=user_region, reason="user_preference")
                    return region

        # Fall back to lowest-latency region
        selected = self.regions[0]
        logger.debug("region_selected", region=selected.region, latency_ms=selected.latency_ms)
        return selected

    def get_api_base(self, region: RegionConfig, default: str) -> str:
        """Get API base URL for region, with fallback to default."""
        return region.api_base or default


class CostOptimizer:
    """Cost-optimized routing: prefer cheaper models."""

    def __init__(self, config: CostOptimizationConfig) -> None:
        self.config = config

    def calculate_cost(self, model_name: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for request in USD."""
        if not self.config.enabled:
            return 0.0

        input_cost = (input_tokens / 1000) * self.config.cost_per_1k_input
        output_cost = (output_tokens / 1000) * self.config.cost_per_1k_output
        return input_cost + output_cost

    def should_use_fallback(self, primary_cost: float, fallback_cost: float) -> bool:
        """Check if fallback model is significantly cheaper."""
        if not self.config.enabled or primary_cost == 0:
            return False

        threshold = primary_cost * self.config.fallback_cost_multiplier
        should_fallback = fallback_cost < threshold
        if should_fallback:
            logger.debug(
                "fallback_triggered_cost_optimization",
                primary_cost=primary_cost,
                fallback_cost=fallback_cost,
                threshold=threshold,
            )
        return should_fallback


class ABTester:
    """A/B testing framework with traffic split."""

    def __init__(self, tests: dict[str, list[ABTestConfig]]) -> None:
        """Initialize with test configurations per request type."""
        self.tests = tests

    def select_variant(
        self, test_id: str, user_id: str | None = None,
    ) -> ABTestConfig | None:
        """Select variant for user in test.

        Uses deterministic hashing of user_id for stable assignment.
        """
        variants = self.tests.get(test_id, [])
        if not variants:
            return None

        # If no user_id, random assignment
        if not user_id:
            return self._weighted_choice(variants)

        # Deterministic assignment based on user_id hash
        hash_val = hash(user_id) % 100
        cumulative = 0
        for variant in variants:
            cumulative += variant.traffic_percentage
            if hash_val < cumulative:
                logger.debug(
                    "ab_test_variant_selected",
                    test_id=test_id,
                    variant=variant.variant_id,
                    reason="hash_assignment",
                )
                return variant

        # Fallback to first variant
        return variants[0]

    @staticmethod
    def _weighted_choice(variants: list[ABTestConfig]) -> ABTestConfig:
        """Randomly select variant weighted by traffic percentage."""
        total = sum(v.traffic_percentage for v in variants)
        rand = random.uniform(0, total)
        cumulative = 0
        for variant in variants:
            cumulative += variant.traffic_percentage
            if rand < cumulative:
                return variant
        return variants[-1]
