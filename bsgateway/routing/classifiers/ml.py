from __future__ import annotations

from bsgateway.routing.classifiers.base import ClassificationResult, ClassifierProtocol


class MLClassifier:
    """ML-based classifier stub.

    Requires trained model and accumulated routing data.
    Falls back to the provided classifier until training data is available.
    """

    def __init__(self, fallback: ClassifierProtocol) -> None:
        self.fallback = fallback

    async def classify(self, data: dict) -> ClassificationResult:
        # TODO: load sklearn model from model.joblib and classify
        return await self.fallback.classify(data)
