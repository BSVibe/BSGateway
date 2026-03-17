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

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Acme Corp",
                "slug": "acme-corp",
                "settings": {
                    "rate_limit": {"requests_per_minute": 60},
                },
            },
        },
    }


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

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "Acme Corp",
                "slug": "acme-corp",
                "is_active": True,
                "settings": {
                    "rate_limit": {"requests_per_minute": 60},
                },
                "created_at": "2026-01-15T09:00:00Z",
                "updated_at": "2026-01-15T09:00:00Z",
            },
        },
    }


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------


class ApiKeyCreate(BaseModel):
    name: str = Field(default="", max_length=255)
    scopes: list[str] = Field(default_factory=list)

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Production Key",
                "scopes": ["chat", "admin"],
            },
        },
    }


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
    provider: str | None = Field(None, max_length=100)
    litellm_model: str = Field(..., min_length=1, max_length=255)
    api_key: str | None = None  # plaintext, encrypted before storage
    api_base: str | None = None
    extra_params: dict = Field(default_factory=dict)

    model_config = {
        "json_schema_extra": {
            "example": {
                "model_name": "gpt-4o",
                "litellm_model": "openai/gpt-4o",
                "api_key": "sk-...",
                "api_base": None,
                "extra_params": {},
            },
        },
    }


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

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "tenant_id": "660e8400-e29b-41d4-a716-446655440000",
                "model_name": "gpt-4o",
                "provider": "openai",
                "litellm_model": "openai/gpt-4o",
                "api_base": None,
                "is_active": True,
                "extra_params": {},
                "created_at": "2026-01-15T09:00:00Z",
                "updated_at": "2026-01-15T09:00:00Z",
            },
        },
    }
