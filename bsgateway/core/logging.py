"""Logging — thin wrapper over :func:`bsvibe_core.configure_logging`.

Phase A Batch 5: BSGateway delegates logging configuration to
``bsvibe-core`` so all four products share one structlog pipeline (JSON
renderer + ``contextvars`` merge + service tag). The local
:func:`setup_logging` shim is preserved for backward compatibility with
the existing import path used by tests.

Migration ledger:
* Direct ``structlog.configure`` is replaced by ``configure_logging``.
* The exported ``logger`` keeps its top-level ``"bsgateway"`` name for
  callers that import it (the rest of the codebase imports
  ``structlog.get_logger(__name__)`` so they self-namespace).
"""

from __future__ import annotations

import structlog
from bsvibe_core import configure_logging

_SERVICE_NAME = "bsgateway"


def setup_logging() -> None:
    """Configure structlog with the BSVibe baseline pipeline."""
    configure_logging(level="info", json_output=True, service_name=_SERVICE_NAME)


logger = structlog.get_logger(_SERVICE_NAME)
