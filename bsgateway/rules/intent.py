from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class IntentDefinition:
    """A custom intent defined by a tenant."""

    name: str
    description: str = ""
    example_embeddings: list[list[float]] = field(default_factory=list)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class IntentClassifier:
    """Classify user text into custom intents via embedding similarity."""

    def __init__(
        self,
        embed_fn: Callable[[str], Awaitable[list[float]]],
        intents: list[IntentDefinition],
        threshold: float = 0.7,
    ) -> None:
        self._embed_fn = embed_fn
        self._intents = intents
        self._threshold = threshold

    async def classify(self, text: str) -> str | None:
        """Classify text into the best matching intent.

        Returns the intent name if similarity >= threshold, else None.
        """
        if not text or not self._intents:
            return None

        text_embedding = await self._embed_fn(text)

        best_intent: str | None = None
        best_score: float = -1.0

        for intent in self._intents:
            for example_emb in intent.example_embeddings:
                score = cosine_similarity(text_embedding, example_emb)
                if score > best_score:
                    best_score = score
                    best_intent = intent.name

        if best_score >= self._threshold:
            logger.debug(
                "intent_classified",
                intent=best_intent,
                score=round(best_score, 4),
            )
            return best_intent

        return None
