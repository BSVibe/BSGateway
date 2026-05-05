"""Tests for the BSGateway demo guard.

The demo guard prevents real LLM provider calls when BSVIBE_DEMO_MODE=true.
Real LLM calls would burn paid API quota on demo traffic — the guard
forces LiteLLM to return ``mock_response`` instead.
"""

from __future__ import annotations

import pytest

from bsgateway.demo.guard import (
    DemoLLMBlockedError,
    enforce_demo_llm_mock,
    is_demo_mode,
)


class TestIsDemoMode:
    def test_returns_true_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BSVIBE_DEMO_MODE", "true")
        assert is_demo_mode() is True

    def test_returns_false_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BSVIBE_DEMO_MODE", raising=False)
        assert is_demo_mode() is False

    def test_returns_false_for_falsy_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for v in ("false", "0", "no", ""):
            monkeypatch.setenv("BSVIBE_DEMO_MODE", v)
            assert is_demo_mode() is False, f"expected False for {v!r}"


class TestEnforceDemoLLMMock:
    def test_passthrough_when_not_demo_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BSVIBE_DEMO_MODE", raising=False)
        kwargs: dict[str, object] = {"model": "gpt-4", "messages": []}
        enforce_demo_llm_mock(kwargs)
        assert "mock_response" not in kwargs

    def test_injects_mock_response_when_demo_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BSVIBE_DEMO_MODE", "true")
        kwargs: dict[str, object] = {"model": "gpt-4", "messages": []}
        enforce_demo_llm_mock(kwargs)
        assert kwargs["mock_response"]
        assert isinstance(kwargs["mock_response"], str)

    def test_strips_real_api_key_when_demo_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BSVIBE_DEMO_MODE", "true")
        kwargs = {"model": "gpt-4", "api_key": "sk-real-key", "messages": []}
        enforce_demo_llm_mock(kwargs)
        # api_key must be removed so demo backend can't accidentally
        # reach a paid provider even if mock_response is bypassed
        assert "api_key" not in kwargs

    def test_raises_when_attempt_to_pass_paid_provider_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If something tries to set api_base to a known paid endpoint while
        # in demo mode, the guard raises rather than silently allowing.
        monkeypatch.setenv("BSVIBE_DEMO_MODE", "true")
        kwargs = {
            "model": "gpt-4",
            "api_base": "https://api.openai.com/v1",
            "messages": [],
        }
        with pytest.raises(DemoLLMBlockedError):
            enforce_demo_llm_mock(kwargs, strict=True)
