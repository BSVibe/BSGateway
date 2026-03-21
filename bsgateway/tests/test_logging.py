from __future__ import annotations

import json
import logging

import pytest

from bsgateway.core.logging import logger, setup_logging


def test_setup_logging_runs_without_error() -> None:
    """setup_logging() should configure structlog without raising."""
    setup_logging()


def test_structlog_produces_json_after_setup(capfd: pytest.CaptureFixture[str]) -> None:
    """After setup, binding context and emitting a message should produce
    valid JSON containing the bound fields."""
    setup_logging()

    # Ensure the stdlib root logger has a stderr handler so output is captured.
    root = logging.getLogger()
    handler = logging.StreamHandler()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    try:
        log = logger.bind(request_id="test-123")
        log.info("health_check", status="ok")

        captured = capfd.readouterr()
        output = captured.err
        assert output, "Expected log output on stderr"

        # The last line should be valid JSON from structlog's JSONRenderer.
        line = output.strip().splitlines()[-1]
        data = json.loads(line)
        assert data["request_id"] == "test-123"
        assert data["status"] == "ok"
        assert data["event"] == "health_check"
    finally:
        root.removeHandler(handler)
