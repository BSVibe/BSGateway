"""Phase Audit Batch 2 — BSGateway → bsvibe-audit emit helpers.

This module is the single integration point between BSGateway's
asyncpg-based domain code and the SQLAlchemy-based ``bsvibe-audit``
package. It exists because BSGateway has no SQLAlchemy ORM yet (the
domain layer talks to PG directly via asyncpg + raw SQL files), so we
cannot emit inside the same transaction as the domain write — we own a
private SQLAlchemy AsyncEngine + sessionmaker dedicated to the
``audit_outbox`` table.

**Atomicity caveat (non-trivial decision)**

``BSVibe_Audit_Design.md §3.1`` recommends inserting the outbox row in
the *same* transaction as the domain change so events are never lost.
BSGateway emits *after* the domain commit using a separate
SQLAlchemy connection. The trade-off:

* domain write succeeds, audit emit fails → event is lost (acceptable
  posture for the four ``gateway.*`` events: high-volume,
  non-billing-critical, mirrors today's fire-and-forget
  ``bsgateway.audit.AuditService.record(...)`` semantics);
* domain write fails → emit not reached → no spurious event.

This is documented as a deliberate scope-narrowing decision until
BSGateway adopts SQLAlchemy at the domain layer (Lockin §3 follow-up).
The four other ``gateway.*`` consumers (BSage / BSNexus / BSupervisor /
BSVibe-Auth) all already use SQLAlchemy and so emit atomically per
spec.

**Sampling for ``classifier.cache_hit``**

Cache hits run on every chat/completions call — emitting one outbox row
per hit drowns the relay. We sample at 1% by default
(``CACHE_HIT_SAMPLE_RATE`` / ``CLASSIFIER_AUDIT_SAMPLE_RATE`` env), keyed
deterministically on the cache fingerprint so the same prompt always
samples the same way (operators get coherent timeline snapshots, not
random noise).
"""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

import structlog
from bsvibe_audit import AuditEmitter
from bsvibe_audit.events.base import AuditEventBase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger(__name__)

# Default 1% sampling rate for classifier cache-hit emission. Override via
# ``CLASSIFIER_AUDIT_SAMPLE_RATE`` env var; values outside [0.0, 1.0] are
# clamped at parse time.
CACHE_HIT_SAMPLE_RATE: float = 0.01


# ---------------------------------------------------------------------------
# Outbox lifespan helpers — invoked from `bsgateway.api.app.lifespan`.
# ---------------------------------------------------------------------------


def build_audit_outbox(
    *,
    enabled: bool,
    collector_database_url: str,
) -> tuple[AuditEmitter | None, async_sessionmaker[AsyncSession] | None]:
    """Build the (emitter, session_factory) pair when audit is enabled.

    Returns ``(None, None)`` when:

    * ``enabled=False`` (operator opt-out via
      ``BSVIBE_AUDIT_OUTBOX_ENABLED=false``); or
    * ``collector_database_url`` is empty / falsy (dev-friendly default
      so unconfigured local runs don't fail).

    Otherwise creates a SQLAlchemy async engine pointed at the same DB
    BSGateway uses for routing logs / tenants / rules. The asyncpg URL
    is rewritten to SQLAlchemy's asyncpg driver scheme so the same
    ``COLLECTOR_DATABASE_URL`` powers both stacks.

    The engine is intentionally distinct from BSGateway's asyncpg pool
    — see the module docstring for the atomicity caveat.
    """
    if not enabled:
        logger.info("audit_outbox_disabled", reason="BSVIBE_AUDIT_OUTBOX_ENABLED=false")
        return None, None
    if not collector_database_url:
        logger.info("audit_outbox_disabled", reason="collector_database_url unset")
        return None, None

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(
        _normalise_async_url(collector_database_url),
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    emitter = AuditEmitter()
    logger.info("audit_outbox_enabled")
    return emitter, factory


def _normalise_async_url(url: str) -> str:
    """Make sure SQLAlchemy receives an async-driver URL.

    BSGateway's runtime asyncpg DSN is already
    ``postgresql+asyncpg://...``; older deployments may still ship
    ``postgresql://...`` which SQLAlchemy would route through psycopg2
    (sync). Rewrite once at startup so the engine stays async without
    forcing every operator to update ``.env``.
    """
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


# ---------------------------------------------------------------------------
# emit_event — single contract used by every BSGateway emit call site.
# ---------------------------------------------------------------------------


async def emit_event(app_state: object, event: AuditEventBase) -> None:
    """Best-effort enqueue ``event`` into the audit outbox.

    Lookup contract:

    * ``app_state.audit_emitter`` (an :class:`AuditEmitter`) and
      ``app_state.audit_outbox_session_factory`` (an
      ``async_sessionmaker``). When either is missing the call is a
      no-op (mirrors P0.7's ``BSUPERVISOR_AUDIT_ENABLED=false`` posture).

    Failure isolation: any exception inside the emit is logged at
    WARNING and swallowed. Phase Audit Batch 2 explicitly chooses
    fire-and-forget over hot-path failure — see module docstring.
    """
    factory = getattr(app_state, "audit_outbox_session_factory", None)
    emitter = getattr(app_state, "audit_emitter", None)
    if factory is None or emitter is None:
        return

    try:
        async with factory() as session:
            await emitter.emit(event, session=session)
            await session.commit()
    except Exception:
        # Audit failures must never bubble into routing / API hot paths.
        logger.warning(
            "audit_emit_failed",
            event_type=getattr(event, "event_type", "unknown"),
            tenant_id=getattr(event, "tenant_id", None),
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Cache-hit sampling — deterministic, fingerprint-keyed.
# ---------------------------------------------------------------------------


def _classifier_audit_sample_rate() -> float:
    """Read the classifier audit sample rate from env, clamped to [0, 1]."""
    raw = os.environ.get("CLASSIFIER_AUDIT_SAMPLE_RATE")
    if raw is None:
        return CACHE_HIT_SAMPLE_RATE
    try:
        rate = float(raw)
    except ValueError:
        logger.warning(
            "classifier_audit_sample_rate_invalid",
            value=raw,
            fallback=CACHE_HIT_SAMPLE_RATE,
        )
        return CACHE_HIT_SAMPLE_RATE
    if rate < 0.0:
        return 0.0
    if rate > 1.0:
        return 1.0
    return rate


def should_sample_cache_hit(fingerprint: str, *, rate: float | None = None) -> bool:
    """Return True iff this fingerprint should be audited.

    Determinism is part of the contract — ``should_sample_cache_hit(fp)``
    returns the same answer every call so a single hot prompt either
    reliably surfaces in audit logs or reliably stays silent.

    Implementation: BLAKE2s 64-bit prefix of the fingerprint string,
    interpreted as a uniform draw in ``[0.0, 1.0)``; emits when below
    ``rate``. Independent of ``random`` state so tests don't need to
    seed.
    """
    if rate is None:
        rate = _classifier_audit_sample_rate()
    if rate <= 0.0:
        return False
    if rate >= 1.0:
        return True
    digest = hashlib.blake2s(fingerprint.encode("utf-8"), digest_size=8).digest()
    bucket = int.from_bytes(digest, "big") / float(1 << 64)
    return bucket < rate


__all__ = [
    "CACHE_HIT_SAMPLE_RATE",
    "build_audit_outbox",
    "emit_event",
    "should_sample_cache_hit",
]
