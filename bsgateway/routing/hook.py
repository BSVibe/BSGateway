from __future__ import annotations

import asyncio
import os
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import structlog
import yaml

from bsgateway.routing.classifiers import ClassifierProtocol, create_classifier
from bsgateway.routing.collector import RoutingCollector
from bsgateway.routing.constants import (
    CLASSIFIER_BLEND_WEIGHT,
    COMPLEXITY_HINT_BLEND_WEIGHT,
)
from bsgateway.routing.models import (
    ClassifierConfig,
    ClassifierWeights,
    CollectorConfig,
    EmbeddingConfig,
    LLMClassifierConfig,
    NexusHeaderConfig,
    NexusMetadata,
    RoutingConfig,
    RoutingDecision,
    TierConfig,
)

if TYPE_CHECKING:
    from litellm.caching.dual_cache import DualCache
    from litellm.proxy._types import UserAPIKeyAuth

    from bsgateway.core.cache import CacheManager

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
        var = value[len("os.environ/") :]
        return os.environ.get(var, value)
    return value


def load_routing_config(config_path: str | None = None) -> RoutingConfig:
    """Load routing configuration from unified gateway.yaml.

    Reads both the ``routing`` section and ``model_list`` from the same YAML.
    ``passthrough_models`` is auto-derived from ``model_list[].model_name``
    so that adding a model only requires editing one place.
    """
    path = config_path or os.environ.get("GATEWAY_CONFIG_PATH", "gateway.yaml")
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
        tiers.append(
            TierConfig(
                name=name,
                score_range=(score_range[0], score_range[1]),
                model=tier_data["model"],
            )
        )

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
            api_base=_resolve_env(
                embedding_raw.get("api_base", "http://host.docker.internal:11434")
            ),
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


def _extract_nexus_metadata(
    data: dict, header_config: NexusHeaderConfig | None = None
) -> NexusMetadata | None:
    """Extract X-BSNexus-* headers from request data into a NexusMetadata object.

    Returns None when no X-BSNexus-* headers are present (backward compatible).
    Header names are matched case-insensitively.
    """
    headers: dict = data.get("metadata", {}).get("headers", {})
    if not headers:
        return None

    if header_config is None:
        header_config = NexusHeaderConfig()

    normalized = {k.lower(): v for k, v in headers.items()}

    task_type: str | None = normalized.get(header_config.task_type)
    priority: str | None = normalized.get(header_config.priority)

    complexity_hint: int | None = None
    hint_raw = normalized.get(header_config.complexity_hint)
    if hint_raw is not None:
        try:
            complexity_hint = max(0, min(100, int(hint_raw)))
        except (ValueError, TypeError):
            pass

    if task_type is None and priority is None and complexity_hint is None:
        return None

    return NexusMetadata(task_type=task_type, priority=priority, complexity_hint=complexity_hint)


class BSGatewayRouter:
    """LiteLLM custom callback handler for complexity-based routing.

    Intercepts requests via async_pre_call_hook and rewrites the model
    field based on complexity classification or alias resolution.
    """

    def __init__(
        self,
        config: RoutingConfig | None = None,
        classifier: ClassifierProtocol | None = None,
        cache: CacheManager | None = None,
        supervisor: object | None = None,
    ) -> None:
        self.config = config or load_routing_config()
        # When ``classifier`` is supplied directly we skip the factory entirely
        # so existing tests that inject a stub keep working. When ``cache`` is
        # provided alongside the default classifier path the static classifier
        # is wrapped in a Redis-backed CachingClassifier (Sprint 3 / S3-3).
        self.classifier = classifier or create_classifier(self.config, cache=cache)
        self._tier_map = {t.name: t for t in self.config.tiers}
        self._background_tasks: set[asyncio.Task] = set()
        # P0.7 — BSGateway absorbs run.pre/run.post. Set via ``attach_supervisor``
        # at lifespan time so the hook stays test-friendly.
        self.supervisor: object | None = supervisor

        if self.config.collector.enabled:
            from bsgateway.core.config import settings

            if settings.collector_database_url is None:
                logger.warning("collector_disabled", reason="collector_database_url not set")
                self.collector = None
            else:
                self.collector: RoutingCollector | None = RoutingCollector(
                    database_url=settings.collector_database_url,
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
        nexus_metadata = _extract_nexus_metadata(data, self.config.nexus_headers)
        decision = await self._route(
            requested_model, data, nexus_metadata, user_api_key=user_api_key_dict
        )

        data["model"] = decision.resolved_model
        metadata = data.setdefault("metadata", {})
        metadata["routing_decision"] = {
            "method": decision.method,
            "original_model": decision.original_model,
            "resolved_model": decision.resolved_model,
            "complexity_score": decision.complexity_score,
            "tier": decision.tier,
            "decision_source": decision.decision_source,
            "nexus_metadata": (
                {
                    "task_type": nexus_metadata.task_type,
                    "priority": nexus_metadata.priority,
                    "complexity_hint": nexus_metadata.complexity_hint,
                }
                if nexus_metadata is not None
                else None
            ),
        }

        logger.info(
            "request_routed",
            method=decision.method,
            original_model=decision.original_model,
            resolved_model=decision.resolved_model,
            complexity_score=decision.complexity_score,
            tier=decision.tier,
        )

        # P0.7 — BSupervisor preflight. Only fires when both:
        #   * a BSupervisor client is attached (tests pass None for hook
        #     unit tests; production lifespan wires the real client), AND
        #   * the inbound request carries a run_id BSNexus owns. Pure
        #     proxy traffic gets no precheck (nothing to correlate with).
        if self.supervisor is not None:
            await self._maybe_run_preflight(metadata, resolved_model=decision.resolved_model)

        return data

    async def _maybe_run_preflight(
        self,
        metadata: dict,
        *,
        resolved_model: str,
    ) -> None:
        """Call BSupervisor /api/events run.pre and abort the LLM call on deny."""
        from bsgateway.supervisor.client import RunMetadata

        run_meta = RunMetadata.from_request_metadata(metadata, resolved_model=resolved_model)
        if run_meta is None:
            # No run_id / tenant_id → no audit event to emit.
            return

        result = await self.supervisor.run_pre(run_meta)  # type: ignore[union-attr]
        if not result.blocked:
            return

        # Block: surface the verdict via a litellm-aware exception so
        # downstream error mapping (`chat_completions` returns 400) keeps
        # working. We use the LiteLLM-native BadRequestError when present
        # and fall back to a typed ValueError so tests that don't import
        # litellm still see a clean abort.
        reason = result.reason or "blocked by BSupervisor policy"
        try:
            from litellm.exceptions import BadRequestError  # type: ignore[import-not-found]
        except Exception:  # pragma: no cover - exercised only if litellm absent
            raise PermissionError(f"BSupervisor denied request: {reason}") from None
        raise BadRequestError(
            message=f"BSupervisor denied request: {reason}",
            model=resolved_model,
            llm_provider="bsgateway",
        )

    async def async_log_success_event(
        self,
        kwargs: dict,
        response_obj: object,
        start_time: float,
        end_time: float,
    ) -> None:
        """LiteLLM CustomLogger hook — fires after a successful provider call.

        We use this entry point to emit BSupervisor run.post fire-and-forget
        so a slow supervisor never delays the user's response.
        """
        if self.supervisor is None:
            return
        await self._emit_run_post(
            kwargs,
            status_value="success",
            start_time=start_time,
            end_time=end_time,
            response_obj=response_obj,
        )

    async def async_log_failure_event(
        self,
        kwargs: dict,
        response_obj: object,
        start_time: float,
        end_time: float,
    ) -> None:
        """LiteLLM CustomLogger hook — fires after a failed provider call."""
        if self.supervisor is None:
            return
        await self._emit_run_post(
            kwargs,
            status_value="error",
            start_time=start_time,
            end_time=end_time,
            error=str(response_obj) if response_obj is not None else None,
        )

    async def _emit_run_post(
        self,
        kwargs: dict,
        *,
        status_value: str,
        start_time: float,
        end_time: float,
        response_obj: object | None = None,
        error: str | None = None,
    ) -> None:
        """Schedule a fire-and-forget BSupervisor run.post call.

        ``run.post`` is best-effort: errors are swallowed inside
        :meth:`BSupervisorClient.run_post`, but we additionally guard
        the construction phase so an unexpected payload shape never
        bubbles up to LiteLLM.
        """
        from bsgateway.supervisor.client import RunMetadata

        try:
            metadata = kwargs.get("metadata") or {}
            resolved_model = kwargs.get("model")
            run_meta = RunMetadata.from_request_metadata(metadata, resolved_model=resolved_model)
            if run_meta is None:
                return

            tokens_in: int | None = None
            tokens_out: int | None = None
            if response_obj is not None:
                usage = getattr(response_obj, "usage", None)
                if usage is not None:
                    tokens_in = getattr(usage, "prompt_tokens", None)
                    tokens_out = getattr(usage, "completion_tokens", None)

            duration_ms: int | None = None
            try:
                duration_ms = max(0, int((end_time - start_time) * 1000))
            except (TypeError, ValueError):
                duration_ms = None

            task = asyncio.create_task(
                self.supervisor.run_post(  # type: ignore[union-attr]
                    run_meta,
                    status=status_value,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    duration_ms=duration_ms,
                    error=error,
                ),
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        except Exception as exc:
            logger.warning("supervisor_run_post_schedule_failed", error=str(exc))

    async def _route(
        self,
        requested_model: str,
        data: dict,
        nexus_metadata: NexusMetadata | None = None,
        user_api_key: UserAPIKeyAuth | None = None,
    ) -> RoutingDecision:
        """Determine the target model for a request."""
        # 1. Passthrough: known direct model names
        if requested_model in self.config.passthrough_models:
            return RoutingDecision(
                method="passthrough",
                original_model=requested_model,
                resolved_model=requested_model,
                nexus_metadata=nexus_metadata,
            )

        # 2. Alias resolution (exact match)
        if requested_model in self.config.aliases:
            resolved = self.config.aliases[requested_model]
            if resolved != "auto_route":
                return RoutingDecision(
                    method="alias",
                    original_model=requested_model,
                    resolved_model=resolved,
                    nexus_metadata=nexus_metadata,
                )
            # Fall through to auto-routing

        # 3. Pattern-based auto-routing (e.g. "claude-*")
        elif self._matches_auto_route_pattern(requested_model):
            pass  # Fall through to auto-routing

        # 4. Auto-route based on complexity
        return await self._auto_route(
            requested_model, data, nexus_metadata, user_api_key=user_api_key
        )

    def _matches_auto_route_pattern(self, model: str) -> bool:
        """Check if a model name matches any auto_route_patterns."""
        return any(fnmatch(model, pattern) for pattern in self.config.auto_route_patterns)

    def _get_highest_tier(self) -> TierConfig | None:
        """Return the tier with the highest score range upper bound."""
        if not self.config.tiers:
            return None
        return max(self.config.tiers, key=lambda t: t.score_range[1])

    @staticmethod
    def _extract_tenant_id(
        data: dict,
        user_api_key: UserAPIKeyAuth | None = None,
    ) -> UUID | None:
        """Pull a tenant UUID out of LiteLLM-style request metadata.

        Resolution order (first hit wins):

        1. ``data["metadata"]["tenant_id"]`` — set by the BSGateway
           chat router (`ChatService.complete`).
        2. ``user_api_key.metadata["tenant_id"]`` — for proxy-direct
           traffic, LiteLLM may attach tenant context to the auth
           payload via the master-key admin UI (Sprint 0 follow-up,
           docs/TODO.md S1).
        3. ``user_api_key.team_id`` — LiteLLM convention for grouping
           keys by tenant; we treat the team_id as a tenant_id when
           nothing more specific is available.

        Returns ``None`` when no source supplies a parseable UUID.
        Callers MUST treat ``None`` as "do not record" to avoid
        cross-tenant leakage in ``routing_logs``.
        """

        def _coerce(raw: object) -> UUID | None:
            if raw is None:
                return None
            if isinstance(raw, UUID):
                return raw
            try:
                return UUID(str(raw))
            except (ValueError, TypeError, AttributeError):
                logger.warning("invalid_tenant_id_in_metadata", raw=str(raw))
                return None

        # 1. Explicit data metadata (chat-router path).
        metadata = data.get("metadata") or {}
        resolved = _coerce(metadata.get("tenant_id"))
        if resolved is not None:
            return resolved

        # 2/3. Fall back to the LiteLLM auth payload for proxy-direct
        # traffic. ``user_api_key`` is optional so existing call sites
        # that only pass ``data`` keep working.
        if user_api_key is not None:
            auth_metadata = getattr(user_api_key, "metadata", None) or {}
            if isinstance(auth_metadata, dict):
                resolved = _coerce(auth_metadata.get("tenant_id"))
                if resolved is not None:
                    return resolved
            resolved = _coerce(getattr(user_api_key, "team_id", None))
            if resolved is not None:
                return resolved

        return None

    async def _auto_route(
        self,
        requested_model: str,
        data: dict,
        nexus_metadata: NexusMetadata | None = None,
        user_api_key: UserAPIKeyAuth | None = None,
    ) -> RoutingDecision:
        """Classify complexity and select the appropriate tier model."""
        # Priority override: critical → skip classification, route to highest tier
        if nexus_metadata is not None and nexus_metadata.priority == "critical":
            highest = self._get_highest_tier()
            target_model = highest.model if highest else self._get_fallback_model()
            tier_name = highest.name if highest else self.config.fallback_tier
            logger.info(
                "routing_priority_override",
                original_model=requested_model,
                resolved_model=target_model,
                tier=tier_name,
            )
            return RoutingDecision(
                method="auto",
                original_model=requested_model,
                resolved_model=target_model,
                complexity_score=None,
                tier=tier_name,
                nexus_metadata=nexus_metadata,
                decision_source="priority_override",
            )

        try:
            result = await self.classifier.classify(data)
        except asyncio.CancelledError:
            # Cooperative cancellation must propagate so callers and
            # the event loop can finish their teardown.
            raise
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
        ) as exc:
            # Expected classifier failure modes: local LLM offline,
            # request timeout, malformed JSON, missing schema fields.
            # Fall back to the default tier with a typed warning.
            logger.warning(
                "classifier_error",
                original_model=requested_model,
                exc_info=exc,
            )
            fallback = self._get_fallback_model()
            return RoutingDecision(
                method="auto",
                original_model=requested_model,
                resolved_model=fallback,
                complexity_score=None,
                tier=self.config.fallback_tier,
                nexus_metadata=nexus_metadata,
            )
        except Exception as exc:
            # Programming bugs: log under a distinct event name so the
            # signal isn't buried alongside expected outages, but still
            # degrade to fallback (better to route than to 5xx).
            logger.error(
                "classifier_unexpected_error",
                original_model=requested_model,
                exc_info=exc,
            )
            fallback = self._get_fallback_model()
            return RoutingDecision(
                method="auto",
                original_model=requested_model,
                resolved_model=fallback,
                complexity_score=None,
                tier=self.config.fallback_tier,
                nexus_metadata=nexus_metadata,
            )

        # Blend classifier score with complexity_hint when provided
        if nexus_metadata is not None and nexus_metadata.complexity_hint is not None:
            classifier_score = result.score if result.score is not None else 50
            blended_score = round(
                CLASSIFIER_BLEND_WEIGHT * classifier_score
                + COMPLEXITY_HINT_BLEND_WEIGHT * nexus_metadata.complexity_hint
            )
            blended_tier = self._score_to_tier(blended_score)
            tier = self._tier_map.get(blended_tier)
            target_model = tier.model if tier else self._get_fallback_model()
            decision_source = "blend"
            final_score = blended_score
            final_tier = blended_tier
            logger.info(
                "routing_complexity_blend",
                original_model=requested_model,
                classifier_score=classifier_score,
                hint=nexus_metadata.complexity_hint,
                blended_score=blended_score,
                tier=blended_tier,
            )
        else:
            tier = self._tier_map.get(result.tier)
            target_model = tier.model if tier else self._get_fallback_model()
            decision_source = "classifier"
            final_score = result.score
            final_tier = result.tier

        decision = RoutingDecision(
            method="auto",
            original_model=requested_model,
            resolved_model=target_model,
            complexity_score=final_score,
            tier=final_tier,
            nexus_metadata=nexus_metadata,
            decision_source=decision_source,
        )

        # Record asynchronously (non-blocking), track for graceful shutdown.
        # Skip recording when no tenant_id is present so we never write a
        # NULL-tenant row that other tenants' queries could sweep up.
        if self.collector:
            tenant_id = self._extract_tenant_id(data, user_api_key=user_api_key)
            if tenant_id is not None:
                _task = asyncio.create_task(
                    self.collector.record(data, result, decision, tenant_id=tenant_id)
                )
                if hasattr(self, "_background_tasks"):
                    self._background_tasks.add(_task)
                    _task.add_done_callback(self._background_tasks.discard)
            else:
                logger.debug(
                    "routing_collector_skipped",
                    reason="no tenant_id on metadata; refusing to log",
                    original_model=requested_model,
                )

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

    def attach_supervisor(self, supervisor: object | None) -> None:
        """Wire a :class:`BSupervisorClient` into the hook (P0.7).

        Idempotent — passing ``None`` leaves any previously attached client
        in place so the lifespan can be re-run in tests.
        """
        if supervisor is None:
            return
        self.supervisor = supervisor

    def attach_cache(self, cache: CacheManager | None) -> None:
        """Wire a Redis-backed cache into the static classifier (S3-3).

        ``proxy_handler_instance`` is built at module import time, before
        the FastAPI lifespan has had a chance to spin up Redis. Once the
        ``CacheManager`` is available the API lifespan calls this method
        so the static classifier gets transparently replaced by a
        :class:`CachingClassifier`.

        Idempotent — calling with ``cache=None`` (Redis disabled) leaves
        the existing classifier alone. Wrapping is only applied when the
        router's current classifier is a bare :class:`StaticClassifier`;
        the LLM and ML strategies are intentionally not cached because
        their outputs are non-deterministic / already memoised.
        """
        if cache is None:
            return

        from bsgateway.routing.cache_classifier import (
            CachingClassifier,
            classifier_cache_ttl,
        )
        from bsgateway.routing.classifiers.static import StaticClassifier

        if isinstance(self.classifier, CachingClassifier):
            return  # already wrapped — idempotent

        if not isinstance(self.classifier, StaticClassifier):
            logger.info(
                "classifier_cache_skipped",
                reason="classifier_not_static",
                classifier_type=type(self.classifier).__name__,
            )
            return

        ttl = classifier_cache_ttl()
        self.classifier = CachingClassifier(self.classifier, cache, ttl=ttl)
        logger.info(
            "classifier_cache_attached",
            ttl_seconds=int(ttl.total_seconds()),
        )

    async def aclose(self) -> None:
        """Release any resources held by the router (audit issue H15).

        Currently this drains the optional :class:`RoutingCollector`'s
        asyncpg pool. The API lifespan calls this during graceful
        shutdown so connections are not leaked when the litellm proxy
        embeds the router as ``proxy_handler_instance``.
        """
        # Drain background record() tasks first so they do not race
        # against close() and hit a closed pool. Best-effort: anything
        # that raises (other than cancellation) is logged and the close
        # path proceeds. Cancellation must propagate so the parent
        # shutdown sequence is not stalled.
        if self._background_tasks:
            pending = list(self._background_tasks)
            try:
                await asyncio.wait(pending, timeout=5.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("router_background_drain_error", exc_info=exc)

        if self.collector is not None:
            try:
                await self.collector.close()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Shutdown must not raise — log and continue.
                logger.warning("router_collector_close_failed", exc_info=exc)


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
