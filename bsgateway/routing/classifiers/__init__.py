from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from bsgateway.routing.classifiers.base import ClassificationResult, ClassifierProtocol
from bsgateway.routing.classifiers.static import StaticClassifier
from bsgateway.routing.models import RoutingConfig

if TYPE_CHECKING:
    from bsgateway.core.cache import CacheManager

logger = structlog.get_logger(__name__)

__all__ = [
    "ClassificationResult",
    "ClassifierProtocol",
    "StaticClassifier",
    "create_classifier",
]


def create_classifier(
    config: RoutingConfig,
    cache: CacheManager | None = None,
) -> ClassifierProtocol:
    """Factory: create a classifier based on the configured strategy.

    When ``cache`` is supplied AND the strategy is ``static`` (Sprint 3 / S3-3),
    the static classifier is wrapped in a :class:`CachingClassifier` so the
    deterministic keyword scan / token estimation is memoised in Redis with
    tenant-scoped keys. ``llm`` and ``ml`` strategies are left unwrapped — their
    underlying calls are non-deterministic (LLM sampling) or already cached
    (ml model uses an in-process pipeline) so the cache wrapper would either
    poison results or duplicate work.
    """
    strategy = config.classifier_strategy
    static = StaticClassifier(config.classifier, config.tiers)

    if strategy == "static":
        if cache is not None:
            from bsgateway.routing.cache_classifier import (
                CachingClassifier,
                classifier_cache_ttl,
            )

            ttl = classifier_cache_ttl()
            logger.info(
                "classifier_created",
                strategy="static",
                cached=True,
                ttl_seconds=int(ttl.total_seconds()),
            )
            return CachingClassifier(static, cache, ttl=ttl)
        logger.info("classifier_created", strategy="static", cached=False)
        return static

    if strategy == "llm":
        from bsgateway.routing.classifiers.llm import LLMClassifier

        logger.info("classifier_created", strategy="llm", fallback="static")
        return LLMClassifier(config.llm_classifier, fallback=static)

    if strategy == "ml":
        from bsgateway.routing.classifiers.ml import MLClassifier

        logger.info("classifier_created", strategy="ml", fallback="static")
        return MLClassifier(fallback=static)

    logger.warning("unknown_classifier_strategy", strategy=strategy, fallback="static")
    return static
