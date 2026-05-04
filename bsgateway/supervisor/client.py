"""BSGateway → BSupervisor /api/events client.

Phase 0 P0.7 architectural shift (Lockin §2 #1): BSGateway absorbs the
``run.pre`` (preflight) and ``run.post`` (post-run) calls that BSNexus
used to fire from ``audit_sink.py``. Behaviour parity is preserved:

* ``run_pre`` blocks on the supervisor with a 200ms budget by default,
  and is fail-open: a timeout / network error returns ``degraded=True,
  blocked=False`` so the LLM call still proceeds. ``fail_mode="closed"``
  flips that for environments that require BSupervisor to be available.
* ``run_post`` is fire-and-forget — callers schedule it via
  ``asyncio.create_task`` and never await its result. Internally we
  silence all exceptions because there is no UX path that benefits from
  surfacing a post-run audit failure.

The wire shape matches BSupervisor PR #4's ``EventRequest``:

```
{
  "agent_id": "<agent_name|service:bsgateway>",
  "source": "bsgateway",
  "event_type": "run.pre" | "run.post",
  "action": "llm.dispatch" | "llm.complete",
  "target": "<resolved_model>",
  "metadata": { tenant_id, run_id, project_id, request_id, ... }
}
```

The free-form ``metadata`` dict is what consumers (BSupervisor incident
tracker, downstream cost rollups) read for run-correlation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    from bsvibe_authz import ServiceTokenMinter

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AuditResult:
    """Outcome of a pre-run audit call to BSupervisor."""

    blocked: bool
    reason: str | None = None
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """Per-run identifiers / context BSGateway forwards to BSupervisor.

    Mirrors the metadata BSNexus used to send via ``audit_sink.preflight``.
    Required identifiers are explicit fields; everything else lands on the
    free-form ``extras`` dict so BSGateway never has to be the schema gate.
    """

    tenant_id: str
    run_id: str
    project_id: str | None = None
    request_id: str | None = None
    parent_run_id: str | None = None
    composition_id: str | None = None
    agent_name: str | None = None
    cost_estimate_cents: int | None = None
    model: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Flatten for transport — drop ``None`` and merge ``extras``."""
        out: dict[str, Any] = {k: v for k, v in asdict(self).items() if k != "extras"}
        # Drop None — keeps payload terse and contracts forward-compatible.
        out = {k: v for k, v in out.items() if v is not None}
        out.update(self.extras)
        return out

    @classmethod
    def from_request_metadata(
        cls,
        metadata: dict[str, Any],
        *,
        resolved_model: str | None = None,
    ) -> RunMetadata | None:
        """Build a ``RunMetadata`` from LiteLLM ``data["metadata"]``.

        Returns ``None`` when ``run_id`` is missing — the caller should
        skip BSupervisor in that case (proxy-direct traffic with no
        BSNexus run to correlate against).
        """
        run_id = metadata.get("run_id")
        if not run_id:
            return None
        tenant_id = metadata.get("tenant_id")
        if not tenant_id:
            return None

        # Pull extras: anything not part of the named fields.
        named = {
            "tenant_id",
            "run_id",
            "project_id",
            "request_id",
            "parent_run_id",
            "composition_id",
            "agent_name",
            "cost_estimate_cents",
            "model",
        }
        extras = {k: v for k, v in metadata.items() if k not in named}

        cost_raw = metadata.get("cost_estimate_cents")
        cost_cents: int | None
        if cost_raw is None:
            cost_cents = None
        else:
            try:
                cost_cents = int(cost_raw)
            except (TypeError, ValueError):
                cost_cents = None

        return cls(
            tenant_id=str(tenant_id),
            run_id=str(run_id),
            project_id=_str_or_none(metadata.get("project_id")),
            request_id=_str_or_none(metadata.get("request_id")),
            parent_run_id=_str_or_none(metadata.get("parent_run_id")),
            composition_id=_str_or_none(metadata.get("composition_id")),
            agent_name=_str_or_none(metadata.get("agent_name")),
            cost_estimate_cents=cost_cents,
            model=_str_or_none(metadata.get("model") or resolved_model),
            extras=extras,
        )


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


class BSupervisorClient:
    """Thin async client over BSupervisor's ``POST /api/events`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        token_minter: ServiceTokenMinter,
        timeout_ms: int = 200,
        fail_mode: str = "open",
    ) -> None:
        if fail_mode not in ("open", "closed"):
            raise ValueError(f"fail_mode must be 'open' or 'closed', got {fail_mode!r}")
        self._base_url = base_url.rstrip("/")
        self.token_minter = token_minter
        self._timeout_s = timeout_ms / 1000.0
        self._fail_mode = fail_mode

    async def run_pre(self, meta: RunMetadata) -> AuditResult:
        """Synchronously call BSupervisor for a pre-flight verdict."""
        payload = self._build_payload(meta, event_type="run.pre", action="llm.dispatch")
        try:
            body = await self._post(payload)
        except httpx.TimeoutException:
            logger.warning(
                "bsupervisor_preflight_timeout",
                run_id=meta.run_id,
                tenant_id=meta.tenant_id,
            )
            return self._fail_result("preflight timeout")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                # Service token was rejected — drop it so the next call
                # mints fresh. Don't retry inline, the 200ms budget is
                # the user's request budget.
                self.token_minter.invalidate()
            logger.warning(
                "bsupervisor_preflight_http_error",
                status=status,
                run_id=meta.run_id,
            )
            return self._fail_result(f"preflight http {status}")
        except (httpx.RequestError, Exception) as exc:
            logger.warning(
                "bsupervisor_preflight_failed",
                run_id=meta.run_id,
                error=str(exc),
            )
            return self._fail_result(f"preflight error: {exc}")

        allowed = bool(body.get("allowed", True))
        return AuditResult(
            blocked=not allowed,
            reason=body.get("reason"),
            degraded=False,
        )

    async def run_post(
        self,
        meta: RunMetadata,
        *,
        status: str,
        actual_cost_cents: int | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        """Fire-and-forget post-run report. Never raises."""
        post_meta = {
            "status": status,
            "actual_cost_cents": actual_cost_cents,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "duration_ms": duration_ms,
            "error": error,
        }
        payload = self._build_payload(
            meta,
            event_type="run.post",
            action="llm.complete",
            extra_metadata={k: v for k, v in post_meta.items() if v is not None},
        )
        try:
            await self._post(payload)
        except Exception as exc:
            logger.warning(
                "bsupervisor_post_failed",
                run_id=meta.run_id,
                error=str(exc),
            )

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        token = await self.token_minter.get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "BSGateway/0.5 (+https://api-gateway.bsvibe.dev)",
        }
        async with httpx.AsyncClient(timeout=self._timeout_s) as cli:
            resp = await cli.post(
                url=f"{self._base_url}/api/events",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json() or {}

    def _build_payload(
        self,
        meta: RunMetadata,
        *,
        event_type: str,
        action: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compose the BSupervisor EventRequest body.

        - ``agent_id`` falls back to the BSGateway service identity so the
          ingestion endpoint always has a non-empty value.
        - ``target`` carries the resolved model so dashboards can group.
        - ``metadata`` is the full RunMetadata + post-run extras.
        """
        agent_id = meta.agent_name or "service:bsgateway"
        target = meta.model or "unknown"
        full_metadata = meta.to_dict()
        if extra_metadata:
            full_metadata.update(extra_metadata)
        return {
            "agent_id": agent_id,
            "source": "bsgateway",
            "event_type": event_type,
            "action": action,
            "target": target,
            "metadata": full_metadata,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def _fail_result(self, reason: str) -> AuditResult:
        blocked = self._fail_mode == "closed"
        return AuditResult(blocked=blocked, reason=reason, degraded=True)
