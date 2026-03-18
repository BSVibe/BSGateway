from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

import structlog

from bsgateway.rules.conditions import evaluate_condition
from bsgateway.rules.models import (
    EvaluationContext,
    RoutingRule,
    RuleMatch,
    TenantConfig,
)

logger = structlog.get_logger(__name__)


@runtime_checkable
class IntentClassifierProtocol(Protocol):
    """Protocol for intent classifiers used by the rule engine."""

    async def classify(self, text: str) -> str | None: ...


class RuleEngine:
    """Priority-based first-match rule engine."""

    async def evaluate(
        self,
        data: dict,
        tenant_config: TenantConfig,
        intent_classifier: IntentClassifierProtocol | None = None,
    ) -> RuleMatch | None:
        """Evaluate rules against request data.

        Returns the first matching rule, or the default rule,
        or None if no rules exist.
        """
        if not tenant_config.rules:
            return None

        ctx = EvaluationContext.from_request(data)

        # Lazy intent classification: only if any rule needs it
        if intent_classifier and self._needs_intent(tenant_config.rules):
            ctx.classified_intent = await self._classify_intent(
                intent_classifier, ctx,
            )

        trace: list[dict] = []
        default_rule: RoutingRule | None = None

        for rule in sorted(tenant_config.rules, key=lambda r: r.priority):
            if not rule.is_active:
                continue

            if rule.is_default:
                default_rule = rule
                continue

            matched = self._match_rule(rule, ctx, trace)
            if matched:
                return RuleMatch(
                    rule=rule,
                    target_model=rule.target_model,
                    trace=trace,
                )

        # No rule matched — use default
        if default_rule:
            return RuleMatch(
                rule=default_rule,
                target_model=default_rule.target_model,
                trace=trace,
            )

        return None

    def _match_rule(
        self,
        rule: RoutingRule,
        ctx: EvaluationContext,
        trace: list[dict],
    ) -> bool:
        """Check if all conditions of a rule match (AND logic)."""
        for cond in rule.conditions:
            if not evaluate_condition(cond, ctx):
                trace.append({
                    "rule": rule.name,
                    "priority": rule.priority,
                    "matched": False,
                    "failed_condition": {
                        "type": cond.condition_type,
                        "field": cond.field,
                        "operator": cond.operator,
                    },
                })
                return False

        trace.append({
            "rule": rule.name,
            "priority": rule.priority,
            "matched": True,
        })
        return True

    @staticmethod
    def _needs_intent(rules: list[RoutingRule]) -> bool:
        for rule in rules:
            if not rule.is_active:
                continue
            for cond in rule.conditions:
                if cond.condition_type == "intent":
                    return True
        return False

    async def evaluate_batch(
        self,
        requests: list[dict],
        tenant_config: TenantConfig,
        intent_classifier: IntentClassifierProtocol | None = None,
    ) -> list[RuleMatch | None]:
        """Evaluate rules against multiple requests in parallel.

        This method batches intent classification to reduce latency
        when processing multiple requests simultaneously.
        """
        if not tenant_config.rules:
            return [None] * len(requests)

        # Pre-classify all intents in parallel if needed
        intent_cache: dict[str, str | None] = {}
        if intent_classifier and self._needs_intent(tenant_config.rules):
            # Extract user texts and classify in parallel
            texts_to_classify = []
            text_indices = []
            for i, req in enumerate(requests):
                user_text = req.get("messages", [{}])[-1].get("content", "")
                if user_text not in intent_cache:
                    texts_to_classify.append(user_text)
                    text_indices.append((i, user_text))

            # Batch classify
            if texts_to_classify:
                tasks = [intent_classifier.classify(text) for text in texts_to_classify]
                results = await asyncio.gather(*tasks)
                for (_, text), result in zip(text_indices, results):
                    intent_cache[text] = result

        # Evaluate all requests in parallel
        tasks = [
            self._evaluate_single(req, tenant_config, intent_cache)
            for req in requests
        ]
        return await asyncio.gather(*tasks)

    async def _evaluate_single(
        self,
        data: dict,
        tenant_config: TenantConfig,
        intent_cache: dict[str, str | None],
    ) -> RuleMatch | None:
        """Evaluate a single request against rules."""
        if not tenant_config.rules:
            return None

        ctx = EvaluationContext.from_request(data)

        # Use cached intent if available
        user_text = data.get("messages", [{}])[-1].get("content", "")
        if user_text in intent_cache:
            ctx.classified_intent = intent_cache[user_text]

        trace: list[dict] = []
        default_rule: RoutingRule | None = None

        for rule in sorted(tenant_config.rules, key=lambda r: r.priority):
            if not rule.is_active:
                continue

            if rule.is_default:
                default_rule = rule
                continue

            matched = self._match_rule(rule, ctx, trace)
            if matched:
                return RuleMatch(
                    rule=rule,
                    target_model=rule.target_model,
                    trace=trace,
                )

        # No rule matched — use default
        if default_rule:
            return RuleMatch(
                rule=default_rule,
                target_model=default_rule.target_model,
                trace=trace,
            )

        return None

    @staticmethod
    async def _classify_intent(
        classifier: IntentClassifierProtocol, ctx: EvaluationContext,
    ) -> str | None:
        return await classifier.classify(ctx.user_text)
