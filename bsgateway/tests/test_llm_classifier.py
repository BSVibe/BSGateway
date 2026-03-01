from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.routing.classifiers.llm import LLMClassifier
from bsgateway.routing.models import LLMClassifierConfig


class FakeStaticClassifier:
    async def classify(self, data: dict) -> ClassificationResult:
        return ClassificationResult(tier="medium", strategy="static", score=50)


@pytest.fixture
def llm_config() -> LLMClassifierConfig:
    return LLMClassifierConfig(
        api_base="http://localhost:11434",
        model="llama3",
        timeout=3.0,
    )


@pytest.fixture
def fallback() -> FakeStaticClassifier:
    return FakeStaticClassifier()


@pytest.fixture
def classifier(
    llm_config: LLMClassifierConfig, fallback: FakeStaticClassifier
) -> LLMClassifier:
    return LLMClassifier(llm_config, fallback=fallback)


def _mock_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


class TestLLMClassification:
    @pytest.mark.asyncio
    async def test_simple_classification(self, classifier: LLMClassifier) -> None:
        with patch("bsgateway.routing.classifiers.llm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=_mock_response("simple"))
            result = await classifier.classify(
                {"messages": [{"role": "user", "content": "hello"}]}
            )
        assert result.tier == "simple"
        assert result.strategy == "llm"

    @pytest.mark.asyncio
    async def test_complex_classification(self, classifier: LLMClassifier) -> None:
        with patch("bsgateway.routing.classifiers.llm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=_mock_response("complex"))
            result = await classifier.classify(
                {"messages": [{"role": "user", "content": "design architecture"}]}
            )
        assert result.tier == "complex"
        assert result.strategy == "llm"

    @pytest.mark.asyncio
    async def test_medium_classification(self, classifier: LLMClassifier) -> None:
        with patch("bsgateway.routing.classifiers.llm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=_mock_response("medium"))
            result = await classifier.classify(
                {"messages": [{"role": "user", "content": "write a function"}]}
            )
        assert result.tier == "medium"
        assert result.strategy == "llm"


class TestLLMResponseParsing:
    @pytest.mark.asyncio
    async def test_parses_with_extra_text(self, classifier: LLMClassifier) -> None:
        with patch("bsgateway.routing.classifiers.llm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_response("I think this is complex.")
            )
            result = await classifier.classify(
                {"messages": [{"role": "user", "content": "test"}]}
            )
        assert result.tier == "complex"

    @pytest.mark.asyncio
    async def test_invalid_response_defaults_to_medium(
        self, classifier: LLMClassifier
    ) -> None:
        with patch("bsgateway.routing.classifiers.llm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_response("I cannot classify this.")
            )
            result = await classifier.classify(
                {"messages": [{"role": "user", "content": "test"}]}
            )
        assert result.tier == "medium"

    @pytest.mark.asyncio
    async def test_case_insensitive_parsing(self, classifier: LLMClassifier) -> None:
        with patch("bsgateway.routing.classifiers.llm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_response("SIMPLE")
            )
            result = await classifier.classify(
                {"messages": [{"role": "user", "content": "test"}]}
            )
        assert result.tier == "simple"


class TestLLMFallback:
    @pytest.mark.asyncio
    async def test_timeout_falls_back_to_static(self, classifier: LLMClassifier) -> None:
        with patch("bsgateway.routing.classifiers.llm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=TimeoutError("timeout"))
            result = await classifier.classify(
                {"messages": [{"role": "user", "content": "hello"}]}
            )
        assert result.strategy == "static"
        assert result.tier == "medium"
        assert result.score == 50

    @pytest.mark.asyncio
    async def test_connection_error_falls_back(self, classifier: LLMClassifier) -> None:
        with patch("bsgateway.routing.classifiers.llm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=ConnectionError("cannot connect")
            )
            result = await classifier.classify(
                {"messages": [{"role": "user", "content": "hello"}]}
            )
        assert result.strategy == "static"

    @pytest.mark.asyncio
    async def test_generic_error_falls_back(self, classifier: LLMClassifier) -> None:
        with patch("bsgateway.routing.classifiers.llm.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=RuntimeError("unexpected error")
            )
            result = await classifier.classify(
                {"messages": [{"role": "user", "content": "hello"}]}
            )
        assert result.strategy == "static"


class TestPromptBuilding:
    def test_prompt_includes_user_text(self, classifier: LLMClassifier) -> None:
        prompt = classifier._build_prompt("hello world", "")
        assert "hello world" in prompt

    def test_prompt_includes_system_context(self, classifier: LLMClassifier) -> None:
        prompt = classifier._build_prompt("test", "You are an expert")
        assert "You are an expert" in prompt
        assert "System context:" in prompt

    def test_prompt_no_system_context(self, classifier: LLMClassifier) -> None:
        prompt = classifier._build_prompt("test", "")
        assert "System context:" not in prompt
