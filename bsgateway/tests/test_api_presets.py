"""Tests for presets and feedback API endpoints."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from bsgateway.api.app import create_app
from bsgateway.api.deps import get_auth_context
from bsgateway.tests.conftest import make_gateway_auth_context

ENCRYPTION_KEY_HEX = os.urandom(32).hex()
ADMIN_TENANT_ID = uuid4()


def _make_app():
    app = create_app()
    pool = AsyncMock()
    pool._closed = False
    app.state.db_pool = pool
    app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
    app.state.redis = None
    admin_ctx = make_gateway_auth_context(tenant_id=ADMIN_TENANT_ID, is_admin=True)
    app.dependency_overrides[get_auth_context] = lambda: admin_ctx
    return app


def _client():
    return TestClient(_make_app(), raise_server_exceptions=False)


class TestPresetsAPI:
    def test_list_presets(self):
        client = _client()
        resp = client.get("/api/v1/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 4
        names = {p["name"] for p in data}
        assert "coding-assistant" in names
        assert "customer-support" in names

    def test_list_presets_has_counts(self):
        client = _client()
        resp = client.get("/api/v1/presets")
        for preset in resp.json():
            assert "intent_count" in preset
            assert "rule_count" in preset
            assert preset["rule_count"] >= 1

    def test_apply_preset(self):
        from bsgateway.presets.models import PresetApplyResult

        client = _client()
        tid = uuid4()

        mock_result = PresetApplyResult(
            preset_name="coding-assistant",
            rules_created=4,
            intents_created=3,
            examples_created=12,
        )

        with patch(
            "bsgateway.presets.service.PresetService.apply_preset",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/presets/apply",
                json={
                    "preset_name": "coding-assistant",
                    "model_mapping": {
                        "economy": "gpt-4o-mini",
                        "balanced": "gpt-4o",
                        "premium": "claude-opus",
                    },
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["preset_name"] == "coding-assistant"
            assert data["rules_created"] == 4
            assert data["intents_created"] == 3

    def test_apply_preset_unknown(self):
        client = _client()
        resp = client.post(
            f"/api/v1/tenants/{uuid4()}/presets/apply",
            json={
                "preset_name": "nonexistent",
                "model_mapping": {
                    "economy": "a",
                    "balanced": "b",
                    "premium": "c",
                },
            },
        )
        assert resp.status_code == 400

    def test_apply_preset_no_auth(self):
        app = create_app()
        pool = AsyncMock()
        pool._closed = False
        app.state.db_pool = pool
        app.state.encryption_key = bytes.fromhex(ENCRYPTION_KEY_HEX)
        app.state.auth_provider = AsyncMock()
        app.state.redis = None
        # No dependency override → auth required
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/v1/tenants/{uuid4()}/presets/apply",
            json={
                "preset_name": "general",
                "model_mapping": {
                    "economy": "a",
                    "balanced": "b",
                    "premium": "c",
                },
            },
        )
        assert resp.status_code == 401


class TestFeedbackAPI:
    def test_submit_feedback(self):
        client = _client()
        tid = uuid4()
        now = datetime.now(UTC)
        with patch(
            "bsgateway.presets.repository.FeedbackRepository.create_feedback",
            new_callable=AsyncMock,
            return_value={
                "id": uuid4(),
                "tenant_id": tid,
                "routing_id": "route-123",
                "rating": 4,
                "comment": "Good",
                "created_at": now,
            },
        ):
            resp = client.post(
                f"/api/v1/tenants/{tid}/feedback",
                json={
                    "routing_id": "route-123",
                    "rating": 4,
                    "comment": "Good",
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["rating"] == 4
            assert data["routing_id"] == "route-123"

    def test_submit_feedback_invalid_rating(self):
        client = _client()
        resp = client.post(
            f"/api/v1/tenants/{uuid4()}/feedback",
            json={"routing_id": "x", "rating": 6},
        )
        assert resp.status_code == 422

    def test_list_feedback(self):
        client = _client()
        tid = uuid4()
        now = datetime.now(UTC)
        with patch(
            "bsgateway.presets.repository.FeedbackRepository.list_feedback",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": uuid4(),
                    "tenant_id": tid,
                    "routing_id": "r-1",
                    "rating": 5,
                    "comment": "",
                    "created_at": now,
                }
            ],
        ):
            resp = client.get(f"/api/v1/tenants/{tid}/feedback")
            assert resp.status_code == 200
            assert len(resp.json()) == 1
