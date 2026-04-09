"""Embedding provider abstraction.

The protocol matches the lightweight pattern used by `bsgateway/routing/classifiers/base.py`:
a single `runtime_checkable` Protocol with one async method, plus a concrete
implementation that wraps litellm. Per-tenant settings drive which model is used,
so we construct a fresh provider per request rather than holding a singleton.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import structlog

from bsgateway.embedding.settings import EmbeddingSettings

logger = structlog.get_logger(__name__)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def model(self) -> str: ...


class LiteLLMEmbeddingProvider:
    """Production embedding provider via ``litellm.aembedding``.

    Constructed per-tenant from `EmbeddingSettings`. The provider exposes its
    model name so callers can record it alongside the generated embedding —
    enabling stale-embedding detection when the tenant later switches models.
    """

    def __init__(self, settings: EmbeddingSettings) -> None:
        self._settings = settings

    @property
    def model(self) -> str:
        return self._settings.model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import litellm

        truncated = [t[: self._settings.max_input_length] for t in texts]
        response = await litellm.aembedding(
            model=self._settings.model,
            input=truncated,
            api_base=self._settings.api_base,
            timeout=self._settings.timeout,
        )
        return [item["embedding"] for item in response.data]


def build_provider(settings: EmbeddingSettings | None) -> EmbeddingProvider | None:
    """Factory: returns a provider for the given settings, or None if disabled."""
    if settings is None:
        return None
    return LiteLLMEmbeddingProvider(settings)
