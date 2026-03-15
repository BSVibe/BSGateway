from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Rule Conditions
# ---------------------------------------------------------------------------


ConditionValue = str | int | float | bool | list | None


class ConditionSchema(BaseModel):
    condition_type: str = Field(..., min_length=1)
    field: str = Field(..., min_length=1)
    operator: str = Field(default="eq")
    value: ConditionValue = Field(...)
    negate: bool = False

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: ConditionValue) -> ConditionValue:
        if isinstance(v, str) and len(v) > 1000:
            raise ValueError("value string too long (max 1000)")
        if isinstance(v, list) and len(v) > 100:
            raise ValueError("value list too long (max 100)")
        return v


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class RuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    priority: int = Field(..., ge=0)
    is_default: bool = False
    target_model: str = Field(..., min_length=1)
    conditions: list[ConditionSchema] = Field(default_factory=list)


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
    description: str = ""
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    examples: list[str] = Field(default_factory=list)


class IntentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
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
    text: str = Field(..., min_length=1)


class ExampleResponse(BaseModel):
    id: UUID
    intent_id: UUID
    text: str
    created_at: datetime
