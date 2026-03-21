"""Tests for the rule engine: models, conditions, and evaluation.

TDD: These tests are written FIRST, before any production code.
"""

from __future__ import annotations

from bsgateway.rules.models import (
    EvaluationContext,
    RoutingRule,
    RuleCondition,
    TenantConfig,
    TenantModel,
)

# ---------------------------------------------------------------------------
# EvaluationContext construction
# ---------------------------------------------------------------------------


class TestEvaluationContext:
    def test_build_from_request_data(self):
        data = {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Translate this to Korean: hello world"},
                {"role": "assistant", "content": "안녕하세요 세계"},
                {"role": "user", "content": "Now translate to Japanese"},
            ],
            "model": "auto",
            "tools": [{"type": "function", "function": {"name": "search"}}],
        }
        ctx = EvaluationContext.from_request(data)

        assert ctx.user_text == "Translate this to Korean: hello world Now translate to Japanese"
        assert ctx.system_prompt == "You are helpful."
        assert ctx.all_text is not None
        assert ctx.estimated_tokens > 0
        assert ctx.conversation_turns == 2
        assert ctx.tool_count == 1
        assert ctx.original_model == "auto"
        assert ctx.has_code_blocks is False

    def test_build_detects_code_blocks(self):
        data = {
            "messages": [
                {"role": "user", "content": "Review this:\n```python\nprint('hi')\n```"},
            ],
        }
        ctx = EvaluationContext.from_request(data)
        assert ctx.has_code_blocks is True

    def test_build_with_empty_messages(self):
        ctx = EvaluationContext.from_request({"messages": []})
        assert ctx.user_text == ""
        assert ctx.estimated_tokens == 0
        assert ctx.conversation_turns == 0


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------


class TestConditions:
    """Test individual condition evaluators."""

    def _make_ctx(self, **overrides) -> EvaluationContext:
        defaults = {
            "user_text": "hello world",
            "system_prompt": "",
            "all_text": "hello world",
            "estimated_tokens": 50,
            "conversation_turns": 1,
            "has_code_blocks": False,
            "has_error_trace": False,
            "tool_count": 0,
            "tool_names": [],
            "original_model": "auto",
            "classified_intent": None,
        }
        defaults.update(overrides)
        return EvaluationContext(**defaults)

    # -- text_pattern --

    def test_text_pattern_contains(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="text_pattern",
            field="user_text",
            operator="contains",
            value="hello",
        )
        ctx = self._make_ctx(user_text="hello world")
        assert evaluate_condition(cond, ctx) is True

    def test_text_pattern_contains_miss(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="text_pattern",
            field="user_text",
            operator="contains",
            value="goodbye",
        )
        ctx = self._make_ctx(user_text="hello world")
        assert evaluate_condition(cond, ctx) is False

    def test_text_pattern_regex(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="text_pattern",
            field="user_text",
            operator="regex",
            value=r"^translate.*korean",
        )
        ctx = self._make_ctx(user_text="Translate this to Korean")
        assert evaluate_condition(cond, ctx) is True

    def test_text_pattern_system_prompt(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="text_pattern",
            field="system_prompt",
            operator="contains",
            value="code reviewer",
        )
        ctx = self._make_ctx(system_prompt="You are a code reviewer")
        assert evaluate_condition(cond, ctx) is True

    # -- token_count --

    def test_token_count_gt(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="token_count",
            field="estimated_tokens",
            operator="gt",
            value=100,
        )
        ctx = self._make_ctx(estimated_tokens=200)
        assert evaluate_condition(cond, ctx) is True

    def test_token_count_lt(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="token_count",
            field="estimated_tokens",
            operator="lt",
            value=100,
        )
        ctx = self._make_ctx(estimated_tokens=50)
        assert evaluate_condition(cond, ctx) is True

    def test_token_count_between(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="token_count",
            field="estimated_tokens",
            operator="between",
            value=[100, 500],
        )
        ctx = self._make_ctx(estimated_tokens=200)
        assert evaluate_condition(cond, ctx) is True
        ctx2 = self._make_ctx(estimated_tokens=50)
        assert evaluate_condition(cond, ctx2) is False

    # -- message --

    def test_message_turns_gt(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="message",
            field="conversation_turns",
            operator="gt",
            value=3,
        )
        ctx = self._make_ctx(conversation_turns=5)
        assert evaluate_condition(cond, ctx) is True

    def test_message_has_code_blocks(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="message",
            field="has_code_blocks",
            operator="eq",
            value=True,
        )
        ctx = self._make_ctx(has_code_blocks=True)
        assert evaluate_condition(cond, ctx) is True

    # -- tool --

    def test_tool_count(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="tool",
            field="tool_count",
            operator="gt",
            value=0,
        )
        ctx = self._make_ctx(tool_count=3)
        assert evaluate_condition(cond, ctx) is True

    def test_tool_names_in(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="tool",
            field="tool_names",
            operator="in",
            value=["browser", "code_exec"],
        )
        ctx = self._make_ctx(tool_names=["browser", "search"])
        assert evaluate_condition(cond, ctx) is True

    # -- model_requested --

    def test_model_requested_eq(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="model_requested",
            field="original_model",
            operator="eq",
            value="auto",
        )
        ctx = self._make_ctx(original_model="auto")
        assert evaluate_condition(cond, ctx) is True

    def test_model_requested_regex(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="model_requested",
            field="original_model",
            operator="regex",
            value=r"claude-.*",
        )
        ctx = self._make_ctx(original_model="claude-sonnet")
        assert evaluate_condition(cond, ctx) is True

    # -- intent --

    def test_intent_eq(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="intent",
            field="classified_intent",
            operator="eq",
            value="code_generation",
        )
        ctx = self._make_ctx(classified_intent="code_generation")
        assert evaluate_condition(cond, ctx) is True

    def test_intent_in(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="intent",
            field="classified_intent",
            operator="in",
            value=["translation", "summarization"],
        )
        ctx = self._make_ctx(classified_intent="translation")
        assert evaluate_condition(cond, ctx) is True

    # -- negate --

    def test_negate_inverts_result(self):
        from bsgateway.rules.conditions import evaluate_condition

        cond = RuleCondition(
            condition_type="text_pattern",
            field="user_text",
            operator="contains",
            value="hello",
            negate=True,
        )
        ctx = self._make_ctx(user_text="hello world")
        assert evaluate_condition(cond, ctx) is False


# ---------------------------------------------------------------------------
# Rule Engine evaluation
# ---------------------------------------------------------------------------


class TestRuleEngine:
    """Test the full rule evaluation pipeline."""

    def _make_tenant_config(
        self,
        rules: list[RoutingRule],
    ) -> TenantConfig:
        return TenantConfig(
            tenant_id="test-tenant",
            slug="test",
            models={
                "gpt4": TenantModel(
                    model_name="gpt4",
                    provider="openai",
                    litellm_model="openai/gpt-4o",
                )
            },
            rules=rules,
            settings={},
        )

    async def test_first_match_wins(self):
        from bsgateway.rules.engine import RuleEngine

        rules = [
            RoutingRule(
                id="rule-1",
                tenant_id="t",
                name="high-token",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="premium",
                conditions=[
                    RuleCondition(
                        condition_type="token_count",
                        field="estimated_tokens",
                        operator="gt",
                        value=1000,
                    )
                ],
            ),
            RoutingRule(
                id="rule-2",
                tenant_id="t",
                name="catch-all",
                priority=2,
                is_active=True,
                is_default=False,
                target_model="economy",
                conditions=[
                    RuleCondition(
                        condition_type="token_count",
                        field="estimated_tokens",
                        operator="gt",
                        value=0,
                    )
                ],
            ),
        ]
        config = self._make_tenant_config(rules)
        engine = RuleEngine()

        data = {
            "messages": [{"role": "user", "content": "x " * 1000}],
            "model": "auto",
        }
        result = await engine.evaluate(data, config)
        assert result is not None
        assert result.rule.name == "high-token"
        assert result.target_model == "premium"

    async def test_default_rule_used_when_no_match(self):
        from bsgateway.rules.engine import RuleEngine

        rules = [
            RoutingRule(
                id="rule-1",
                tenant_id="t",
                name="code-only",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="premium",
                conditions=[
                    RuleCondition(
                        condition_type="text_pattern",
                        field="user_text",
                        operator="contains",
                        value="```",
                    )
                ],
            ),
            RoutingRule(
                id="rule-default",
                tenant_id="t",
                name="default",
                priority=99,
                is_active=True,
                is_default=True,
                target_model="economy",
                conditions=[],
            ),
        ]
        config = self._make_tenant_config(rules)
        engine = RuleEngine()

        data = {
            "messages": [{"role": "user", "content": "just a question"}],
            "model": "auto",
        }
        result = await engine.evaluate(data, config)
        assert result is not None
        assert result.rule.name == "default"
        assert result.target_model == "economy"

    async def test_inactive_rules_skipped(self):
        from bsgateway.rules.engine import RuleEngine

        rules = [
            RoutingRule(
                id="rule-1",
                tenant_id="t",
                name="disabled",
                priority=1,
                is_active=False,
                is_default=False,
                target_model="premium",
                conditions=[],
            ),
            RoutingRule(
                id="rule-2",
                tenant_id="t",
                name="active",
                priority=2,
                is_active=True,
                is_default=True,
                target_model="economy",
                conditions=[],
            ),
        ]
        config = self._make_tenant_config(rules)
        engine = RuleEngine()

        result = await engine.evaluate(
            {"messages": [{"role": "user", "content": "hi"}], "model": "auto"},
            config,
        )
        assert result is not None
        assert result.rule.name == "active"

    async def test_and_logic_all_conditions_must_match(self):
        from bsgateway.rules.engine import RuleEngine

        rules = [
            RoutingRule(
                id="rule-1",
                tenant_id="t",
                name="complex-code",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="premium",
                conditions=[
                    RuleCondition(
                        condition_type="message",
                        field="has_code_blocks",
                        operator="eq",
                        value=True,
                    ),
                    RuleCondition(
                        condition_type="token_count",
                        field="estimated_tokens",
                        operator="gt",
                        value=500,
                    ),
                ],
            ),
            RoutingRule(
                id="rule-default",
                tenant_id="t",
                name="default",
                priority=99,
                is_active=True,
                is_default=True,
                target_model="economy",
                conditions=[],
            ),
        ]
        config = self._make_tenant_config(rules)
        engine = RuleEngine()

        # Has code but short — should NOT match rule-1
        data = {
            "messages": [
                {"role": "user", "content": "fix:\n```py\nprint(1)\n```"},
            ],
            "model": "auto",
        }
        result = await engine.evaluate(data, config)
        assert result.rule.name == "default"

    async def test_no_rules_returns_none(self):
        from bsgateway.rules.engine import RuleEngine

        config = self._make_tenant_config([])
        engine = RuleEngine()

        result = await engine.evaluate(
            {"messages": [{"role": "user", "content": "hi"}], "model": "auto"},
            config,
        )
        assert result is None

    async def test_evaluation_trace_returned(self):
        """Engine should return a trace of which rules were evaluated."""
        from bsgateway.rules.engine import RuleEngine

        rules = [
            RoutingRule(
                id="rule-1",
                tenant_id="t",
                name="code-rule",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="premium",
                conditions=[
                    RuleCondition(
                        condition_type="text_pattern",
                        field="user_text",
                        operator="contains",
                        value="```",
                    )
                ],
            ),
            RoutingRule(
                id="rule-default",
                tenant_id="t",
                name="default",
                priority=99,
                is_active=True,
                is_default=True,
                target_model="economy",
                conditions=[],
            ),
        ]
        config = self._make_tenant_config(rules)
        engine = RuleEngine()

        result = await engine.evaluate(
            {"messages": [{"role": "user", "content": "hello"}], "model": "auto"},
            config,
        )
        assert result is not None
        assert result.trace is not None
        assert len(result.trace) >= 1
        # First trace entry should show code-rule didn't match
        assert result.trace[0]["rule"] == "code-rule"
        assert result.trace[0]["matched"] is False


# ---------------------------------------------------------------------------
# Batch evaluation
# ---------------------------------------------------------------------------


class TestEvaluateBatch:
    """Tests for RuleEngine.evaluate_batch and related helpers."""

    def _make_tenant_config(self, rules: list[RoutingRule]) -> TenantConfig:
        return TenantConfig(
            tenant_id="test-tenant",
            slug="test",
            models={
                "gpt4": TenantModel(
                    model_name="gpt4",
                    provider="openai",
                    litellm_model="openai/gpt-4o",
                )
            },
            rules=rules,
            settings={},
        )

    async def test_batch_no_rules_returns_all_none(self):
        from bsgateway.rules.engine import RuleEngine

        config = self._make_tenant_config([])
        engine = RuleEngine()
        requests = [
            {"messages": [{"role": "user", "content": "hi"}], "model": "auto"},
            {"messages": [{"role": "user", "content": "hello"}], "model": "auto"},
        ]
        results = await engine.evaluate_batch(requests, config)
        assert results == [None, None]

    async def test_batch_evaluates_multiple_requests(self):
        from bsgateway.rules.engine import RuleEngine

        rules = [
            RoutingRule(
                id="r1",
                tenant_id="t",
                name="long-text",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="premium",
                conditions=[
                    RuleCondition(
                        condition_type="token_count",
                        field="estimated_tokens",
                        operator="gt",
                        value=500,
                    )
                ],
            ),
            RoutingRule(
                id="r-default",
                tenant_id="t",
                name="default",
                priority=99,
                is_active=True,
                is_default=True,
                target_model="economy",
                conditions=[],
            ),
        ]
        config = self._make_tenant_config(rules)
        engine = RuleEngine()

        requests = [
            {"messages": [{"role": "user", "content": "x " * 1000}], "model": "auto"},
            {"messages": [{"role": "user", "content": "short"}], "model": "auto"},
        ]
        results = await engine.evaluate_batch(requests, config)
        assert len(results) == 2
        assert results[0] is not None
        assert results[0].target_model == "premium"
        assert results[1] is not None
        assert results[1].target_model == "economy"

    async def test_batch_with_intent_classifier(self):
        from unittest.mock import AsyncMock

        from bsgateway.rules.engine import RuleEngine

        classifier = AsyncMock()
        classifier.classify = AsyncMock(return_value="code_generation")

        rules = [
            RoutingRule(
                id="r1",
                tenant_id="t",
                name="code-intent",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="premium",
                conditions=[
                    RuleCondition(
                        condition_type="intent",
                        field="classified_intent",
                        operator="eq",
                        value="code_generation",
                    )
                ],
            ),
        ]
        config = self._make_tenant_config(rules)
        engine = RuleEngine()

        requests = [
            {"messages": [{"role": "user", "content": "write code"}], "model": "auto"},
        ]
        results = await engine.evaluate_batch(requests, config, classifier)
        assert results[0] is not None
        assert results[0].target_model == "premium"
        classifier.classify.assert_awaited()

    async def test_batch_deduplicates_intent_classification(self):
        from unittest.mock import AsyncMock

        from bsgateway.rules.engine import RuleEngine

        classifier = AsyncMock()
        classifier.classify = AsyncMock(return_value="translation")

        rules = [
            RoutingRule(
                id="r1",
                tenant_id="t",
                name="translate",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="premium",
                conditions=[
                    RuleCondition(
                        condition_type="intent",
                        field="classified_intent",
                        operator="eq",
                        value="translation",
                    )
                ],
            ),
        ]
        config = self._make_tenant_config(rules)
        engine = RuleEngine()

        # Same text in both requests — classifier should only be called once
        same_text = "translate this to Korean"
        requests = [
            {"messages": [{"role": "user", "content": same_text}], "model": "auto"},
            {"messages": [{"role": "user", "content": same_text}], "model": "auto"},
        ]
        results = await engine.evaluate_batch(requests, config, classifier)
        assert len(results) == 2
        # Both results should match via the intent
        assert results[0] is not None
        assert results[0].target_model == "premium"
        assert results[1] is not None
        assert results[1].target_model == "premium"


class TestNeedsIntent:
    """Tests for RuleEngine._needs_intent static method."""

    def test_true_when_intent_condition_present(self):
        from bsgateway.rules.engine import RuleEngine

        rules = [
            RoutingRule(
                id="r1",
                tenant_id="t",
                name="intent-rule",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="m",
                conditions=[
                    RuleCondition(
                        condition_type="intent",
                        field="classified_intent",
                        operator="eq",
                        value="code",
                    )
                ],
            ),
        ]
        assert RuleEngine._needs_intent(rules) is True

    def test_false_when_no_intent_conditions(self):
        from bsgateway.rules.engine import RuleEngine

        rules = [
            RoutingRule(
                id="r1",
                tenant_id="t",
                name="token-rule",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="m",
                conditions=[
                    RuleCondition(
                        condition_type="token_count",
                        field="estimated_tokens",
                        operator="gt",
                        value=100,
                    )
                ],
            ),
        ]
        assert RuleEngine._needs_intent(rules) is False

    def test_skips_inactive_rules(self):
        from bsgateway.rules.engine import RuleEngine

        rules = [
            RoutingRule(
                id="r1",
                tenant_id="t",
                name="inactive-intent",
                priority=1,
                is_active=False,
                is_default=False,
                target_model="m",
                conditions=[
                    RuleCondition(
                        condition_type="intent",
                        field="classified_intent",
                        operator="eq",
                        value="code",
                    )
                ],
            ),
        ]
        assert RuleEngine._needs_intent(rules) is False


class TestEvaluateSingle:
    """Tests for RuleEngine._evaluate_single."""

    def _make_tenant_config(self, rules: list[RoutingRule]) -> TenantConfig:
        return TenantConfig(
            tenant_id="t",
            slug="test",
            models={},
            rules=rules,
            settings={},
        )

    async def test_with_cached_intent(self):
        from bsgateway.rules.engine import RuleEngine

        rules = [
            RoutingRule(
                id="r1",
                tenant_id="t",
                name="intent-rule",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="premium",
                conditions=[
                    RuleCondition(
                        condition_type="intent",
                        field="classified_intent",
                        operator="eq",
                        value="code_gen",
                    )
                ],
            ),
        ]
        config = self._make_tenant_config(rules)
        engine = RuleEngine()

        data = {"messages": [{"role": "user", "content": "write code"}], "model": "auto"}
        intent_cache = {"write code": "code_gen"}

        result = await engine._evaluate_single(data, config, intent_cache)
        assert result is not None
        assert result.target_model == "premium"

    async def test_no_rules_returns_none(self):
        from bsgateway.rules.engine import RuleEngine

        config = self._make_tenant_config([])
        engine = RuleEngine()

        result = await engine._evaluate_single(
            {"messages": [{"role": "user", "content": "hi"}], "model": "auto"},
            config,
            {},
        )
        assert result is None
