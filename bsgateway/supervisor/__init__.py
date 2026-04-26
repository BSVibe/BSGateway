"""BSGateway → BSupervisor integration.

Phase 0 P0.7 — BSGateway absorbs the LLM run.pre/run.post precheck flow
that BSNexus used to drive directly. The components in this package:

- :class:`ServiceTokenMinter` — mints short-lived service JWTs by calling
  BSVibe-Auth's ``POST /api/service-tokens/issue`` with a long-lived
  service-account credential.
- :class:`BSupervisorClient` — calls ``POST /api/events`` on BSupervisor
  for ``run.pre`` (sync, fail-open by default) and ``run.post``
  (fire-and-forget). Mirrors the schema used by BSNexus's old
  ``audit_sink`` so the cut-over is observably equivalent.
"""

from __future__ import annotations

from .client import AuditResult, BSupervisorClient, RunMetadata
from .service_token import ServiceTokenMinter, ServiceTokenMinterError

__all__ = [
    "AuditResult",
    "BSupervisorClient",
    "RunMetadata",
    "ServiceTokenMinter",
    "ServiceTokenMinterError",
]
