from __future__ import annotations

import structlog

from bsgateway.routing.classifiers.base import ClassificationResult, ClassifierProtocol
from bsgateway.routing.classifiers.static import StaticClassifier
from bsgateway.routing.models import RoutingConfig

logger = structlog.get_logger(__name__)

__all__ = [
    "ClassificationResult",
    "ClassifierProtocol",
    "StaticClassifier",
    "create_classifier",
]


def create_classifier(config: RoutingConfig) -> ClassifierProtocol:
    """Factory: create a classifier based on the configured strategy."""
    strategy = config.classifier_strategy
    static = StaticClassifier(config.classifier, config.tiers)

    if strategy == "static":
        logger.info("classifier_created", strategy="static")
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
