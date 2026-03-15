"""Tests for Phase 3 advanced conditions: budget, time, language.

TDD: Tests written FIRST.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bsgateway.rules.budget import BudgetTracker
from bsgateway.rules.conditions import evaluate_condition
from bsgateway.rules.models import EvaluationContext, RuleCondition


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
        "classified_intent": None,
        "detected_language": None,
        "hour_of_day": None,
        "day_of_week": None,
        "daily_cost": None,
        "monthly_cost": None,
        "request_count_hourly": None,
    }
    defaults.update(overrides)
    return EvaluationContext(**defaults)


class TestLanguageCondition:
    def test_language_eq(self):
        ctx = _make_ctx(detected_language="ko")
        cond = RuleCondition(
            condition_type="language",
            field="detected_language",
            operator="eq",
            value="ko",
        )
        assert evaluate_condition(cond, ctx) is True

    def test_language_in(self):
        ctx = _make_ctx(detected_language="ko")
        cond = RuleCondition(
            condition_type="language",
            field="detected_language",
            operator="in",
            value=["en", "ko", "ja"],
        )
        assert evaluate_condition(cond, ctx) is True

    def test_language_miss(self):
        ctx = _make_ctx(detected_language="fr")
        cond = RuleCondition(
            condition_type="language",
            field="detected_language",
            operator="in",
            value=["en", "ko"],
        )
        assert evaluate_condition(cond, ctx) is False

    def test_language_none(self):
        ctx = _make_ctx(detected_language=None)
        cond = RuleCondition(
            condition_type="language",
            field="detected_language",
            operator="eq",
            value="ko",
        )
        assert evaluate_condition(cond, ctx) is False


class TestLanguageDetection:
    """Test heuristic language detection edge cases."""

    def test_arabic_returns_none(self):
        from bsgateway.rules.models import _detect_language

        assert _detect_language("مرحبا بالعالم") is None

    def test_cyrillic_returns_none(self):
        from bsgateway.rules.models import _detect_language

        assert _detect_language("Привет мир") is None

    def test_english_returns_en(self):
        from bsgateway.rules.models import _detect_language

        assert _detect_language("Hello world, how are you?") == "en"

    def test_korean_returns_ko(self):
        from bsgateway.rules.models import _detect_language

        assert _detect_language("안녕하세요 반갑습니다") == "ko"

    def test_empty_returns_none(self):
        from bsgateway.rules.models import _detect_language

        assert _detect_language("") is None

    def test_numbers_only_returns_none(self):
        from bsgateway.rules.models import _detect_language

        assert _detect_language("12345 67890") is None


class TestTimeCondition:
    def test_hour_between(self):
        ctx = _make_ctx(hour_of_day=3)
        cond = RuleCondition(
            condition_type="time",
            field="hour_of_day",
            operator="between",
            value=[0, 6],
        )
        assert evaluate_condition(cond, ctx) is True

    def test_hour_outside_range(self):
        ctx = _make_ctx(hour_of_day=14)
        cond = RuleCondition(
            condition_type="time",
            field="hour_of_day",
            operator="between",
            value=[0, 6],
        )
        assert evaluate_condition(cond, ctx) is False

    def test_day_of_week_in(self):
        ctx = _make_ctx(day_of_week="sat")
        cond = RuleCondition(
            condition_type="time",
            field="day_of_week",
            operator="in",
            value=["sat", "sun"],
        )
        assert evaluate_condition(cond, ctx) is True

    def test_day_of_week_miss(self):
        ctx = _make_ctx(day_of_week="mon")
        cond = RuleCondition(
            condition_type="time",
            field="day_of_week",
            operator="in",
            value=["sat", "sun"],
        )
        assert evaluate_condition(cond, ctx) is False


class TestBudgetCondition:
    def test_daily_cost_lt(self):
        ctx = _make_ctx(daily_cost=5.0)
        cond = RuleCondition(
            condition_type="budget",
            field="daily_cost",
            operator="lt",
            value=10.0,
        )
        assert evaluate_condition(cond, ctx) is True

    def test_daily_cost_exceeds(self):
        ctx = _make_ctx(daily_cost=15.0)
        cond = RuleCondition(
            condition_type="budget",
            field="daily_cost",
            operator="lt",
            value=10.0,
        )
        assert evaluate_condition(cond, ctx) is False

    def test_monthly_cost_lte(self):
        ctx = _make_ctx(monthly_cost=100.0)
        cond = RuleCondition(
            condition_type="budget",
            field="monthly_cost",
            operator="lte",
            value=100.0,
        )
        assert evaluate_condition(cond, ctx) is True

    def test_request_count_hourly(self):
        ctx = _make_ctx(request_count_hourly=50)
        cond = RuleCondition(
            condition_type="budget",
            field="request_count_hourly",
            operator="lt",
            value=100,
        )
        assert evaluate_condition(cond, ctx) is True


class TestBudgetTracker:
    @pytest.fixture
    def mock_redis(self) -> AsyncMock:
        redis = AsyncMock()
        redis.incrbyfloat = AsyncMock(return_value=5.5)
        redis.get = AsyncMock(return_value=b"5.5")
        redis.expire = AsyncMock()
        return redis

    async def test_record_cost(self, mock_redis: AsyncMock):
        tracker = BudgetTracker(mock_redis)
        await tracker.record_cost("tenant-1", 0.05)
        assert mock_redis.incrbyfloat.call_count == 2  # daily + monthly

    async def test_get_daily_cost(self, mock_redis: AsyncMock):
        tracker = BudgetTracker(mock_redis)
        cost = await tracker.get_daily_cost("tenant-1")
        assert cost == 5.5

    async def test_get_daily_cost_none(self, mock_redis: AsyncMock):
        mock_redis.get.return_value = None
        tracker = BudgetTracker(mock_redis)
        cost = await tracker.get_daily_cost("tenant-1")
        assert cost == 0.0

    async def test_get_monthly_cost(self, mock_redis: AsyncMock):
        tracker = BudgetTracker(mock_redis)
        cost = await tracker.get_monthly_cost("tenant-1")
        assert cost == 5.5

    async def test_increment_request_count(self, mock_redis: AsyncMock):
        mock_redis.incr = AsyncMock(return_value=42)
        tracker = BudgetTracker(mock_redis)
        count = await tracker.increment_request_count("tenant-1")
        assert count == 42

    async def test_get_request_count(self, mock_redis: AsyncMock):
        mock_redis.get.return_value = b"42"
        tracker = BudgetTracker(mock_redis)
        count = await tracker.get_request_count_hourly("tenant-1")
        assert count == 42
