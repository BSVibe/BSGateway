from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PresetSummary(BaseModel):
    name: str
    description: str
    intent_count: int
    rule_count: int


class PresetApplyResponse(BaseModel):
    preset_name: str
    rules_created: int
    intents_created: int
    examples_created: int


class FeedbackCreate(BaseModel):
    routing_id: str = Field(..., min_length=1)
    rating: int = Field(..., ge=1, le=5)
    comment: str = ""


class FeedbackResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    routing_id: str
    rating: int
    comment: str
    created_at: datetime
