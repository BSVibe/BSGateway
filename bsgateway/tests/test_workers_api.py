"""Tests for worker API endpoints: register, heartbeat, poll, result."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.api.deps import get_auth_context
from bsgateway.streams import RedisStreamManager
from bsgateway.tests.conftest import make_gateway_auth_context, make_mock_pool

TENANT_ID = uuid4()
WORKER_ID = uuid4()
TASK_ID = uuid4()


@pytest.fixture
def mock_pool():
    pool, conn = make_mock_pool()
    return pool, conn


@pytest.fixture
def mock_stream_manager() -> AsyncMock:
    return AsyncMock(spec=RedisStreamManager)


@pytest.fixture
def app(mock_pool, mock_stream_manager):
    pool, _conn = mock_pool
    app = create_app()
    app.state.db_pool = pool
    app.state.encryption_key = b"\x00" * 32
    app.state.redis = MagicMock()
    app.state.stream_manager = mock_stream_manager
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def tenant_ctx():
    return make_gateway_auth_context(tenant_id=TENANT_ID)


def _worker_row(
    worker_id=WORKER_ID,
    tenant_id=TENANT_ID,
    name="test-worker",
) -> dict:
    return {
        "id": worker_id,
        "tenant_id": tenant_id,
        "name": name,
        "labels": "[]",
        "capabilities": "[]",
        "status": "online",
    }


class TestRegisterWorker:
    def test_register_with_valid_install_token(self, app, client: TestClient, mock_pool) -> None:
        _pool, conn = mock_pool
        conn.fetchrow.return_value = {"id": WORKER_ID}

        with patch(
            "bsgateway.api.routers.workers.resolve_install_token_tenant",
            new=AsyncMock(return_value=TENANT_ID),
        ):
            resp = client.post(
                "/api/v1/workers/register",
                json={"name": "my-worker", "labels": ["gpu"]},
                headers={"X-Install-Token": "bsg-test"},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == str(WORKER_ID)
        assert "token" in body
        assert len(body["token"]) > 0

    def test_register_without_token_is_401(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/workers/register",
            json={"name": "w", "labels": []},
        )
        assert resp.status_code == 401

    def test_register_multi_capability_creates_one_model_per_cap(
        self, app, client: TestClient, mock_pool
    ) -> None:
        """3 capabilities → 3 tenant_models rows with suffixed names."""
        _pool, conn = mock_pool
        conn.fetchrow.return_value = {"id": WORKER_ID}

        with patch(
            "bsgateway.api.routers.workers.resolve_install_token_tenant",
            new=AsyncMock(return_value=TENANT_ID),
        ):
            resp = client.post(
                "/api/v1/workers/register",
                json={
                    "name": "trio",
                    "labels": [],
                    "capabilities": ["claude_code", "codex", "opencode"],
                },
                headers={"X-Install-Token": "bsg-test"},
            )

        assert resp.status_code == 201
        # 1 create_worker call + 3 upsert_worker_model calls
        assert conn.fetchrow.await_count == 4

        upsert_calls = conn.fetchrow.await_args_list[1:]
        names = [call.args[2] for call in upsert_calls]
        litellm = [call.args[3] for call in upsert_calls]
        assert names == ["trio (claude_code)", "trio (codex)", "trio (opencode)"]
        assert litellm == [
            "executor/claude_code",
            "executor/codex",
            "executor/opencode",
        ]

    def test_register_single_capability_keeps_bare_name(
        self, app, client: TestClient, mock_pool
    ) -> None:
        _pool, conn = mock_pool
        conn.fetchrow.return_value = {"id": WORKER_ID}

        with patch(
            "bsgateway.api.routers.workers.resolve_install_token_tenant",
            new=AsyncMock(return_value=TENANT_ID),
        ):
            resp = client.post(
                "/api/v1/workers/register",
                json={"name": "solo", "capabilities": ["opencode"]},
                headers={"X-Install-Token": "bsg-test"},
            )

        assert resp.status_code == 201
        upsert_call = conn.fetchrow.await_args_list[1]
        assert upsert_call.args[2] == "solo"
        assert upsert_call.args[3] == "executor/opencode"

    def test_register_with_invalid_token_is_401(self, client: TestClient) -> None:
        with patch(
            "bsgateway.api.routers.workers.resolve_install_token_tenant",
            new=AsyncMock(return_value=None),
        ):
            resp = client.post(
                "/api/v1/workers/register",
                json={"name": "w", "labels": []},
                headers={"X-Install-Token": "bad"},
            )
        assert resp.status_code == 401


class TestInstallToken:
    def test_get_status_no_token(self, app, client: TestClient, tenant_ctx, mock_pool) -> None:
        app.dependency_overrides[get_auth_context] = lambda: tenant_ctx
        with patch(
            "bsgateway.api.routers.workers.has_install_token",
            new=AsyncMock(return_value=False),
        ):
            resp = client.get("/api/v1/workers/install-token")
        assert resp.status_code == 200
        assert resp.json() == {"token": None, "has_token": False}

    def test_create_returns_plaintext_once(
        self, app, client: TestClient, tenant_ctx, mock_pool
    ) -> None:
        app.dependency_overrides[get_auth_context] = lambda: tenant_ctx
        with patch(
            "bsgateway.api.routers.workers.set_install_token_hash",
            new=AsyncMock(),
        ):
            resp = client.post("/api/v1/workers/install-token")
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_token"] is True
        assert body["token"].startswith("bsg-")

    def test_revoke_returns_204(self, app, client: TestClient, tenant_ctx, mock_pool) -> None:
        app.dependency_overrides[get_auth_context] = lambda: tenant_ctx
        with patch(
            "bsgateway.api.routers.workers.set_install_token_hash",
            new=AsyncMock(),
        ):
            resp = client.delete("/api/v1/workers/install-token")
        assert resp.status_code == 204


class TestHeartbeat:
    def test_heartbeat_with_valid_token(self, app, client: TestClient, mock_pool) -> None:
        _pool, conn = mock_pool
        conn.fetchrow.return_value = _worker_row()

        resp = client.post(
            "/api/v1/workers/heartbeat",
            headers={"X-Worker-Token": "valid-token"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_heartbeat_missing_token_returns_401(self, app, client: TestClient) -> None:
        resp = client.post("/api/v1/workers/heartbeat")
        assert resp.status_code == 401

    def test_heartbeat_invalid_token_returns_401(self, app, client: TestClient, mock_pool) -> None:
        _pool, conn = mock_pool
        conn.fetchrow.return_value = None  # no matching worker

        resp = client.post(
            "/api/v1/workers/heartbeat",
            headers={"X-Worker-Token": "bad-token"},
        )

        assert resp.status_code == 401


class TestPollTasks:
    def test_poll_returns_messages(
        self, app, client: TestClient, mock_pool, mock_stream_manager
    ) -> None:
        _pool, conn = mock_pool
        conn.fetchrow.return_value = _worker_row()
        mock_stream_manager.consume.return_value = [
            {
                "task_id": str(TASK_ID),
                "executor_type": "claude_code",
                "prompt": "do stuff",
                "action": "execute",
                "_message_id": "1-0",
            }
        ]

        resp = client.post(
            "/api/v1/workers/poll",
            headers={"X-Worker-Token": "valid-token"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["task_id"] == str(TASK_ID)
        # _message_id should be popped (auto-ACK)
        assert "_message_id" not in data[0]
        mock_stream_manager.acknowledge.assert_awaited_once()

    def test_poll_empty_stream(
        self, app, client: TestClient, mock_pool, mock_stream_manager
    ) -> None:
        _pool, conn = mock_pool
        conn.fetchrow.return_value = _worker_row()
        mock_stream_manager.consume.return_value = []

        resp = client.post(
            "/api/v1/workers/poll",
            headers={"X-Worker-Token": "valid-token"},
        )

        assert resp.status_code == 200
        assert resp.json() == []


class TestReportResult:
    def test_report_result_updates_task(self, app, client: TestClient, mock_pool) -> None:
        _pool, conn = mock_pool
        conn.fetchrow.return_value = _worker_row()

        resp = client.post(
            "/api/v1/workers/result",
            json={
                "task_id": str(TASK_ID),
                "success": True,
                "output": "done",
            },
            headers={"X-Worker-Token": "valid-token"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
