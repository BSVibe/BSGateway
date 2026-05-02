from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from bsgateway.routing.classifiers.base import (
    extract_all_text,
    extract_system_prompt,
    extract_user_text,
)
from bsgateway.routing.constants import WORDS_TO_TOKENS_RATIO

# CJK Unicode ranges for language detection
_CJK_RE = re.compile(r"[\u3000-\u9fff\uac00-\ud7af\u3040-\u309f\u30a0-\u30ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af\u3131-\u3163]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_CJK_IDEO_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[a-zA-Z]")


def _detect_language(text: str) -> str | None:
    """Simple heuristic language detection.

    Returns ISO 639-1 code or None if undetermined.
    Only detects ko, ja, zh, en for now — enough for routing decisions.
    Non-CJK/non-Latin scripts (Arabic, Cyrillic, etc.) return None.
    """
    if not text:
        return None
    # Count script-specific characters
    hangul = len(_HANGUL_RE.findall(text))
    kana = len(_KANA_RE.findall(text))
    cjk_ideo = len(_CJK_IDEO_RE.findall(text))
    total_cjk = hangul + kana + cjk_ideo
    if total_cjk == 0:
        # Check if text is predominantly Latin before assuming English
        latin = len(_LATIN_RE.findall(text))
        if latin / max(len(text), 1) > 0.3:
            return "en"
        return None
    if hangul > kana and hangul > cjk_ideo:
        return "ko"
    if kana > hangul:
        return "ja"
    if cjk_ideo > 0:
        return "zh"
    return None


def _estimate_tokens(text: str) -> int:
    """Rough token estimate that handles both CJK and Latin text.

    CJK characters are roughly 1 token each; Latin words ~1.3 tokens.
    """
    if not text:
        return 0
    cjk_chars = len(_CJK_RE.findall(text))
    # Remove CJK chars to count remaining word-based tokens
    non_cjk = _CJK_RE.sub("", text)
    word_tokens = len(non_cjk.split())
    return int((word_tokens + cjk_chars) * WORDS_TO_TOKENS_RATIO)


@dataclass
class RuleCondition:
    """A single condition within a routing rule."""

    condition_type: str  # text_pattern, token_count, message, tool, intent, model_requested
    field: str
    operator: str  # eq, contains, regex, gt, lt, gte, lte, between, in, not_in
    value: Any
    negate: bool = False


@dataclass
class RoutingRule:
    """A routing rule with priority and conditions."""

    id: str
    tenant_id: str
    name: str
    priority: int
    is_active: bool
    is_default: bool
    target_model: str
    conditions: list[RuleCondition] = field(default_factory=list)


@dataclass
class TenantModel:
    """A model registered by a tenant."""

    model_name: str
    provider: str
    litellm_model: str
    api_key_encrypted: str | None = None
    api_base: str | None = None
    extra_params: dict = field(default_factory=dict)


@dataclass
class TenantConfig:
    """Full tenant configuration loaded from DB cache."""

    tenant_id: str
    slug: str
    models: dict[str, TenantModel]
    rules: list[RoutingRule]  # sorted by priority ascending
    settings: dict = field(default_factory=dict)
    embedding_settings: Any = None  # bsgateway.embedding.settings.EmbeddingSettings | None
    intent_definitions: list = field(default_factory=list)  # list[IntentDefinition]


@dataclass
class RuleMatch:
    """Result of rule evaluation."""

    rule: RoutingRule
    target_model: str
    trace: list[dict] | None = None


@dataclass
class EvaluationContext:
    """Pre-extracted fields from a request, evaluated once per request."""

    user_text: str
    system_prompt: str
    all_text: str
    estimated_tokens: int
    conversation_turns: int
    has_code_blocks: bool
    has_error_trace: bool
    tool_count: int
    tool_names: list[str]
    original_model: str
    classified_intent: str | None = None
    detected_language: str | None = None
    hour_of_day: int | None = None
    day_of_week: str | None = None
    daily_cost: float | None = None
    monthly_cost: float | None = None
    request_count_hourly: int | None = None

    @classmethod
    def from_request(cls, data: dict) -> EvaluationContext:
        messages = data.get("messages", [])
        user_text = extract_user_text(messages)
        all_text = extract_all_text(messages)
        system_prompt = extract_system_prompt(data)

        tools = data.get("tools", [])
        tool_names = []
        for t in tools:
            fn = t.get("function", {})
            if fn.get("name"):
                tool_names.append(fn["name"])

        from datetime import datetime

        now = datetime.now(UTC)
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

        return cls(
            user_text=user_text,
            system_prompt=system_prompt,
            all_text=all_text,
            estimated_tokens=_estimate_tokens(all_text),
            conversation_turns=len([m for m in messages if m.get("role") == "user"]),
            has_code_blocks=bool(re.search(r"```", all_text)),
            has_error_trace=any(p in all_text for p in ["Traceback", "Error:", "Exception"]),
            tool_count=len(tools),
            tool_names=tool_names,
            original_model=data.get("model", ""),
            detected_language=_detect_language(user_text),
            hour_of_day=now.hour,
            day_of_week=day_names[now.weekday()],
        )
