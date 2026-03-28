"""Tests for bsgateway.api.app — app factory, lifespan, and Redis init."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from bsgateway.api.app import _init_redis, create_app, lifespan

# ---------------------------------------------------------------------------
# create_app
# ---------------------------------------------------------------------------


class TestCreateApp:
    def test_returns_fastapi_instance(self):
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_metadata(self):
        app = create_app()
        assert app.title == "BSGateway API"
        assert app.version == "0.5.0"

    def test_routers_registered(self):
        app = create_app()
        paths = [route.path for route in app.routes]
        assert "/api/v1/tenants" in paths
        assert "/api/v1/tenants/{tenant_id}/rules" in paths

    def test_cors_middleware_present(self):
        app = create_app()
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    def test_auth_router_removed(self):
        """Auth router should no longer be registered."""
        app = create_app()
        paths = [route.path for route in app.routes]
        assert "/api/v1/auth/token" not in paths


# ---------------------------------------------------------------------------
# _init_redis
# ---------------------------------------------------------------------------


class TestInitRedis:
    async def test_returns_none_when_no_host(self):
        with patch("bsgateway.api.app.settings") as mock_settings:
            mock_settings.redis_host = ""
            result = await _init_redis()
        assert result is None

    async def test_returns_none_on_connection_failure(self):
        with (
            patch("bsgateway.api.app.settings") as mock_settings,
            patch("redis.asyncio.Redis") as mock_redis_cls,
        ):
            mock_settings.redis_host = "localhost"
            mock_settings.redis_port = 6379
            mock_settings.redis_password = ""
            mock_redis_cls.return_value.ping = AsyncMock(side_effect=ConnectionError("refused"))
            result = await _init_redis()
        assert result is None

    async def test_returns_client_on_success(self):
        with (
            patch("bsgateway.api.app.settings") as mock_settings,
            patch("redis.asyncio.Redis") as mock_redis_cls,
        ):
            mock_settings.redis_host = "localhost"
            mock_settings.redis_port = 6379
            mock_settings.redis_password = ""
            mock_client = AsyncMock()
            mock_redis_cls.return_value = mock_client
            result = await _init_redis()
        assert result is mock_client


# ---------------------------------------------------------------------------
# lifespan
# ---------------------------------------------------------------------------


class TestLifespan:
    async def test_raises_without_database_url(self):
        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()

        with (
            patch("bsgateway.api.app.settings") as mock_settings,
            pytest.raises(RuntimeError, match="collector_database_url is required"),
        ):
            mock_settings.collector_database_url = ""
            async with lifespan(app):
                pass

    async def test_raises_without_supabase_config(self):
        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()

        with (
            patch("bsgateway.api.app.settings") as mock_settings,
            pytest.raises(RuntimeError, match=r"SUPABASE_URL.*or SUPABASE_JWT_SECRET is required"),
        ):
            mock_settings.collector_database_url = "postgresql://test"
            mock_settings.encryption_key_bytes = b"x" * 32
            mock_settings.supabase_url = ""
            mock_settings.supabase_jwt_secret = ""
            async with lifespan(app):
                pass

    async def test_lifespan_sets_state_and_cleans_up(self):
        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()

        mock_pool = AsyncMock()
        mock_redis = AsyncMock()

        with (
            patch("bsgateway.api.app.settings") as mock_settings,
            patch("bsgateway.api.app.get_pool", new_callable=AsyncMock, return_value=mock_pool),
            patch("bsgateway.api.app._init_redis", new_callable=AsyncMock, return_value=mock_redis),
            patch("bsgateway.api.app.close_pool", new_callable=AsyncMock) as mock_close_pool,
            patch("bsgateway.api.app.execute_schema", new_callable=AsyncMock),
            patch("bsgateway.api.app.TenantRepository") as mock_tenant_repo_cls,
            patch("bsgateway.api.app.RulesRepository") as mock_rules_repo_cls,
            patch("bsgateway.api.app.FeedbackRepository") as mock_feedback_repo_cls,
            patch("bsgateway.api.app.AuditRepository") as mock_audit_repo_cls,
            patch("bsgateway.apikey.repository.ApiKeyRepository") as mock_apikey_repo_cls,
            patch("bsgateway.api.app.CacheManager"),
            patch("bsvibe_auth.SupabaseAuthProvider") as mock_auth_provider_cls,
        ):
            mock_settings.collector_database_url = "postgresql://test"
            mock_settings.encryption_key_bytes = b"x" * 32
            mock_settings.supabase_url = "https://test.supabase.co"
            mock_settings.supabase_jwt_secret = ""
            mock_settings.redis_host = "localhost"

            # Each repo class returns a mock with async init_schema
            repo_classes = [
                mock_tenant_repo_cls,
                mock_rules_repo_cls,
                mock_feedback_repo_cls,
                mock_audit_repo_cls,
                mock_apikey_repo_cls,
            ]
            for cls in repo_classes:
                cls.return_value.init_schema = AsyncMock()

            async with lifespan(app):
                # Verify state was set
                assert app.state.db_pool == mock_pool
                assert app.state.auth_provider == mock_auth_provider_cls.return_value

            # Verify cleanup
            mock_redis.aclose.assert_awaited_once()
            mock_close_pool.assert_awaited_once()

    async def test_lifespan_without_redis(self):
        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()

        mock_pool = AsyncMock()

        with (
            patch("bsgateway.api.app.settings") as mock_settings,
            patch("bsgateway.api.app.get_pool", new_callable=AsyncMock, return_value=mock_pool),
            patch("bsgateway.api.app._init_redis", new_callable=AsyncMock, return_value=None),
            patch("bsgateway.api.app.close_pool", new_callable=AsyncMock),
            patch("bsgateway.api.app.execute_schema", new_callable=AsyncMock),
            patch("bsgateway.api.app.TenantRepository") as mock_tenant_repo_cls,
            patch("bsgateway.api.app.RulesRepository") as mock_rules_repo_cls,
            patch("bsgateway.api.app.FeedbackRepository") as mock_feedback_repo_cls,
            patch("bsgateway.api.app.AuditRepository") as mock_audit_repo_cls,
            patch("bsgateway.apikey.repository.ApiKeyRepository") as mock_apikey_repo_cls,
            patch("bsvibe_auth.SupabaseAuthProvider"),
        ):
            mock_settings.collector_database_url = "postgresql://test"
            mock_settings.encryption_key_bytes = b"x" * 32
            mock_settings.supabase_jwt_secret = "test-supabase-secret"
            mock_settings.redis_host = ""

            repo_classes = [
                mock_tenant_repo_cls,
                mock_rules_repo_cls,
                mock_feedback_repo_cls,
                mock_audit_repo_cls,
                mock_apikey_repo_cls,
            ]
            for cls in repo_classes:
                cls.return_value.init_schema = AsyncMock()

            async with lifespan(app):
                # cache should be None when no Redis
                assert app.state.cache is None
