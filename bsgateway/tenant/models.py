from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9-]*$")
    settings: dict = Field(default_factory=dict)


class TenantUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    slug: str | None = Field(None, min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9-]*$")
    settings: dict | None = None


class TenantResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    is_active: bool
    settings: dict
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------


class ApiKeyCreate(BaseModel):
    name: str = Field(default="", max_length=255)
    scopes: list[str] = Field(default_factory=list)


class ApiKeyCreatedResponse(BaseModel):
    """Returned only once at creation time with the plaintext key."""

    id: UUID
    tenant_id: UUID
    key: str  # plaintext, shown once
    key_prefix: str
    name: str
    scopes: list[str]
    created_at: datetime


class ApiKeyResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    key_prefix: str
    name: str
    scopes: list[str]
    is_active: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Tenant Models
# ---------------------------------------------------------------------------


class TenantModelCreate(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=255)
    provider: str = Field(..., min_length=1, max_length=100)
    litellm_model: str = Field(..., min_length=1, max_length=255)
    api_key: str | None = None  # plaintext, encrypted before storage
    api_base: str | None = None
    extra_params: dict = Field(default_factory=dict)


class TenantModelUpdate(BaseModel):
    model_name: str | None = Field(None, min_length=1, max_length=255)
    provider: str | None = Field(None, min_length=1, max_length=100)
    litellm_model: str | None = Field(None, min_length=1, max_length=255)
    api_key: str | None = None
    api_base: str | None = None
    extra_params: dict | None = None


class TenantModelResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    model_name: str
    provider: str
    litellm_model: str
    api_base: str | None
    is_active: bool
    extra_params: dict
    created_at: datetime
    updated_at: datetime
