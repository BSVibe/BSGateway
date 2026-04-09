"""Embedding service: generation + serialization with graceful degradation.

Wraps an `EmbeddingProvider` to produce serialized BYTEA payloads suitable for
storage in `intent_examples.embedding`. All failures are logged and degraded
to ``None`` so example creation never blocks on a transient embedding-API
outage — the example row is still written, just without an embedding, and
will show up in `list_examples_needing_reembedding` for later backfill.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from bsgateway.embedding.provider import EmbeddingProvider
from bsgateway.embedding.serialization import serialize_embedding

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EmbeddedExample:
    """Result of embedding a single example."""

    text: str
    embedding: bytes | None
    model: str


class EmbeddingService:
    """Tenant-scoped embedding lifecycle: generate, serialize, tag with model."""

    def __init__(self, provider: EmbeddingProvider) -> None:
        self._provider = provider

    @property
    def model(self) -> str:
        return self._provider.model

    async def test_connection(self) -> int:
        """Verify the embedding provider is reachable and returns sane data.

        Sends a single tiny embed request and asserts the response is a
        non-empty vector. Returns the vector dimension on success. Raises
        whatever error the underlying provider raises (typically a
        litellm exception with the upstream HTTP status).
        """
        result = await self._provider.embed(["ping"])
        if not result or not result[0]:
            raise RuntimeError("Embedding provider returned empty result for test input")
        return len(result[0])

    async def embed_one(self, text: str) -> EmbeddedExample:
        """Embed a single text. Returns an EmbeddedExample (embedding=None on failure)."""
        try:
            vectors = await self._provider.embed([text])
        except Exception:
            logger.warning(
                "embedding_generation_failed",
                exc_info=True,
                text_length=len(text),
                model=self._provider.model,
            )
            return EmbeddedExample(text=text, embedding=None, model=self._provider.model)
        return EmbeddedExample(
            text=text,
            embedding=serialize_embedding(vectors[0]),
            model=self._provider.model,
        )

    async def embed_many(self, texts: list[str]) -> list[EmbeddedExample]:
        """Batch-embed in a single API call. All-or-nothing on failure."""
        if not texts:
            return []
        try:
            vectors = await self._provider.embed(texts)
        except Exception:
            logger.warning(
                "embedding_batch_failed",
                exc_info=True,
                count=len(texts),
                model=self._provider.model,
            )
            return [
                EmbeddedExample(text=t, embedding=None, model=self._provider.model) for t in texts
            ]
        return [
            EmbeddedExample(text=t, embedding=serialize_embedding(v), model=self._provider.model)
            for t, v in zip(texts, vectors, strict=True)
        ]
