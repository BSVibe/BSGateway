"""Tests for the usage dashboard API endpoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.core.security import hash_api_key
from bsgateway.tests.conftest import make_api_key_row, make_mock_pool

SUPERADMIN_KEY = "test-superadmin-key"
ENCRYPTION_KEY_HEX = os.urandom(32).hex()
TENANT_ID = uuid4()
TENANT_KEY = "bsg_test-tenant-usage-key"


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


@pytest.fixture
def tenant_headers() -> dict:
    return {"Authorization": f"Bearer {TENANT_KEY}"}


def _patch_auth(tenant_id=None, scopes=None):
    return patch(
        "bsgateway.tenant.repository.TenantRepository.get_api_key_by_hash",
        new_callable=AsyncMock,
        return_value=make_api_key_row(
            tenant_id=tenant_id or TENANT_ID,
            scopes=scopes or ["admin"],
            key_hash=hash_api_key(TENANT_KEY),
        ),
    )


def _setup_usage_pool(mock_pool, total_row, model_rows, rule_rows):
    """Configure mock pool with proper async context manager for usage queries."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=total_row)
    conn.fetch = AsyncMock(side_effect=[model_rows, rule_rows])

    @asynccontextmanager
    async def mock_acquire():
        yield conn

    mock_pool.acquire = mock_acquire


class TestUsageAPI:
    def test_usage_with_data(self, client, mock_pool, admin_headers):
        total_row = {"total_requests": 150, "total_tokens": 50000}
        model_rows = [
            {
                "day": date(2024, 1, 15),
                "resolved_model": "openai/gpt-4o",
                "requests": 100,
                "tokens": 35000,
            },
            {
                "day": date(2024, 1, 15),
                "resolved_model": "anthropic/claude-3",
                "requests": 50,
                "tokens": 15000,
            },
        ]
        rule_rows = [
            {"rule_id": uuid4(), "rule_name": "code-review", "requests": 80},
            {"rule_id": uuid4(), "rule_name": "default", "requests": 70},
        ]

        _setup_usage_pool(mock_pool, total_row, model_rows, rule_rows)

        with patch("bsgateway.api.routers.usage._sql") as mock_sql:
            mock_sql.query.side_effect = lambda q: q
            resp = client.get(
                f"/api/v1/tenants/{TENANT_ID}/usage",
                headers=admin_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 150
        assert data["total_tokens"] == 50000
        assert "openai/gpt-4o" in data["by_model"]
        assert data["by_model"]["openai/gpt-4o"]["requests"] == 100
        assert "code-review" in data["by_rule"]
        assert len(data["daily_breakdown"]) == 1

    def test_empty_period_returns_zeros(self, client, mock_pool, admin_headers):
        total_row = {"total_requests": 0, "total_tokens": 0}

        _setup_usage_pool(mock_pool, total_row, [], [])

        with patch("bsgateway.api.routers.usage._sql") as mock_sql:
            mock_sql.query.side_effect = lambda q: q
            resp = client.get(
                f"/api/v1/tenants/{TENANT_ID}/usage?period=week",
                headers=admin_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 0
        assert data["total_tokens"] == 0
        assert data["by_model"] == {}
        assert data["by_rule"] == {}
        assert data["daily_breakdown"] == []

    def test_date_range_filtering(self, client, mock_pool, admin_headers):
        total_row = {"total_requests": 10, "total_tokens": 1000}

        _setup_usage_pool(mock_pool, total_row, [], [])

        with patch("bsgateway.api.routers.usage._sql") as mock_sql:
            mock_sql.query.side_effect = lambda q: q
            resp = client.get(
                f"/api/v1/tenants/{TENANT_ID}/usage?from=2024-01-01&to=2024-01-31",
                headers=admin_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["total_requests"] == 10

    def test_tenant_access_by_own_key(self, client, mock_pool, tenant_headers):
        """Tenant can access their own usage."""
        total_row = {"total_requests": 5, "total_tokens": 500}
        _setup_usage_pool(mock_pool, total_row, [], [])

        with (
            _patch_auth(TENANT_ID, ["admin"]),
            patch("bsgateway.api.routers.usage._sql") as mock_sql,
        ):
            mock_sql.query.side_effect = lambda q: q
            resp = client.get(
                f"/api/v1/tenants/{TENANT_ID}/usage",
                headers=tenant_headers,
            )

        assert resp.status_code == 200

    def test_tenant_cannot_access_other_tenant(self, client, mock_pool, tenant_headers):
        """Tenant cannot access another tenant's usage."""
        other_tenant = uuid4()

        with _patch_auth(TENANT_ID, ["chat"]):
            resp = client.get(
                f"/api/v1/tenants/{other_tenant}/usage",
                headers=tenant_headers,
            )

        assert resp.status_code == 403

    def test_invalid_period_returns_422(self, client, admin_headers):
        resp = client.get(
            f"/api/v1/tenants/{TENANT_ID}/usage?period=invalid",
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_daily_breakdown_sorted(self, client, mock_pool, admin_headers):
        total_row = {"total_requests": 20, "total_tokens": 3000}
        model_rows = [
            {"day": date(2024, 1, 17), "resolved_model": "gpt-4o", "requests": 5, "tokens": 1000},
            {"day": date(2024, 1, 15), "resolved_model": "gpt-4o", "requests": 10, "tokens": 1500},
            {"day": date(2024, 1, 16), "resolved_model": "gpt-4o", "requests": 5, "tokens": 500},
        ]

        _setup_usage_pool(mock_pool, total_row, model_rows, [])

        with patch("bsgateway.api.routers.usage._sql") as mock_sql:
            mock_sql.query.side_effect = lambda q: q
            resp = client.get(
                f"/api/v1/tenants/{TENANT_ID}/usage?period=week",
                headers=admin_headers,
            )

        data = resp.json()
        dates = [d["date"] for d in data["daily_breakdown"]]
        assert dates == sorted(dates)
