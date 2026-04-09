from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Rule Conditions
# ---------------------------------------------------------------------------

ValidOperator = Literal[
    "eq",
    "contains",
    "regex",
    "gt",
    "lt",
    "gte",
    "lte",
    "between",
    "in",
    "not_in",
]

ValidConditionType = Literal[
    "text_pattern",
    "token_count",
    "message",
    "tool",
    "intent",
    "model_requested",
    "language",
    "time",
    "budget",
]

ConditionValue = str | int | float | bool | list | None


class ConditionSchema(BaseModel):
    condition_type: ValidConditionType = Field(...)
    field: str = Field(..., min_length=1)
    operator: ValidOperator = Field(default="eq")
    value: ConditionValue = Field(...)
    negate: bool = False

    model_config = {
        "json_schema_extra": {
            "example": {
                "condition_type": "token_count",
                "field": "estimated_tokens",
                "operator": "gt",
                "value": 500,
                "negate": False,
            },
        },
    }

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: ConditionValue) -> ConditionValue:
        if isinstance(v, str) and len(v) > 1000:
            raise ValueError("value string too long (max 1000)")
        if isinstance(v, list) and len(v) > 100:
            raise ValueError("value list too long (max 100)")
        return v

    @model_validator(mode="after")
    def validate_between_value(self) -> ConditionSchema:
        if self.operator == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("'between' operator requires a 2-element list")
        return self


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class RuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    priority: int = Field(..., ge=0)
    is_default: bool = False
    target_model: str = Field(..., min_length=1)
    conditions: list[ConditionSchema] = Field(default_factory=list)

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Route complex to GPT-4",
                "priority": 10,
                "is_default": False,
                "target_model": "gpt-4o",
                "conditions": [
                    {
                        "condition_type": "token_count",
                        "field": "estimated_tokens",
                        "operator": "gt",
                        "value": 500,
                        "negate": False,
                    },
                ],
            },
        },
    }


class RuleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    priority: int | None = Field(None, ge=0)
    is_default: bool | None = None
    target_model: str | None = Field(None, min_length=1)
    conditions: list[ConditionSchema] | None = None


class ConditionResponse(BaseModel):
    id: UUID
    condition_type: str
    field: str
    operator: str
    value: ConditionValue
    negate: bool


class RuleResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    priority: int
    is_active: bool
    is_default: bool
    target_model: str
    conditions: list[ConditionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ReorderRequest(BaseModel):
    priorities: dict[UUID, int]


class RuleTestRequest(BaseModel):
    messages: list[dict]
    model: str = "auto"

    model_config = {
        "json_schema_extra": {
            "example": {
                "messages": [
                    {
                        "role": "user",
                        "content": "Explain quantum computing in detail",
                    },
                ],
                "model": "auto",
            },
        },
    }


class RuleTestResponse(BaseModel):
    matched_rule: dict | None
    target_model: str | None
    evaluation_trace: list[dict]
    context: dict


# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------


class IntentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    examples: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("examples")
    @classmethod
    def validate_example_lengths(cls, v: list[str]) -> list[str]:
        for ex in v:
            if len(ex) > 5000:
                raise ValueError("example text exceeds 5000 characters")
        return v


class IntentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    threshold: float | None = Field(None, ge=0.0, le=1.0)


class IntentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str
    threshold: float
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ExampleCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


class ExampleResponse(BaseModel):
    id: UUID
    intent_id: UUID
    text: str
    created_at: datetime


class ReembedResponse(BaseModel):
    """Result of a re-embedding backfill run."""

    refreshed: int = Field(..., ge=0, description="Number of examples successfully re-embedded")
    failed: int = Field(..., ge=0, description="Number of examples that failed to embed")
    model: str = Field(..., description="Embedding model used for the backfill")
