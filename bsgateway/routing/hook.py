from __future__ import annotations

import asyncio
import os
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Literal

import structlog
import yaml

from bsgateway.routing.classifiers import ClassifierProtocol, create_classifier
from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.routing.collector import RoutingCollector
from bsgateway.routing.models import (
    ClassifierConfig,
    ClassifierWeights,
    CollectorConfig,
    EmbeddingConfig,
    LLMClassifierConfig,
    RoutingConfig,
    RoutingDecision,
    TierConfig,
)

if TYPE_CHECKING:
    from litellm.caching.dual_cache import DualCache
    from litellm.proxy._types import UserAPIKeyAuth

logger = structlog.get_logger(__name__)

# Lazy import to avoid circular dependency with litellm
_CustomLogger = None


def _get_custom_logger_base():
    global _CustomLogger
    if _CustomLogger is None:
        from litellm.integrations.custom_logger import CustomLogger
        _CustomLogger = CustomLogger
    return _CustomLogger


def _resolve_env(value: str) -> str:
    """Resolve ``os.environ/VAR`` references, matching LiteLLM's convention."""
    if isinstance(value, str) and value.startswith("os.environ/"):
        var = value[len("os.environ/"):]
        return os.environ.get(var, value)
    return value


def load_routing_config(config_path: str | None = None) -> RoutingConfig:
    """Load routing configuration from unified gateway.yaml.

    Reads both the ``routing`` section and ``model_list`` from the same YAML.
    ``passthrough_models`` is auto-derived from ``model_list[].model_name``
    so that adding a model only requires editing one place.
    """
    path = config_path or os.environ.get(
        "GATEWAY_CONFIG_PATH", "gateway.yaml"
    )
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning("routing_config_not_found", path=path)
        return RoutingConfig()

    routing = raw.get("routing", raw)

    # Parse tiers
    tiers: list[TierConfig] = []
    for name, tier_data in routing.get("tiers", {}).items():
        score_range = tier_data.get("score_range", [0, 100])
        tiers.append(TierConfig(
            name=name,
            score_range=(score_range[0], score_range[1]),
            model=tier_data["model"],
        ))

    # Parse aliases
    aliases = routing.get("aliases", {})

    # Parse auto-route patterns (fnmatch glob syntax)
    auto_route_patterns: list[str] = routing.get("auto_route_patterns", [])

    # Auto-derive passthrough from model_list + tier models
    passthrough_models: set[str] = set()
    for tier in tiers:
        passthrough_models.add(tier.model)
    for entry in raw.get("model_list", []):
        model_name = entry.get("model_name")
        if model_name:
            passthrough_models.add(model_name)

    # Parse classifier config
    classifier_raw = routing.get("classifier", {})
    static_raw = classifier_raw.get("static", classifier_raw)
    weights_raw = static_raw.get("weights", {})
    classifier_config = ClassifierConfig(
        weights=ClassifierWeights(**weights_raw) if weights_raw else ClassifierWeights(),
        token_thresholds=static_raw.get(
            "token_thresholds", {"low": 500, "medium": 2000, "high": 8000}
        ),
        complex_keywords=static_raw.get("complex_keywords", []),
        simple_keywords=static_raw.get("simple_keywords", []),
    )

    # Parse classifier strategy
    classifier_strategy = classifier_raw.get("strategy", "llm")

    # Parse LLM classifier config
    llm_raw = classifier_raw.get("llm", {})
    llm_config = LLMClassifierConfig(
        api_base=_resolve_env(llm_raw.get("api_base", "http://host.docker.internal:11434")),
        model=llm_raw.get("model", "llama3"),
        timeout=llm_raw.get("timeout", 3.0),
    )

    # Parse collector config
    collector_raw = routing.get("collector", {})
    embedding_config = None
    embedding_raw = collector_raw.get("embedding")
    if embedding_raw:
        embedding_config = EmbeddingConfig(
            api_base=_resolve_env(embedding_raw.get("api_base", "http://host.docker.internal:11434")),
            model=embedding_raw.get("model", "nomic-embed-text"),
            timeout=embedding_raw.get("timeout", 5.0),
            max_chars=embedding_raw.get("max_chars", 1000),
        )

    collector_config = CollectorConfig(
        enabled=collector_raw.get("enabled", True),
        embedding=embedding_config,
    )

    return RoutingConfig(
        tiers=tiers,
        aliases=aliases,
        auto_route_patterns=auto_route_patterns,
        passthrough_models=passthrough_models,
        classifier=classifier_config,
        fallback_tier=routing.get("fallback_tier", "medium"),
        classifier_strategy=classifier_strategy,
        llm_classifier=llm_config,
        collector=collector_config,
    )


class BSGatewayRouter:
    """LiteLLM custom callback handler for complexity-based routing.

    Intercepts requests via async_pre_call_hook and rewrites the model
    field based on complexity classification or alias resolution.
    """

    def __init__(
        self,
        config: RoutingConfig | None = None,
        classifier: ClassifierProtocol | None = None,
    ) -> None:
        self.config = config or load_routing_config()
        self.classifier = classifier or create_classifier(self.config)
        self._tier_map = {t.name: t for t in self.config.tiers}

        if self.config.collector.enabled:
            from bsgateway.core.config import settings

            if settings.database_url is None:
                logger.warning("collector_disabled", reason="database_url not set")
                self.collector = None
            else:
                self.collector: RoutingCollector | None = RoutingCollector(
                    database_url=settings.database_url,
                    embedding_config=self.config.collector.embedding,
                )
        else:
            self.collector = None

    async def async_pre_call_hook(
        self,
        user_api_key_dict: UserAPIKeyAuth,
        cache: DualCache,
        data: dict,
        call_type: Literal[
            "completion",
            "text_completion",
            "embeddings",
            "image_generation",
            "moderation",
            "audio_transcription",
        ],
    ) -> dict:
        """Intercept LLM requests and apply routing logic."""
        if call_type not in ("completion", "text_completion"):
            return data

        requested_model = data.get("model", "auto")
        decision = await self._route(requested_model, data)

        data["model"] = decision.resolved_model
        metadata = data.setdefault("metadata", {})
        metadata["routing_decision"] = {
            "method": decision.method,
            "original_model": decision.original_model,
            "resolved_model": decision.resolved_model,
            "complexity_score": decision.complexity_score,
            "tier": decision.tier,
        }

        logger.info(
            "request_routed",
            method=decision.method,
            original_model=decision.original_model,
            resolved_model=decision.resolved_model,
            complexity_score=decision.complexity_score,
            tier=decision.tier,
        )

        return data

    async def _route(self, requested_model: str, data: dict) -> RoutingDecision:
        """Determine the target model for a request."""
        # 1. Passthrough: known direct model names
        if requested_model in self.config.passthrough_models:
            return RoutingDecision(
                method="passthrough",
                original_model=requested_model,
                resolved_model=requested_model,
            )

        # 2. Alias resolution (exact match)
        if requested_model in self.config.aliases:
            resolved = self.config.aliases[requested_model]
            if resolved != "auto_route":
                return RoutingDecision(
                    method="alias",
                    original_model=requested_model,
                    resolved_model=resolved,
                )
            # Fall through to auto-routing

        # 3. Pattern-based auto-routing (e.g. "claude-*")
        elif self._matches_auto_route_pattern(requested_model):
            pass  # Fall through to auto-routing

        # 4. Auto-route based on complexity
        return await self._auto_route(requested_model, data)

    def _matches_auto_route_pattern(self, model: str) -> bool:
        """Check if a model name matches any auto_route_patterns."""
        return any(
            fnmatch(model, pattern)
            for pattern in self.config.auto_route_patterns
        )

    async def _auto_route(
        self, requested_model: str, data: dict
    ) -> RoutingDecision:
        """Classify complexity and select the appropriate tier model."""
        try:
            result = await self.classifier.classify(data)
        except Exception:
            logger.exception("classifier_error", original_model=requested_model)
            fallback = self._get_fallback_model()
            return RoutingDecision(
                method="auto",
                original_model=requested_model,
                resolved_model=fallback,
                complexity_score=None,
                tier=self.config.fallback_tier,
            )

        tier = self._tier_map.get(result.tier)
        target_model = tier.model if tier else self._get_fallback_model()

        decision = RoutingDecision(
            method="auto",
            original_model=requested_model,
            resolved_model=target_model,
            complexity_score=result.score,
            tier=result.tier,
        )

        # Record asynchronously (non-blocking)
        if self.collector:
            asyncio.create_task(self.collector.record(data, result, decision))

        return decision

    def _score_to_tier(self, score: int) -> str:
        """Map a complexity score to a tier name."""
        for tier in self.config.tiers:
            low, high = tier.score_range
            if low <= score <= high:
                return tier.name
        return self.config.fallback_tier

    def _get_fallback_model(self) -> str:
        """Get the model for the fallback tier."""
        tier = self._tier_map.get(self.config.fallback_tier)
        if tier:
            return tier.model
        if self.config.tiers:
            return self.config.tiers[0].model
        return "gpt-4o-mini"


def _create_proxy_handler() -> BSGatewayRouter:
    """Create the proxy handler instance that LiteLLM will import.

    Dynamically subclasses CustomLogger so litellm recognizes it as a callback,
    while keeping BSGatewayRouter testable without litellm dependency.
    """
    try:
        base = _get_custom_logger_base()

        class _ProxyHandler(base, BSGatewayRouter):
            def __init__(self) -> None:
                base.__init__(self)
                BSGatewayRouter.__init__(self)

        return _ProxyHandler()
    except ImportError:
        logger.warning("litellm_not_available", msg="Using standalone BSGatewayRouter")
        return BSGatewayRouter()


proxy_handler_instance = _create_proxy_handler()
