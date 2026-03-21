from __future__ import annotations

import re
from typing import Any

from bsgateway.rules.models import EvaluationContext, RuleCondition

# Pre-compiled ReDoS detection pattern (nested quantifiers)
_REDOS_PATTERN = re.compile(r"\(.+[*+]\)[*+?]|\[.+[*+]\][*+?]")

# Allowed fields for rule conditions — prevents access to internal/dunder attributes
_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "user_text",
        "system_prompt",
        "all_text",
        "estimated_tokens",
        "conversation_turns",
        "has_code_blocks",
        "has_error_trace",
        "tool_count",
        "tool_names",
        "original_model",
        "classified_intent",
        "detected_language",
        "hour_of_day",
        "day_of_week",
        "daily_cost",
        "monthly_cost",
        "request_count_hourly",
    }
)


def evaluate_condition(condition: RuleCondition, ctx: EvaluationContext) -> bool:
    """Evaluate a single condition against the evaluation context.

    Returns True if the condition matches (before negate is applied).
    """
    if condition.field not in _ALLOWED_FIELDS:
        return False
    result = _evaluate_raw(condition, ctx)
    return (not result) if condition.negate else result


def _evaluate_raw(condition: RuleCondition, ctx: EvaluationContext) -> bool:
    field_value = _get_field_value(condition.field, ctx)
    op = condition.operator
    expected = condition.value

    if op == "eq":
        return field_value == expected
    if op == "contains":
        return _str_contains(field_value, expected)
    if op == "regex":
        pattern = str(expected)
        if len(pattern) > 500:
            return False
        # Reject patterns with nested quantifiers (ReDoS risk)
        if _REDOS_PATTERN.search(pattern):
            return False
        try:
            return bool(re.search(pattern, str(field_value), re.IGNORECASE))
        except re.error:
            return False
    if op == "gt":
        return _numeric(field_value) > _numeric(expected)
    if op == "lt":
        return _numeric(field_value) < _numeric(expected)
    if op == "gte":
        return _numeric(field_value) >= _numeric(expected)
    if op == "lte":
        return _numeric(field_value) <= _numeric(expected)
    if op == "between":
        if not isinstance(expected, list) or len(expected) != 2:
            return False
        v = _numeric(field_value)
        return _numeric(expected[0]) <= v <= _numeric(expected[1])
    if op == "in":
        return _check_in(field_value, expected)
    if op == "not_in":
        return not _check_in(field_value, expected)

    return False


def _get_field_value(field: str, ctx: EvaluationContext) -> Any:
    return getattr(ctx, field, None)


def _str_contains(haystack: Any, needle: Any) -> bool:
    if haystack is None:
        return False
    return str(needle).lower() in str(haystack).lower()


def _numeric(value: Any) -> float:
    """Convert value to float for numeric comparisons.

    Returns 0.0 for None or non-numeric values. This is intentional:
    missing fields (None) are treated as zero so that comparisons like
    ``daily_cost < 10`` still work when the field hasn't been populated.
    """
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _check_in(field_value: Any, expected_list: Any) -> bool:
    """Check if field_value is in expected_list, or has intersection."""
    if not isinstance(expected_list, list):
        return False
    # If field is a list (e.g. tool_names), check intersection
    if isinstance(field_value, list):
        return bool(set(field_value) & set(expected_list))
    return field_value in expected_list
