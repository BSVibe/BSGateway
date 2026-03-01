from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ClassificationResult:
    """Result of a complexity classification."""

    tier: str  # "simple" | "medium" | "complex"
    strategy: str  # "static" | "llm" | "ml"
    score: int | None = None  # 0-100 (static only)
    confidence: float | None = None  # 0.0-1.0 (ml only)


@runtime_checkable
class ClassifierProtocol(Protocol):
    async def classify(self, data: dict) -> ClassificationResult: ...


def extract_all_text(messages: list) -> str:
    """Extract all text content from messages (all roles)."""
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return " ".join(parts)


def extract_user_text(messages: list) -> str:
    """Extract text content from user messages only."""
    parts: list[str] = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return " ".join(parts)


def extract_system_prompt(data: dict) -> str:
    """Extract system prompt from request data (Anthropic or OpenAI format)."""
    system = data.get("system", "")
    if system:
        return system
    for msg in data.get("messages", []):
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
    return ""
