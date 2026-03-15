"""Tests for the chat completions API endpoint."""
from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.chat.service import ModelNotFoundError, NoRuleMatchedError
from bsgateway.core.security import hash_api_key

SUPERADMIN_KEY = "test-superadmin-key"
ENCRYPTION_KEY_HEX = os.urandom(32).hex()
TENANT_ID = uuid4()
TENANT_KEY = "bsg_test-tenant-key-12345678"


def _make_api_key_row(tenant_id=None, scopes=None):
    from datetime import UTC, datetime

    return {
        "id": uuid4(),
        "tenant_id": tenant_id or TENANT_ID,
        "key_hash": hash_api_key(TENANT_KEY),
        "key_prefix": "bsg_test",
        "name": "test-key",
        "scopes": scopes or ["chat"],
        "is_active": True,
        "expires_at": None,
        "last_used_at": None,
        "created_at": datetime.now(UTC),
        "tenant_is_active": True,
    }


@pytest.fixture
def mock_pool() -> AsyncMock:
    pool = AsyncMock()
    pool._closed = False
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
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
def tenant_headers() -> dict:
    return {"Authorization": f"Bearer {TENANT_KEY}"}


@pytest.fixture
def admin_headers() -> dict:
    return {"Authorization": f"Bearer {SUPERADMIN_KEY}"}


def _patch_auth():
    """Patch auth to resolve to tenant."""
    return patch(
        "bsgateway.tenant.repository.TenantRepository.get_api_key_by_hash",
        new_callable=AsyncMock,
        return_value=_make_api_key_row(),
    )


class TestChatAuth:
    def test_no_auth_returns_401(self, client: TestClient):
        resp = client.post(
            "/api/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401

    def test_invalid_key_returns_401(self, client: TestClient):
        with patch(
            "bsgateway.tenant.repository.TenantRepository.get_api_key_by_hash",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": "Bearer bsg_invalid"},
            )
        assert resp.status_code == 401


class TestChatValidation:
    def test_missing_messages_returns_400(self, client: TestClient, tenant_headers):
        with _patch_auth():
            resp = client.post(
                "/api/v1/chat/completions",
                json={"model": "gpt-4o"},
                headers=tenant_headers,
            )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "invalid_messages"

    def test_empty_messages_returns_400(self, client: TestClient, tenant_headers):
        with _patch_auth():
            resp = client.post(
                "/api/v1/chat/completions",
                json={"model": "gpt-4o", "messages": []},
                headers=tenant_headers,
            )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "invalid_messages"


class TestChatCompletion:
    def test_happy_path(self, client: TestClient, tenant_headers):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }

        with (
            _patch_auth(),
            patch(
                "bsgateway.chat.service.ChatService.complete",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hello"}],
                },
                headers=tenant_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "chatcmpl-123"
        assert data["choices"][0]["message"]["content"] == "Hello!"

    def test_model_not_found_returns_error(self, client: TestClient, tenant_headers):
        with (
            _patch_auth(),
            patch(
                "bsgateway.chat.service.ChatService.complete",
                new_callable=AsyncMock,
                side_effect=ModelNotFoundError("Model 'xyz' is not registered"),
            ),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "xyz",
                    "messages": [{"role": "user", "content": "hello"}],
                },
                headers=tenant_headers,
            )

        data = resp.json()
        assert data["error"]["code"] == "model_not_found"
        assert "xyz" in data["error"]["message"]

    def test_no_rule_matched_returns_error(self, client: TestClient, tenant_headers):
        with (
            _patch_auth(),
            patch(
                "bsgateway.chat.service.ChatService.complete",
                new_callable=AsyncMock,
                side_effect=NoRuleMatchedError("No routing rule matched"),
            ),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "auto",
                    "messages": [{"role": "user", "content": "hello"}],
                },
                headers=tenant_headers,
            )

        data = resp.json()
        assert data["error"]["code"] == "no_rule_matched"

    def test_upstream_error_returns_502(self, client: TestClient, tenant_headers):
        with (
            _patch_auth(),
            patch(
                "bsgateway.chat.service.ChatService.complete",
                new_callable=AsyncMock,
                side_effect=Exception("Connection refused"),
            ),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hello"}],
                },
                headers=tenant_headers,
            )

        data = resp.json()
        assert data["error"]["type"] == "upstream_error"

    def test_streaming_returns_sse(self, client: TestClient, tenant_headers):
        """Streaming response should return SSE format."""
        chunk1 = MagicMock()
        chunk1.model_dump.return_value = {
            "id": "chatcmpl-123",
            "choices": [{"delta": {"content": "Hel"}, "index": 0}],
        }
        chunk2 = MagicMock()
        chunk2.model_dump.return_value = {
            "id": "chatcmpl-123",
            "choices": [{"delta": {"content": "lo!"}, "index": 0}],
        }

        async def mock_stream():
            yield chunk1
            yield chunk2

        with (
            _patch_auth(),
            patch(
                "bsgateway.chat.service.ChatService.complete",
                new_callable=AsyncMock,
                return_value=mock_stream(),
            ),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
                headers=tenant_headers,
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        assert len(data_lines) == 3  # 2 chunks + [DONE]
        assert data_lines[-1] == "data: [DONE]"

        # Verify first chunk is valid JSON
        first_data = json.loads(data_lines[0][6:])
        assert first_data["choices"][0]["delta"]["content"] == "Hel"

    def test_admin_can_use_chat(self, client: TestClient, admin_headers):
        """Superadmin should be able to use chat completions too."""
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"id": "chatcmpl-123", "choices": []}

        with patch(
            "bsgateway.chat.service.ChatService.complete",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hello"}],
                },
                headers=admin_headers,
            )

        assert resp.status_code == 200
