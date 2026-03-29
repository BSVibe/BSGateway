"""Pydantic schemas for MCP tool request/response payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from bsgateway.rules.schemas import ConditionValue, ValidConditionType, ValidOperator

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class MCPCondition(BaseModel):
    condition_type: ValidConditionType
    field: str = Field(..., min_length=1)
    operator: ValidOperator = "eq"
    value: ConditionValue = None
    negate: bool = False

    @model_validator(mode="after")
    def validate_between_value(self) -> MCPCondition:
        if self.operator == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("'between' operator requires a 2-element list")
        return self


class MCPCreateRule(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    conditions: list[MCPCondition] = Field(default_factory=list)
    target_model: str = Field(..., min_length=1)
    priority: int = Field(default=0, ge=0)
    is_default: bool = False


class MCPUpdateRule(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    conditions: list[MCPCondition] | None = None
    target_model: str | None = Field(None, min_length=1)
    priority: int | None = Field(None, ge=0)
    is_default: bool | None = None


class MCPRuleResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    priority: int
    is_active: bool
    is_default: bool
    target_model: str
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class MCPRegisterModel(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    provider: str = Field(..., min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class MCPModelResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    model_name: str
    provider: str
    litellm_model: str
    api_base: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Simulate routing
# ---------------------------------------------------------------------------


class MCPSimulateRequest(BaseModel):
    model_hint: str = "auto"
    text: str = Field(..., min_length=1)


class MCPSimulateResponse(BaseModel):
    matched_rule: dict[str, Any] | None = None
    target_model: str | None = None
    evaluation_trace: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cost / Usage
# ---------------------------------------------------------------------------


class MCPCostReport(BaseModel):
    period: str
    total_requests: int
    total_tokens: int
    by_model: dict[str, dict[str, int]] = Field(default_factory=dict)


class MCPUsageStats(BaseModel):
    total_requests: int
    total_tokens: int
    by_model: dict[str, dict[str, int]] = Field(default_factory=dict)
    by_rule: dict[str, int] = Field(default_factory=dict)
