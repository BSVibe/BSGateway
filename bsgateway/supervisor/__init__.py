"""BSGateway → BSupervisor integration.

The minter (now backed by OAuth2 client_credentials against BSVibe-Auth's
``POST /api/oauth/token``) lives in :mod:`bsvibe_authz`. This package wires
it into :class:`BSupervisorClient`, which calls ``POST /api/events`` on
BSupervisor for ``run.pre`` (sync, fail-open by default) and ``run.post``
(fire-and-forget).
"""

from __future__ import annotations

from bsvibe_authz import ServiceTokenMinter, ServiceTokenMinterError

from .client import AuditResult, BSupervisorClient, RunMetadata

__all__ = [
    "AuditResult",
    "BSupervisorClient",
    "RunMetadata",
    "ServiceTokenMinter",
    "ServiceTokenMinterError",
]
