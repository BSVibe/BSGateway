"""Tests for condition evaluation edge cases: ReDoS, between safety, validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bsgateway.rules.conditions import evaluate_condition
from bsgateway.rules.models import EvaluationContext, RuleCondition
from bsgateway.rules.schemas import ConditionSchema


def _make_ctx(**overrides) -> EvaluationContext:
    defaults = {
        "user_text": "hello",
        "system_prompt": "",
        "all_text": "hello",
        "estimated_tokens": 100,
        "conversation_turns": 1,
        "has_code_blocks": False,
        "has_error_trace": False,
        "tool_count": 0,
        "tool_names": [],
        "original_model": "auto",
    }
    defaults.update(overrides)
    return EvaluationContext(**defaults)


class TestRegexSafety:
    def test_valid_regex(self):
        ctx = _make_ctx(user_text="hello world")
        cond = RuleCondition(
            condition_type="text_pattern",
            field="user_text",
            operator="regex",
            value=r"hello\s+\w+",
        )
        assert evaluate_condition(cond, ctx) is True

    def test_invalid_regex_returns_false(self):
        ctx = _make_ctx(user_text="hello")
        cond = RuleCondition(
            condition_type="text_pattern",
            field="user_text",
            operator="regex",
            value="[invalid(",
        )
        assert evaluate_condition(cond, ctx) is False

    def test_long_regex_rejected(self):
        ctx = _make_ctx(user_text="hello")
        cond = RuleCondition(
            condition_type="text_pattern",
            field="user_text",
            operator="regex",
            value="a" * 501,
        )
        assert evaluate_condition(cond, ctx) is False

    def test_max_length_regex_accepted(self):
        ctx = _make_ctx(user_text="a" * 500)
        cond = RuleCondition(
            condition_type="text_pattern",
            field="user_text",
            operator="regex",
            value="a" * 500,
        )
        assert evaluate_condition(cond, ctx) is True


class TestBetweenSafety:
    def test_between_valid(self):
        ctx = _make_ctx(estimated_tokens=50)
        cond = RuleCondition(
            condition_type="token_count",
            field="estimated_tokens",
            operator="between",
            value=[10, 100],
        )
        assert evaluate_condition(cond, ctx) is True

    def test_between_not_a_list(self):
        ctx = _make_ctx(estimated_tokens=50)
        cond = RuleCondition(
            condition_type="token_count",
            field="estimated_tokens",
            operator="between",
            value="not-a-list",
        )
        assert evaluate_condition(cond, ctx) is False

    def test_between_wrong_length(self):
        ctx = _make_ctx(estimated_tokens=50)
        cond = RuleCondition(
            condition_type="token_count",
            field="estimated_tokens",
            operator="between",
            value=[10],
        )
        assert evaluate_condition(cond, ctx) is False

    def test_between_three_elements(self):
        ctx = _make_ctx(estimated_tokens=50)
        cond = RuleCondition(
            condition_type="token_count",
            field="estimated_tokens",
            operator="between",
            value=[10, 100, 200],
        )
        assert evaluate_condition(cond, ctx) is False


class TestConditionSchemaValidation:
    def test_valid_string_value(self):
        schema = ConditionSchema(
            condition_type="text_pattern",
            field="user_text",
            operator="contains",
            value="hello",
        )
        assert schema.value == "hello"

    def test_valid_numeric_value(self):
        schema = ConditionSchema(
            condition_type="token_count",
            field="estimated_tokens",
            operator="gt",
            value=100,
        )
        assert schema.value == 100

    def test_valid_list_value(self):
        schema = ConditionSchema(
            condition_type="language",
            field="detected_language",
            operator="in",
            value=["en", "ko"],
        )
        assert schema.value == ["en", "ko"]

    def test_string_too_long(self):
        with pytest.raises(ValidationError, match="too long"):
            ConditionSchema(
                condition_type="text_pattern",
                field="user_text",
                operator="regex",
                value="x" * 1001,
            )

    def test_list_too_long(self):
        with pytest.raises(ValidationError, match="too long"):
            ConditionSchema(
                condition_type="language",
                field="detected_language",
                operator="in",
                value=list(range(101)),
            )

    def test_bool_value(self):
        schema = ConditionSchema(
            condition_type="message",
            field="has_code_blocks",
            operator="eq",
            value=True,
        )
        assert schema.value is True

    def test_none_value(self):
        schema = ConditionSchema(
            condition_type="intent",
            field="classified_intent",
            operator="eq",
            value=None,
        )
        assert schema.value is None

    def test_invalid_operator_rejected(self):
        with pytest.raises(ValidationError):
            ConditionSchema(
                condition_type="text_pattern",
                field="user_text",
                operator="invalid_op",
                value="hello",
            )

    def test_invalid_condition_type_rejected(self):
        with pytest.raises(ValidationError):
            ConditionSchema(
                condition_type="nonexistent_type",
                field="user_text",
                operator="eq",
                value="hello",
            )

    def test_between_requires_two_element_list(self):
        with pytest.raises(ValidationError, match="2-element list"):
            ConditionSchema(
                condition_type="token_count",
                field="estimated_tokens",
                operator="between",
                value="not-a-list",
            )

    def test_between_with_valid_list(self):
        schema = ConditionSchema(
            condition_type="token_count",
            field="estimated_tokens",
            operator="between",
            value=[10, 100],
        )
        assert schema.value == [10, 100]


class TestReDoSProtection:
    def test_nested_quantifier_rejected(self):
        ctx = _make_ctx(user_text="aaaaaaaab")
        cond = RuleCondition(
            condition_type="text_pattern",
            field="user_text",
            operator="regex",
            value="(a+)+b",
        )
        assert evaluate_condition(cond, ctx) is False


class TestFieldWhitelist:
    """Schema-level whitelist enforcement for condition fields (audit H4)."""

    def test_unknown_field_rejected_at_schema(self):
        """Arbitrary field names are rejected at the schema layer."""
        with pytest.raises(ValidationError, match="field"):
            ConditionSchema(
                condition_type="text_pattern",
                field="__class__",
                operator="eq",
                value="x",
            )

    def test_dunder_field_rejected_at_schema(self):
        """Dunder attribute names cannot be smuggled through field=."""
        with pytest.raises(ValidationError, match="field"):
            ConditionSchema(
                condition_type="text_pattern",
                field="__dict__",
                operator="contains",
                value="x",
            )

    def test_typo_field_rejected_at_schema(self):
        """Typos are caught at write-time, not silently never-matching."""
        with pytest.raises(ValidationError, match="field"):
            ConditionSchema(
                condition_type="token_count",
                field="estimated_token",  # missing trailing s
                operator="gt",
                value=100,
            )

    def test_all_allowed_fields_pass_schema(self):
        """Every field returned by the runtime whitelist must round-trip."""
        from bsgateway.rules.conditions import ALLOWED_FIELDS

        for f in ALLOWED_FIELDS:
            schema = ConditionSchema(
                condition_type="text_pattern",
                field=f,
                operator="eq",
                value="x",
            )
            assert schema.field == f
