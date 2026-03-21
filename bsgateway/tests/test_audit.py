"""Tests for the audit logging system."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.audit.repository import AuditRepository
from bsgateway.audit.service import AuditService
from bsgateway.core.security import hash_api_key
from bsgateway.tests.conftest import make_mock_pool

SUPERADMIN_KEY = "test-superadmin-key"
ENCRYPTION_KEY_HEX = os.urandom(32).hex()
TENANT_ID = uuid4()


@pytest.fixture
def mock_pool():
    pool, _conn = make_mock_pool()
    return pool


@pytest.fixture
def app(mock_pool: AsyncMock):
    app = create_app()
    app.state.db_pool = mock_pool
    app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    app.state.superadmin_key_hash = hash_api_key(SUPERADMIN_KEY)
    app.state.redis = None
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_headers() -> dict:
    return {"Authorization": f"Bearer {SUPERADMIN_KEY}"}


class TestAuditService:
    """Unit tests for AuditService."""

    async def test_record_calls_repository(self):
        repo = AsyncMock(spec=AuditRepository)
        svc = AuditService(repo)

        await svc.record(
            TENANT_ID,
            "superadmin",
            "rule.created",
            "rule",
            str(uuid4()),
            {"name": "test-rule"},
        )

        repo.record.assert_called_once()
        call_kwargs = repo.record.call_args.kwargs
        assert call_kwargs["tenant_id"] == TENANT_ID
        assert call_kwargs["action"] == "rule.created"
        assert call_kwargs["resource_type"] == "rule"
        assert call_kwargs["details"] == {"name": "test-rule"}

    async def test_record_swallows_exceptions(self):
        repo = AsyncMock(spec=AuditRepository)
        repo.record.side_effect = Exception("DB error")
        svc = AuditService(repo)

        # Should not raise
        await svc.record(
            TENANT_ID,
            "superadmin",
            "rule.created",
            "rule",
            str(uuid4()),
        )

    async def test_record_with_no_details(self):
        repo = AsyncMock(spec=AuditRepository)
        svc = AuditService(repo)

        await svc.record(
            TENANT_ID,
            "superadmin",
            "model.deleted",
            "model",
            str(uuid4()),
        )

        call_kwargs = repo.record.call_args.kwargs
        assert call_kwargs["details"] is None


class TestAuditRepository:
    """Test AuditRepository methods."""

    async def test_record_inserts_correctly(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": uuid4(),
                "tenant_id": TENANT_ID,
                "actor": "superadmin",
                "action": "rule.created",
                "resource_type": "rule",
                "resource_id": "abc",
                "details": "{}",
                "created_at": datetime.now(UTC),
            }
        )

        pool = AsyncMock()

        @asynccontextmanager
        async def mock_acquire():
            yield conn

        pool.acquire = mock_acquire

        with patch("bsgateway.audit.repository._sql") as mock_sql:
            mock_sql.query.side_effect = lambda q: q
            repo = AuditRepository(pool)
            result = await repo.record(
                TENANT_ID,
                "superadmin",
                "rule.created",
                "rule",
                "abc",
                {"name": "test"},
            )

        assert result["action"] == "rule.created"

    async def test_list_by_tenant(self):
        rows = [
            {
                "id": uuid4(),
                "tenant_id": TENANT_ID,
                "actor": "superadmin",
                "action": "rule.created",
                "resource_type": "rule",
                "resource_id": str(uuid4()),
                "details": "{}",
                "created_at": datetime.now(UTC),
            }
        ]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        pool = AsyncMock()

        @asynccontextmanager
        async def mock_acquire():
            yield conn

        pool.acquire = mock_acquire

        with patch("bsgateway.audit.repository._sql") as mock_sql:
            mock_sql.query.side_effect = lambda q: q
            repo = AuditRepository(pool)
            result = await repo.list_by_tenant(TENANT_ID, limit=50, offset=0)

        assert len(result) == 1
        assert result[0]["action"] == "rule.created"


class TestAuditAPI:
    """Test the audit log API endpoint."""

    def test_list_audit_logs(self, client, mock_pool, admin_headers):
        now = datetime.now(UTC)
        audit_rows = [
            {
                "id": uuid4(),
                "tenant_id": TENANT_ID,
                "actor": "superadmin",
                "action": "rule.created",
                "resource_type": "rule",
                "resource_id": str(uuid4()),
                "details": '{"name": "test-rule"}',
                "created_at": now,
            },
            {
                "id": uuid4(),
                "tenant_id": TENANT_ID,
                "actor": "bsg_test",
                "action": "model.deleted",
                "resource_type": "model",
                "resource_id": str(uuid4()),
                "details": "{}",
                "created_at": now,
            },
        ]

        with (
            patch(
                "bsgateway.audit.repository.AuditRepository.list_by_tenant",
                new_callable=AsyncMock,
                return_value=audit_rows,
            ),
            patch(
                "bsgateway.audit.repository.AuditRepository.count_by_tenant",
                new_callable=AsyncMock,
                return_value=2,
            ),
        ):
            resp = client.get(
                f"/api/v1/tenants/{TENANT_ID}/audit",
                headers=admin_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["action"] == "rule.created"
        assert data["items"][0]["details"] == {"name": "test-rule"}
        assert data["items"][1]["actor"] == "bsg_test"

    def test_audit_pagination(self, client, mock_pool, admin_headers):
        with (
            patch(
                "bsgateway.audit.repository.AuditRepository.list_by_tenant",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_list,
            patch(
                "bsgateway.audit.repository.AuditRepository.count_by_tenant",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            resp = client.get(
                f"/api/v1/tenants/{TENANT_ID}/audit?limit=10&offset=20",
                headers=admin_headers,
            )

        assert resp.status_code == 200
        mock_list.assert_called_once_with(TENANT_ID, 10, 20)

    def test_audit_tenant_isolation(self, client, mock_pool):
        """Non-admin tenant cannot access another tenant's audit."""
        other_tenant = uuid4()
        tenant_key = "bsg_tenant-key-123"

        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_api_key_by_hash",
            new_callable=AsyncMock,
            return_value={
                "id": uuid4(),
                "tenant_id": TENANT_ID,
                "key_hash": hash_api_key(tenant_key),
                "key_prefix": "bsg_tena",
                "name": "test",
                "scopes": ["chat"],  # No admin scope
                "is_active": True,
                "expires_at": None,
                "last_used_at": None,
                "created_at": datetime.now(UTC),
                "tenant_is_active": True,
            },
        ):
            resp = client.get(
                f"/api/v1/tenants/{other_tenant}/audit",
                headers={"Authorization": f"Bearer {tenant_key}"},
            )

        assert resp.status_code == 403


class TestAuditWiring:
    """Test that admin operations create audit log entries."""

    def test_create_tenant_creates_audit(self, client, mock_pool, admin_headers):
        from bsgateway.tenant.models import TenantResponse

        now = datetime.now(UTC)
        mock_tenant = TenantResponse(
            id=TENANT_ID,
            name="Test Corp",
            slug="test-corp",
            is_active=True,
            settings={},
            created_at=now,
            updated_at=now,
        )

        with (
            patch(
                "bsgateway.tenant.service.TenantService.create_tenant",
                new_callable=AsyncMock,
                return_value=mock_tenant,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            resp = client.post(
                "/api/v1/tenants",
                json={"name": "Test Corp", "slug": "test-corp"},
                headers=admin_headers,
            )

        assert resp.status_code == 201
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args[0][2] == "tenant.created"
        assert call_args[0][3] == "tenant"

    def test_delete_model_creates_audit(self, client, mock_pool, admin_headers):
        model_id = uuid4()

        with (
            patch(
                "bsgateway.tenant.service.TenantService.delete_model",
                new_callable=AsyncMock,
            ),
            patch(
                "bsgateway.audit.service.AuditService.record",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            resp = client.delete(
                f"/api/v1/tenants/{TENANT_ID}/models/{model_id}",
                headers=admin_headers,
            )

        assert resp.status_code == 204
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args[0][2] == "model.deleted"


class TestAuditInitSchema:
    """Test AuditRepository.init_schema."""

    async def test_init_schema_executes(self):
        """init_schema reads the SQL file and calls execute_schema."""
        pool = AsyncMock()

        with (
            patch(
                "bsgateway.audit.repository.execute_schema",
                new_callable=AsyncMock,
            ) as mock_exec,
            patch(
                "pathlib.Path.read_text",
                return_value="CREATE TABLE IF NOT EXISTS audit_logs (...);",
            ),
        ):
            repo = AuditRepository(pool)
            await repo.init_schema()

        mock_exec.assert_called_once_with(
            pool,
            "CREATE TABLE IF NOT EXISTS audit_logs (...);",
        )
