from __future__ import annotations

import pytest

from bsgateway.routing.classifiers.static import StaticClassifier
from bsgateway.routing.models import ClassifierConfig, ClassifierWeights, TierConfig


@pytest.fixture
def tiers() -> list[TierConfig]:
    return [
        TierConfig(name="simple", score_range=(0, 30), model="local/llama3"),
        TierConfig(name="medium", score_range=(31, 65), model="gpt-4o-mini"),
        TierConfig(name="complex", score_range=(66, 100), model="claude-opus"),
    ]


@pytest.fixture
def config() -> ClassifierConfig:
    return ClassifierConfig(
        weights=ClassifierWeights(),
        token_thresholds={"low": 500, "medium": 2000, "high": 8000},
        complex_keywords=[
            "architect", "design system", "trade-off", "security audit",
            "refactor", "optimize", "deep analysis", "implement", "function",
            "build", "create",
        ],
        simple_keywords=[
            "hello", "thanks", "convert", "format", "translate",
            "what is", "how to",
        ],
    )


@pytest.fixture
def classifier(config: ClassifierConfig, tiers: list[TierConfig]) -> StaticClassifier:
    return StaticClassifier(config, tiers)


class TestSimpleRequests:
    @pytest.mark.asyncio
    async def test_greeting_scores_low(self, classifier: StaticClassifier) -> None:
        data = {"messages": [{"role": "user", "content": "hello, how are you?"}]}
        result = await classifier.classify(data)
        assert result.score <= 30, f"Greeting should be simple, got {result.score}"
        assert result.tier == "simple"
        assert result.strategy == "static"

    @pytest.mark.asyncio
    async def test_simple_question_scores_low(self, classifier: StaticClassifier) -> None:
        data = {"messages": [{"role": "user", "content": "what is Python?"}]}
        result = await classifier.classify(data)
        assert result.score <= 30, f"Simple question should be simple, got {result.score}"

    @pytest.mark.asyncio
    async def test_format_request_scores_low(self, classifier: StaticClassifier) -> None:
        data = {"messages": [{"role": "user", "content": "convert this to JSON format"}]}
        result = await classifier.classify(data)
        assert result.score <= 30, f"Format conversion should be simple, got {result.score}"


class TestComplexRequests:
    @pytest.mark.asyncio
    async def test_architecture_design_scores_high(self, classifier: StaticClassifier) -> None:
        data = {
            "messages": [
                {"role": "user", "content": (
                    "Design a microservices architecture for an e-commerce platform. "
                    "Consider trade-off between consistency and availability. "
                    "Include security audit recommendations."
                )}
            ],
        }
        result = await classifier.classify(data)
        assert result.score >= 50, f"Architecture design should be complex, got {result.score}"

    @pytest.mark.asyncio
    async def test_code_review_with_large_codeblock_scores_high(
        self, classifier: StaticClassifier
    ) -> None:
        code_block = "```python\n" + "def foo():\n    pass\n" * 20 + "```"
        data = {
            "messages": [
                {"role": "user", "content": f"refactor this code:\n{code_block}"},
            ],
        }
        result = await classifier.classify(data)
        assert result.score >= 50, f"Code review with large block should be complex, got {result.score}"

    @pytest.mark.asyncio
    async def test_tool_usage_boosts_score(self, classifier: StaticClassifier) -> None:
        data = {
            "messages": [{"role": "user", "content": "help me with this task"}],
            "tools": [
                {"type": "function", "function": {"name": "read_file"}},
                {"type": "function", "function": {"name": "write_file"}},
                {"type": "function", "function": {"name": "run_command"}},
            ],
        }
        result = await classifier.classify(data)
        result_no_tools = await classifier.classify(
            {"messages": [{"role": "user", "content": "help me with this task"}]}
        )
        assert result.score > result_no_tools.score, "Tool usage should increase score"


class TestMediumRequests:
    @pytest.mark.asyncio
    async def test_moderate_code_generation(self, classifier: StaticClassifier) -> None:
        data = {
            "messages": [
                {"role": "user", "content": (
                    "Write a Python function that reads a CSV file, "
                    "filters rows by date range, and outputs a summary."
                )}
            ],
        }
        result = await classifier.classify(data)
        assert 20 <= result.score <= 70, f"Moderate task should be medium, got {result.score}"


class TestAnthropicFormat:
    @pytest.mark.asyncio
    async def test_system_prompt_in_top_level(self, classifier: StaticClassifier) -> None:
        data = {
            "system": "You are an expert software architect. Review and optimize code.",
            "messages": [{"role": "user", "content": "help me"}],
        }
        result = await classifier.classify(data)
        result_no_system = await classifier.classify(
            {"messages": [{"role": "user", "content": "help me"}]}
        )
        assert result.score > result_no_system.score, "System prompt should increase score"

    @pytest.mark.asyncio
    async def test_content_blocks_format(self, classifier: StaticClassifier) -> None:
        data = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is Python?"},
                    ],
                }
            ],
        }
        result = await classifier.classify(data)
        assert result.score <= 30, f"Simple content block should be simple, got {result.score}"


class TestMultiTurnConversation:
    @pytest.mark.asyncio
    async def test_long_conversation_boosts_score(self, classifier: StaticClassifier) -> None:
        messages = []
        for i in range(6):
            messages.append({"role": "user", "content": f"Question {i}"})
            messages.append({"role": "assistant", "content": f"Answer {i}"})

        result_long = await classifier.classify({"messages": messages})
        result_short = await classifier.classify(
            {"messages": [{"role": "user", "content": "Question 0"}]}
        )
        assert result_long.score > result_short.score, "Longer conversation should have higher score"


class TestErrorTraces:
    @pytest.mark.asyncio
    async def test_error_in_code_boosts_score(self, classifier: StaticClassifier) -> None:
        data = {
            "messages": [
                {"role": "user", "content": (
                    "Fix this error:\n"
                    "```\n"
                    "Traceback (most recent call last):\n"
                    "  File 'app.py', line 42\n"
                    "    raise ValueError('bad input')\n"
                    "ValueError: bad input\n"
                    "```"
                )}
            ],
        }
        result = await classifier.classify(data)
        assert result.score >= 20, f"Error trace should boost score, got {result.score}"


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_messages(self, classifier: StaticClassifier) -> None:
        result = await classifier.classify({"messages": []})
        assert 0 <= result.score <= 100

    @pytest.mark.asyncio
    async def test_no_messages_key(self, classifier: StaticClassifier) -> None:
        result = await classifier.classify({})
        assert 0 <= result.score <= 100

    @pytest.mark.asyncio
    async def test_empty_content(self, classifier: StaticClassifier) -> None:
        data = {"messages": [{"role": "user", "content": ""}]}
        result = await classifier.classify(data)
        assert 0 <= result.score <= 100
