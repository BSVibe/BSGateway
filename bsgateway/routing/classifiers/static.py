from __future__ import annotations

import re

import structlog

from bsgateway.routing.classifiers.base import (
    ClassificationResult,
    extract_all_text,
    extract_system_prompt,
    extract_user_text,
)
from bsgateway.routing.models import ClassifierConfig, TierConfig

logger = structlog.get_logger(__name__)


class StaticClassifier:
    """Heuristic-based request complexity classifier.

    Computes a score from 0-100 based on multiple signals,
    then maps the score to a tier (simple/medium/complex).
    """

    def __init__(self, config: ClassifierConfig, tiers: list[TierConfig]) -> None:
        self.config = config
        self.tiers = tiers

    async def classify(self, data: dict) -> ClassificationResult:
        score = self._compute_score(data)
        tier = self._score_to_tier(score)
        return ClassificationResult(tier=tier, strategy="static", score=score)

    def _compute_score(self, data: dict) -> int:
        """Return a complexity score from 0 to 100."""
        messages = data.get("messages", [])
        tools = data.get("tools", [])

        system_prompt = extract_system_prompt(data)
        all_text = extract_all_text(messages)
        user_text = extract_user_text(messages)

        raw = {
            "token_count": self._score_token_count(all_text),
            "system_prompt": self._score_system_prompt(system_prompt),
            "keyword_patterns": self._score_keywords(user_text),
            "conversation_length": self._score_conversation_length(messages),
            "code_complexity": self._score_code_complexity(all_text),
            "tool_usage": self._score_tool_usage(tools),
        }

        w = self.config.weights
        weighted = {
            "token_count": raw["token_count"] * w.token_count,
            "system_prompt": raw["system_prompt"] * w.system_prompt,
            "keyword_patterns": raw["keyword_patterns"] * w.keyword_patterns,
            "conversation_length": raw["conversation_length"] * w.conversation_length,
            "code_complexity": raw["code_complexity"] * w.code_complexity,
            "tool_usage": raw["tool_usage"] * w.tool_usage,
        }
        total = sum(weighted.values())

        # Keyword-based floor
        kw_raw = raw["keyword_patterns"]
        if kw_raw >= 80:
            total = max(total, 70)
        elif kw_raw >= 60:
            total = max(total, 45)
        elif kw_raw >= 40:
            total = max(total, 25)

        # System prompt floor
        sp_raw = raw["system_prompt"]
        if sp_raw >= 60:
            total = max(total, 50)

        # Code complexity floor
        if raw["code_complexity"] >= 60:
            total = max(total, 50)
        elif raw["code_complexity"] >= 30:
            total = max(total, 30)

        result = max(0, min(100, int(total)))

        logger.debug(
            "complexity_classified",
            score=result,
            raw_signals=raw,
            weighted=weighted,
        )
        return result

    def _score_to_tier(self, score: int) -> str:
        for tier in self.tiers:
            low, high = tier.score_range
            if low <= score <= high:
                return tier.name
        return "medium"

    def _score_token_count(self, text: str) -> int:
        estimated_tokens = int(len(text.split()) * 1.3)
        thresholds = self.config.token_thresholds
        if estimated_tokens < thresholds["low"]:
            return 10
        elif estimated_tokens < thresholds["medium"]:
            return 35
        elif estimated_tokens < thresholds["high"]:
            return 60
        return 85

    def _score_system_prompt(self, prompt: str) -> int:
        if not prompt:
            return 0
        complexity_words = [
            "architect", "design", "analyze", "review",
            "plan", "refactor", "security", "optimize",
        ]
        matches = sum(1 for w in complexity_words if w in prompt.lower())
        base = min(40, len(prompt) // 50)
        keyword_boost = min(60, matches * 15)
        return min(100, base + keyword_boost)

    def _score_keywords(self, text: str) -> int:
        text_lower = text.lower()
        complex_count = sum(
            1 for kw in self.config.complex_keywords if kw in text_lower
        )
        simple_count = sum(
            1 for kw in self.config.simple_keywords if kw in text_lower
        )

        if complex_count > 0 and simple_count == 0:
            return min(100, 50 + complex_count * 10)
        if simple_count > 0 and complex_count == 0:
            return max(0, 15 - simple_count * 3)
        # Mixed signals
        return max(0, min(100, 30 + (complex_count - simple_count) * 8))

    def _score_conversation_length(self, messages: list) -> int:
        turn_count = len([m for m in messages if m.get("role") == "user"])
        if turn_count <= 1:
            return 10
        elif turn_count <= 3:
            return 30
        elif turn_count <= 5:
            return 50
        return 70

    def _score_code_complexity(self, text: str) -> int:
        code_blocks = re.findall(r"```[\s\S]*?```", text)
        if not code_blocks:
            return 0
        total_lines = sum(block.count("\n") for block in code_blocks)
        error_patterns = ["Traceback", "Error:", "Exception", "FAILED"]
        has_errors = any(p in text for p in error_patterns)
        base = min(60, total_lines * 2)
        error_boost = 25 if has_errors else 0
        multi_block_boost = min(15, (len(code_blocks) - 1) * 5)
        return min(100, base + error_boost + multi_block_boost)

    def _score_tool_usage(self, tools: list) -> int:
        if not tools:
            return 0
        return min(80, 30 + len(tools) * 10)
