from __future__ import annotations

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

    @staticmethod
    async def _classify_intent(
        classifier: IntentClassifierProtocol, ctx: EvaluationContext,
    ) -> str | None:
        return await classifier.classify(ctx.user_text)
