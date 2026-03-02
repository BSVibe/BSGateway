from __future__ import annotations

from typing import cast

import litellm
from litellm.types.utils import Choices, ModelResponse
import structlog

from bsgateway.routing.classifiers.base import (
    ClassificationResult,
    ClassifierProtocol,
    extract_system_prompt,
    extract_user_text,
)
from bsgateway.routing.models import LLMClassifierConfig

logger = structlog.get_logger(__name__)

CLASSIFICATION_PROMPT = """\
Classify this request's complexity. Reply ONLY with one word: simple, medium, or complex.

simple: greeting, simple Q&A, format conversion, translation
medium: code generation, explanation, data processing, single-file changes
complex: architecture design, security audit, multi-step refactoring, system optimization

{system_context}Request: {user_text}"""

VALID_TIERS = {"simple", "medium", "complex"}


class LLMClassifier:
    """LLM-based request complexity classifier using a local model via Ollama.

    Falls back to the provided static classifier on any failure.
    """

    def __init__(
        self, config: LLMClassifierConfig, fallback: ClassifierProtocol
    ) -> None:
        self.config = config
        self.fallback = fallback

    async def classify(self, data: dict) -> ClassificationResult:
        user_text = extract_user_text(data.get("messages", []))
        system_text = extract_system_prompt(data)
        prompt = self._build_prompt(user_text[:500], system_text[:200])

        try:
            response = cast(
                ModelResponse,
                await litellm.acompletion(
                    model=self.config.model,
                    messages=[{"role": "user", "content": prompt}],
                    api_base=self.config.api_base,
                    max_tokens=20,
                    temperature=0,
                    timeout=self.config.timeout,
                    stream=False,
                ),
            )
            choice = cast(Choices, response.choices[0])
            raw = (choice.message.content or "").strip().lower()
            tier = self._parse_tier(raw)
            logger.debug("llm_classified", tier=tier, raw_response=raw)
            return ClassificationResult(tier=tier, strategy="llm")
        except Exception:
            logger.warning("llm_classifier_fallback", exc_info=True)
            return await self.fallback.classify(data)

    def _build_prompt(self, user_text: str, system_text: str) -> str:
        system_context = ""
        if system_text:
            system_context = f"System context: {system_text}\n"
        return CLASSIFICATION_PROMPT.format(
            system_context=system_context, user_text=user_text
        )

    @staticmethod
    def _parse_tier(raw: str) -> str:
        """Extract a valid tier from LLM response, defaulting to medium."""
        for tier in VALID_TIERS:
            if tier in raw:
                return tier
        return "medium"
