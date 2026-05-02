"""Redis-backed caching wrapper around any classifier.

Sprint 3 / S3-3: Static classifier results are deterministic for a given
tenant + request fingerprint, so we memoise them in Redis to skip the
keyword scan / token estimation on hot paths. Tenant isolation is part of
the cache key so one tenant cannot read another tenant's cached tier.

Behaviour summary:

* **Cache key** = ``cache:classifier:{tenant_id|"_global_"}:{fingerprint}``.
  ``fingerprint`` is a hash of the request content (messages, system,
  tool names) — request *metadata* (trace ids, etc) is excluded.
* **TTL** is supplied by the caller (env-driven via
  :func:`bsgateway.routing.cache_classifier.classifier_cache_ttl`).
* **Graceful degradation**: when the underlying :class:`CacheManager`
  raises (Redis down, decode error, etc.) the wrapper falls back to the
  inner classifier. When ``cache=None`` it is a transparent passthrough.
* **Metrics**: ``hit_count`` / ``miss_count`` / ``hit_rate`` are
  cumulative process-wide counters and a structured log event
  (``classifier_cache_hit``/``classifier_cache_miss``) is emitted on
  every lookup so an external scraper can chart the hit ratio.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from bsvibe_audit.events.base import AuditActor
from bsvibe_audit.events.gateway import ClassifierCacheHit

from bsgateway.audit_publisher import emit_event, should_sample_cache_hit
from bsgateway.core.cache import CacheManager
from bsgateway.routing.classifiers.base import ClassificationResult, ClassifierProtocol

logger = structlog.get_logger(__name__)

CACHE_KEY_PREFIX = "cache:classifier:"
DEFAULT_CACHE_TTL_SECONDS = 600  # 10 minutes — between rules cache (15m) and usage (5m)


def classifier_cache_ttl() -> timedelta:
    """Return the configured TTL for classifier cache entries.

    Reads ``CLASSIFIER_CACHE_TTL_SECONDS`` from the environment so operators
    can tune without a code change. Falls back to
    :data:`DEFAULT_CACHE_TTL_SECONDS` when unset or unparseable.
    """
    raw = os.environ.get("CLASSIFIER_CACHE_TTL_SECONDS")
    if raw is None:
        return timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS)
    try:
        seconds = int(raw)
    except ValueError:
        logger.warning(
            "classifier_cache_ttl_invalid",
            value=raw,
            fallback=DEFAULT_CACHE_TTL_SECONDS,
        )
        return timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS)
    if seconds <= 0:
        logger.warning(
            "classifier_cache_ttl_non_positive",
            value=seconds,
            fallback=DEFAULT_CACHE_TTL_SECONDS,
        )
        return timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS)
    return timedelta(seconds=seconds)


def _extract_tenant_id(data: dict) -> UUID | None:
    """Pull a UUID out of ``data['metadata']['tenant_id']`` if present."""
    metadata = data.get("metadata") or {}
    raw = metadata.get("tenant_id") if isinstance(metadata, dict) else None
    if raw is None:
        return None
    if isinstance(raw, UUID):
        return raw
    try:
        return UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def _normalise_message_content(content: Any) -> str:
    """Flatten OpenAI/Anthropic content arrays into a single string for hashing."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(json.dumps(block, sort_keys=True, ensure_ascii=False))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def fingerprint_request(data: dict) -> str:
    """Compute a stable hash of the *content* portion of a request.

    Hash inputs:

    * ordered list of (role, content) pairs from ``messages``
    * top-level ``system`` prompt (Anthropic-style)
    * tool names (declared schema, not invocation results)

    Anything outside this — request ``metadata``, model name, model params
    like temperature — is intentionally excluded so the same prompt with a
    different metadata trace_id reuses the cached classification.

    Returns a 32-char hex digest (BLAKE2b-128).
    """
    h = hashlib.blake2b(digest_size=16)

    messages = data.get("messages", []) or []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", ""))
        content = _normalise_message_content(msg.get("content", ""))
        h.update(b"M\x00")
        h.update(role.encode("utf-8", errors="replace"))
        h.update(b"\x00")
        h.update(content.encode("utf-8", errors="replace"))
        h.update(b"\x01")

    system = data.get("system", "")
    if isinstance(system, str) and system:
        h.update(b"S\x00")
        h.update(system.encode("utf-8", errors="replace"))
        h.update(b"\x01")

    tools = data.get("tools", []) or []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        # Anthropic uses {"name": ...} at top level; OpenAI uses {"function": {"name": ...}}
        name = tool.get("name") or (tool.get("function") or {}).get("name", "")
        if name:
            h.update(b"T\x00")
            h.update(str(name).encode("utf-8", errors="replace"))
            h.update(b"\x01")

    return h.hexdigest()


def make_cache_key(tenant_id: UUID | None, fingerprint: str) -> str:
    """Build a tenant-scoped cache key.

    ``tenant_id=None`` callers (e.g. proxy-direct traffic without a tenant
    in metadata) get a dedicated ``_global_`` namespace so they cannot
    collide with — or read from — any real tenant's cached entries.
    """
    scope = str(tenant_id) if tenant_id is not None else "_global_"
    return f"{CACHE_KEY_PREFIX}{scope}:{fingerprint}"


def _result_to_dict(result: ClassificationResult) -> dict:
    return {
        "tier": result.tier,
        "strategy": result.strategy,
        "score": result.score,
        "confidence": result.confidence,
    }


def _result_from_dict(payload: object) -> ClassificationResult | None:
    """Best-effort reconstruction; returns None when payload shape is unexpected."""
    if not isinstance(payload, dict):
        return None
    tier = payload.get("tier")
    strategy = payload.get("strategy")
    if not isinstance(tier, str) or not isinstance(strategy, str):
        return None
    return ClassificationResult(
        tier=tier,
        strategy=strategy,
        score=payload.get("score"),
        confidence=payload.get("confidence"),
    )


class CachingClassifier:
    """Wraps any :class:`ClassifierProtocol` with a Redis-backed cache.

    The wrapper is itself a :class:`ClassifierProtocol` (only ``classify``
    is required) so it can drop-in replace the static / llm / ml
    classifier.

    On every call:

    1. Build cache key from ``(tenant_id, fingerprint(data))``.
    2. ``cache.get(key)`` — on hit return the cached :class:`ClassificationResult`.
    3. On miss call the inner classifier and best-effort ``cache.set``.
       ``CacheManager`` already swallows Redis errors and returns
       ``False`` from ``set`` / ``None`` from ``get``, so the wrapper is
       fail-soft by construction.

    Phase Audit Batch 2 — when ``audit_app_state`` is set the wrapper
    samples cache hits at ``CACHE_HIT_SAMPLE_RATE`` (env-tunable via
    ``CLASSIFIER_AUDIT_SAMPLE_RATE``) and emits a
    ``gateway.classifier.cache_hit`` event for the sampled subset. The
    sampler is deterministic on the request fingerprint so a single hot
    prompt either reliably surfaces or reliably stays silent.
    """

    def __init__(
        self,
        inner: ClassifierProtocol,
        cache: CacheManager | None,
        *,
        ttl: timedelta,
        audit_app_state: object | None = None,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._ttl = ttl
        self._audit_app_state = audit_app_state
        self.hit_count = 0
        self.miss_count = 0

    def attach_audit_state(self, app_state: object | None) -> None:
        """Plumb the FastAPI ``app.state`` so cache hits can be (sampled) audited.

        Called from the API lifespan once the audit emitter / session
        factory have been constructed; idempotent so unit tests can wrap
        a classifier first and attach later.
        """
        self._audit_app_state = app_state

    @property
    def hit_rate(self) -> float:
        total = self.hit_count + self.miss_count
        if total == 0:
            return 0.0
        return self.hit_count / total

    async def classify(self, data: dict) -> ClassificationResult:
        if self._cache is None:
            return await self._inner.classify(data)

        tenant_id = _extract_tenant_id(data)
        try:
            fingerprint = fingerprint_request(data)
        except (TypeError, ValueError):
            # Defensive: anything malformed enough to defeat the hasher
            # falls back to the inner classifier without caching.
            logger.warning("classifier_cache_fingerprint_failed", exc_info=True)
            return await self._inner.classify(data)

        key = make_cache_key(tenant_id, fingerprint)

        cached_payload: object | None = None
        try:
            cached_payload = await self._cache.get(key)
        except Exception as exc:
            # Fail-soft on ANY Redis backend error: caching must never block
            # routing. CacheManager already swallows redis.RedisError /
            # ConnectionError / TimeoutError / OSError internally, so we are
            # really only catching programming bugs here — but a bug in the
            # cache layer must still not 5xx user requests.
            logger.warning("classifier_cache_get_failed", key=key, exc_info=exc)
            cached_payload = None

        if cached_payload is not None:
            cached = _result_from_dict(cached_payload)
            if cached is not None:
                self.hit_count += 1
                logger.info(
                    "classifier_cache_hit",
                    tier=cached.tier,
                    strategy=cached.strategy,
                    tenant_id=str(tenant_id) if tenant_id else None,
                    hits=self.hit_count,
                    misses=self.miss_count,
                )
                # Phase Audit Batch 2 — emit gateway.classifier.cache_hit
                # for a deterministic 1% sample. Skip when audit not wired
                # (default) so tests + module-level imports stay cheap.
                if self._audit_app_state is not None and should_sample_cache_hit(fingerprint):
                    actor_id = str(tenant_id) if tenant_id else "system"
                    await emit_event(
                        self._audit_app_state,
                        ClassifierCacheHit(
                            actor=AuditActor(type="system", id=actor_id),
                            tenant_id=str(tenant_id) if tenant_id else None,
                            data={
                                "tier": cached.tier,
                                "strategy": cached.strategy,
                                "fingerprint": fingerprint,
                                "hit_count": self.hit_count,
                            },
                        ),
                    )
                return cached
            # Corrupt payload — best-effort delete so it does not poison
            # subsequent reads, then fall through.
            try:
                await self._cache.delete(key)
            except Exception:
                # Best-effort cleanup of corrupt cached entry. Any failure
                # here is fine — we already have the inner-classifier
                # fallback below, and the corrupt entry will eventually
                # expire via its TTL.
                pass

        # Cache miss (or corrupt/unrecoverable cached payload)
        result = await self._inner.classify(data)
        self.miss_count += 1
        logger.info(
            "classifier_cache_miss",
            tier=result.tier,
            strategy=result.strategy,
            tenant_id=str(tenant_id) if tenant_id else None,
            hits=self.hit_count,
            misses=self.miss_count,
        )

        try:
            await self._cache.set(key, _result_to_dict(result), ttl=self._ttl)
        except Exception as exc:
            # Fail-soft: never block routing on a cache-write failure.
            # CacheManager already returns False on Redis errors, so this
            # only fires for unexpected bugs in the cache layer.
            logger.warning("classifier_cache_set_failed", key=key, exc_info=exc)

        return result
