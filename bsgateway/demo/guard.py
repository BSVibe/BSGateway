"""Re-export demo LLM guard from the shared bsvibe-demo package."""

from __future__ import annotations

from bsvibe_demo import (
    DEMO_MOCK_RESPONSE,
    DemoLLMBlockedError,
    enforce_demo_llm_mock,
    is_demo_mode,
)

__all__ = [
    "DEMO_MOCK_RESPONSE",
    "DemoLLMBlockedError",
    "enforce_demo_llm_mock",
    "is_demo_mode",
]
