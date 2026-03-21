"""Tests for bsgateway.tenant.service module.

Uses mocked repository to test business logic without a real database.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from bsgateway.core.security import encrypt_value
from bsgateway.tenant.models import TenantModelCreate, TenantModelUpdate
from bsgateway.tenant.service import TenantService


@pytest.fixture
def encryption_key() -> bytes:
    return os.urandom(32)


@pytest.fixture
def mock_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(mock_repo: AsyncMock, encryption_key: bytes) -> TenantService:
    return TenantService(mock_repo, encryption_key)


def _make_tenant_record(
    tenant_id: UUID | None = None,
    name: str = "Test Tenant",
    slug: str = "test-tenant",
) -> dict:
    now = datetime.now(UTC)
    return {
        "id": tenant_id or uuid4(),
        "name": name,
        "slug": slug,
        "is_active": True,
        "settings": json.dumps({}),
        "created_at": now,
        "updated_at": now,
    }


def _make_model_record(
    tenant_id: UUID | None = None,
    model_id: UUID | None = None,
    model_name: str = "gpt-4o",
    api_key_encrypted: str | None = None,
) -> dict:
    now = datetime.now(UTC)
    return {
        "id": model_id or uuid4(),
        "tenant_id": tenant_id or uuid4(),
        "model_name": model_name,
        "provider": "openai",
        "litellm_model": "openai/gpt-4o",
        "api_key_encrypted": api_key_encrypted,
        "api_base": None,
        "is_active": True,
        "extra_params": json.dumps({}),
        "created_at": now,
        "updated_at": now,
    }


class TestTenantCRUD:
    async def test_create_tenant(self, service: TenantService, mock_repo: AsyncMock):
        record = _make_tenant_record()
        mock_repo.create_tenant.return_value = record

        result = await service.create_tenant("Test Tenant", "test-tenant")
        assert result.name == "Test Tenant"
        assert result.slug == "test-tenant"
        assert result.is_active is True
        mock_repo.create_tenant.assert_called_once()

    async def test_get_tenant(self, service: TenantService, mock_repo: AsyncMock):
        tid = uuid4()
        record = _make_tenant_record(tenant_id=tid)
        mock_repo.get_tenant.return_value = record

        result = await service.get_tenant(tid)
        assert result is not None
        assert result.id == tid

    async def test_get_tenant_not_found(self, service: TenantService, mock_repo: AsyncMock):
        mock_repo.get_tenant.return_value = None
        result = await service.get_tenant(uuid4())
        assert result is None

    async def test_list_tenants(self, service: TenantService, mock_repo: AsyncMock):
        records = [_make_tenant_record() for _ in range(3)]
        mock_repo.list_tenants.return_value = records

        result = await service.list_tenants()
        assert len(result) == 3

    async def test_deactivate_tenant(self, service: TenantService, mock_repo: AsyncMock):
        tid = uuid4()
        await service.deactivate_tenant(tid)
        mock_repo.deactivate_tenant.assert_called_once_with(tid)


class TestApiKeys:
    async def test_create_api_key(self, service: TenantService, mock_repo: AsyncMock):
        tid = uuid4()
        mock_repo.create_api_key.return_value = {
            "id": uuid4(),
            "tenant_id": tid,
            "key_prefix": "bsg_abcd1234",
            "name": "production",
            "scopes": ["read"],
            "is_active": True,
            "expires_at": None,
            "created_at": datetime.now(UTC),
        }

        result = await service.create_api_key(tid, name="production", scopes=["read"])
        assert result.key.startswith("bsg_")
        assert result.name == "production"
        assert result.tenant_id == tid
        mock_repo.create_api_key.assert_called_once()

    async def test_list_api_keys(self, service: TenantService, mock_repo: AsyncMock):
        tid = uuid4()
        mock_repo.list_api_keys.return_value = [
            {
                "id": uuid4(),
                "tenant_id": tid,
                "key_prefix": "bsg_abcd1234",
                "name": "test",
                "scopes": [],
                "is_active": True,
                "expires_at": None,
                "last_used_at": None,
                "created_at": datetime.now(UTC),
            }
        ]
        result = await service.list_api_keys(tid)
        assert len(result) == 1
        assert result[0].key_prefix == "bsg_abcd1234"

    async def test_revoke_api_key(self, service: TenantService, mock_repo: AsyncMock):
        tid = uuid4()
        kid = uuid4()
        await service.revoke_api_key(kid, tid)
        mock_repo.revoke_api_key.assert_called_once_with(kid, tid)


class TestTenantModels:
    async def test_create_model_with_api_key(
        self,
        service: TenantService,
        mock_repo: AsyncMock,
        encryption_key: bytes,
    ):
        tid = uuid4()
        record = _make_model_record(tenant_id=tid, api_key_encrypted="encrypted_value")
        mock_repo.create_model.return_value = record

        data = TenantModelCreate(
            model_name="gpt-4o",
            provider="openai",
            litellm_model="openai/gpt-4o",
            api_key="sk-test-key",
        )
        result = await service.create_model(tid, data)
        assert result.model_name == "gpt-4o"

        # Verify encrypted key was passed (not plaintext)
        call_kwargs = mock_repo.create_model.call_args
        assert call_kwargs.kwargs["api_key_encrypted"] is not None
        assert call_kwargs.kwargs["api_key_encrypted"] != "sk-test-key"

    async def test_create_model_without_api_key(
        self,
        service: TenantService,
        mock_repo: AsyncMock,
    ):
        tid = uuid4()
        record = _make_model_record(tenant_id=tid)
        mock_repo.create_model.return_value = record

        data = TenantModelCreate(
            model_name="my-ollama",
            provider="ollama",
            litellm_model="ollama_chat/llama3",
            api_base="http://localhost:11434",
        )
        result = await service.create_model(tid, data)
        assert result.model_name == "gpt-4o"  # from mock record

        call_kwargs = mock_repo.create_model.call_args
        assert call_kwargs.kwargs["api_key_encrypted"] is None

    async def test_get_model_api_key_decrypts(
        self,
        service: TenantService,
        mock_repo: AsyncMock,
        encryption_key: bytes,
    ):
        tid = uuid4()
        mid = uuid4()
        encrypted = encrypt_value("sk-real-key", encryption_key)
        record = _make_model_record(
            tenant_id=tid,
            model_id=mid,
            api_key_encrypted=encrypted,
        )
        mock_repo.get_model.return_value = record

        result = await service.get_model_api_key(mid, tid)
        assert result == "sk-real-key"

    async def test_get_model_api_key_none_when_no_key(
        self,
        service: TenantService,
        mock_repo: AsyncMock,
    ):
        record = _make_model_record(api_key_encrypted=None)
        mock_repo.get_model.return_value = record

        result = await service.get_model_api_key(uuid4(), uuid4())
        assert result is None

    async def test_update_model(
        self,
        service: TenantService,
        mock_repo: AsyncMock,
    ):
        tid = uuid4()
        mid = uuid4()
        existing = _make_model_record(tenant_id=tid, model_id=mid)
        mock_repo.get_model.return_value = existing
        mock_repo.update_model.return_value = {
            **existing,
            "model_name": "gpt-4o-updated",
        }

        data = TenantModelUpdate(model_name="gpt-4o-updated")
        result = await service.update_model(mid, tid, data)
        assert result is not None
        assert result.model_name == "gpt-4o-updated"

    async def test_create_model_no_encryption_key_rejects(
        self,
        mock_repo: AsyncMock,
    ):
        """Providing api_key without ENCRYPTION_KEY must raise ValueError."""
        svc_no_key = TenantService(mock_repo, encryption_key=b"")
        data = TenantModelCreate(
            model_name="gpt-4o",
            provider="openai",
            litellm_model="openai/gpt-4o",
            api_key="sk-plaintext",
        )
        with pytest.raises(ValueError, match="Unable to store API keys securely"):
            await svc_no_key.create_model(uuid4(), data)

    async def test_update_model_no_encryption_key_rejects(
        self,
        mock_repo: AsyncMock,
    ):
        """Updating api_key without ENCRYPTION_KEY must raise ValueError."""
        svc_no_key = TenantService(mock_repo, encryption_key=b"")
        tid = uuid4()
        mid = uuid4()
        existing = _make_model_record(tenant_id=tid, model_id=mid)
        mock_repo.get_model.return_value = existing

        data = TenantModelUpdate(api_key="sk-new-plaintext")
        with pytest.raises(ValueError, match="Unable to store API keys securely"):
            await svc_no_key.update_model(mid, tid, data)

    async def test_delete_model(self, service: TenantService, mock_repo: AsyncMock):
        tid = uuid4()
        mid = uuid4()
        await service.delete_model(mid, tid)
        mock_repo.delete_model.assert_called_once_with(mid, tid)
