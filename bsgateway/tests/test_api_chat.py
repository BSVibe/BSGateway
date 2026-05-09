"""Tests for the chat completions API endpoint."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.api.deps import get_auth_context
from bsgateway.chat.service import ModelNotFoundError, NoRuleMatchedError
from bsgateway.tests.conftest import make_gateway_auth_context, make_mock_pool

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
    app.state.redis = None
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def tenant_ctx():
    return make_gateway_auth_context(tenant_id=TENANT_ID, is_admin=False)


@pytest.fixture
def admin_ctx():
    return make_gateway_auth_context(tenant_id=TENANT_ID, is_admin=True)


class TestChatAuth:
    def test_no_auth_returns_401(self, app, client: TestClient):
        app.state.auth_provider = AsyncMock()
        resp = client.post(
            "/api/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401

    def test_invalid_key_returns_401(self, app, client: TestClient):
        from fastapi import HTTPException

        with patch(
            "bsgateway.api.deps._authz_get_current_user",
            new=AsyncMock(side_effect=HTTPException(status_code=401, detail="bad")),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": "Bearer bad-token"},
            )
        assert resp.status_code == 401


class TestChatValidation:
    def test_missing_messages_returns_400(self, app, client: TestClient, tenant_ctx):
        app.dependency_overrides[get_auth_context] = lambda: tenant_ctx
        resp = client.post(
            "/api/v1/chat/completions",
            json={"model": "gpt-4o"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "invalid_messages"

    def test_empty_messages_returns_400(self, app, client: TestClient, tenant_ctx):
        app.dependency_overrides[get_auth_context] = lambda: tenant_ctx
        resp = client.post(
            "/api/v1/chat/completions",
            json={"model": "gpt-4o", "messages": []},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "invalid_messages"


class TestChatCompletion:
    def test_happy_path(self, app, client: TestClient, tenant_ctx):
        app.dependency_overrides[get_auth_context] = lambda: tenant_ctx
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
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "chatcmpl-123"
        assert data["choices"][0]["message"]["content"] == "Hello!"

    def test_model_not_found_returns_error(self, app, client: TestClient, tenant_ctx):
        app.dependency_overrides[get_auth_context] = lambda: tenant_ctx
        with patch(
            "bsgateway.chat.service.ChatService.complete",
            new_callable=AsyncMock,
            side_effect=ModelNotFoundError("Model 'xyz' is not registered"),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "xyz",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )

        data = resp.json()
        assert data["error"]["code"] == "model_not_found"
        assert "xyz" in data["error"]["message"]

    def test_no_rule_matched_returns_error(self, app, client: TestClient, tenant_ctx):
        app.dependency_overrides[get_auth_context] = lambda: tenant_ctx
        with patch(
            "bsgateway.chat.service.ChatService.complete",
            new_callable=AsyncMock,
            side_effect=NoRuleMatchedError("No routing rule matched"),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "auto",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )

        data = resp.json()
        assert data["error"]["code"] == "no_rule_matched"

    def test_upstream_error_returns_502(self, app, client: TestClient, tenant_ctx):
        app.dependency_overrides[get_auth_context] = lambda: tenant_ctx
        with patch(
            "bsgateway.chat.service.ChatService.complete",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )

        data = resp.json()
        assert data["error"]["type"] == "upstream_error"

    def test_streaming_returns_sse(self, app, client: TestClient, tenant_ctx):
        """Streaming response should return SSE format."""
        app.dependency_overrides[get_auth_context] = lambda: tenant_ctx
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

        with patch(
            "bsgateway.chat.service.ChatService.complete",
            new_callable=AsyncMock,
            return_value=mock_stream(),
        ):
            resp = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        lines = resp.text.strip().split("\n")
        data_lines = [line for line in lines if line.startswith("data: ")]
        assert len(data_lines) == 3  # 2 chunks + [DONE]
        assert data_lines[-1] == "data: [DONE]"

        # Verify first chunk is valid JSON
        first_data = json.loads(data_lines[0][6:])
        assert first_data["choices"][0]["delta"]["content"] == "Hel"

    def test_admin_can_use_chat(self, app, client: TestClient, admin_ctx):
        """Admin should be able to use chat completions too."""
        app.dependency_overrides[get_auth_context] = lambda: admin_ctx
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
            )

        assert resp.status_code == 200
