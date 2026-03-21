from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Human-readable tenant name")
    slug: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9-]*$",
        description="URL-friendly identifier (lowercase, hyphens allowed)",
    )
    settings: dict = Field(
        default_factory=dict, description="JSON settings (e.g., rate_limit config)"
    )

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
    id: UUID = Field(description="Unique tenant identifier")
    name: str = Field(description="Human-readable tenant name")
    slug: str = Field(description="URL-friendly identifier")
    is_active: bool = Field(description="Whether tenant is active or deactivated")
    settings: dict = Field(description="Tenant configuration")
    created_at: datetime = Field(description="Timestamp when tenant was created")
    updated_at: datetime = Field(description="Timestamp of last update")

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
    name: str = Field(default="", max_length=255, description="Optional name for this key")
    scopes: list[str] = Field(
        default_factory=list,
        description="Permission scopes (e.g., 'chat', 'admin')",
    )

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
    model_name: str = Field(
        ..., min_length=1, max_length=255, description="Alias for this model (e.g., 'gpt-4o')"
    )
    litellm_model: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="LiteLLM model ID in format provider/model (e.g., 'openai/gpt-4o')",
    )
    api_key: str | None = Field(
        None,
        max_length=4096,
        description="API key for the model provider (optional, encrypted at rest)",
    )
    api_base: str | None = Field(
        None, description="Custom API base URL for non-standard endpoints (optional)"
    )
    extra_params: dict = Field(default_factory=dict, description="Additional LiteLLM parameters")

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
    litellm_model: str | None = Field(None, min_length=1, max_length=255)
    api_key: str | None = None
    api_base: str | None = None
    extra_params: dict | None = None


class TenantModelResponse(BaseModel):
    id: UUID = Field(description="Unique model identifier")
    tenant_id: UUID = Field(description="Tenant this model belongs to")
    model_name: str = Field(description="Model alias")
    provider: str = Field(description="Provider (auto-derived from litellm_model)")
    litellm_model: str = Field(description="LiteLLM model ID (provider/model)")
    api_base: str | None = Field(None, description="Custom API endpoint (if any)")
    is_active: bool = Field(description="Whether model is available for routing")
    extra_params: dict = Field(description="Additional LiteLLM parameters")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")

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
