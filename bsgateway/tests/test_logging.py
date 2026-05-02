from __future__ import annotations

import io
import json

import structlog
from bsvibe_core import configure_logging

from bsgateway.core.logging import logger, setup_logging


def test_setup_logging_runs_without_error() -> None:
    """setup_logging() should configure structlog without raising."""
    setup_logging()


def test_structlog_produces_json_after_setup() -> None:
    """After setup, binding context and emitting a message should produce
    valid JSON containing the bound fields and the BSVibe ``service`` tag.

    Phase A Batch 5: BSGateway uses :func:`bsvibe_core.configure_logging`,
    which emits via ``PrintLoggerFactory`` (stdout). We capture
    deterministically via the ``stream=`` kwarg instead of relying on
    pytest capfd, which interleaves unreliably with PrintLoggerFactory.
    """
    sink = io.StringIO()
    # Re-configure with our captured stream + same service tag as setup_logging().
    configure_logging(level="info", json_output=True, service_name="bsgateway", stream=sink)

    bound = structlog.get_logger("bsgateway").bind(request_id="test-123")
    bound.info("health_check", status="ok")

    output = sink.getvalue()
    assert output, "Expected log output on the captured stream"

    line = output.strip().splitlines()[-1]
    data = json.loads(line)
    assert data["request_id"] == "test-123"
    assert data["status"] == "ok"
    assert data["event"] == "health_check"
    assert data["service"] == "bsgateway"

    # Restore the default config so subsequent tests start from a known state.
    setup_logging()
    # Reference the package-level logger to keep the import non-dead.
    assert logger is not None
