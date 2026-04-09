"""Tests for ChatService: model resolution, tenant config loading, litellm delegation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from bsgateway.chat.service import (
    ChatService,
    ModelNotFoundError,
    NoRuleMatchedError,
)
from bsgateway.rules.models import (
    RoutingRule,
    RuleMatch,
    TenantConfig,
    TenantModel,
)

TENANT_ID = uuid4()
ENCRYPTION_KEY = bytes.fromhex("a" * 64)


def _make_tenant_config(
    models: dict[str, TenantModel] | None = None,
    rules: list[RoutingRule] | None = None,
    settings: dict | None = None,
) -> TenantConfig:
    if models is None:
        models = {
            "gpt-4o": TenantModel(
                model_name="gpt-4o",
                provider="openai",
                litellm_model="openai/gpt-4o",
                api_key_encrypted="encrypted_key_1",
            ),
            "claude-sonnet": TenantModel(
                model_name="claude-sonnet",
                provider="anthropic",
                litellm_model="anthropic/claude-3-5-sonnet-20241022",
                api_key_encrypted="encrypted_key_2",
            ),
        }
    if rules is None:
        rules = [
            RoutingRule(
                id=str(uuid4()),
                tenant_id=str(TENANT_ID),
                name="code-review",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="gpt-4o",
                conditions=[],
            ),
            RoutingRule(
                id=str(uuid4()),
                tenant_id=str(TENANT_ID),
                name="default",
                priority=100,
                is_active=True,
                is_default=True,
                target_model="claude-sonnet",
            ),
        ]
    return TenantConfig(
        tenant_id=str(TENANT_ID),
        slug="acme",
        models=models,
        rules=rules,
        settings=settings or {},
    )


def _make_pool() -> MagicMock:
    from bsgateway.tests.conftest import make_mock_pool

    pool, _conn = make_mock_pool()
    return pool


class TestResolveModel:
    """Test model resolution logic."""

    async def test_specific_model_direct_lookup(self):
        svc = ChatService(_make_pool(), ENCRYPTION_KEY)
        config = _make_tenant_config()

        model, match = await svc.resolve_model(config, {"model": "gpt-4o", "messages": []})

        assert model.model_name == "gpt-4o"
        assert match is None

    async def test_specific_model_not_found(self):
        svc = ChatService(_make_pool(), ENCRYPTION_KEY)
        config = _make_tenant_config()

        with pytest.raises(ModelNotFoundError, match="not registered"):
            await svc.resolve_model(config, {"model": "nonexistent", "messages": []})

    async def test_auto_triggers_rule_engine(self):
        svc = ChatService(_make_pool(), ENCRYPTION_KEY)
        config = _make_tenant_config()

        with patch.object(svc._engine, "evaluate", new_callable=AsyncMock) as mock_eval:
            mock_eval.return_value = RuleMatch(
                rule=config.rules[0],
                target_model="gpt-4o",
            )
            model, _match = await svc.resolve_model(
                config, {"model": "auto", "messages": [{"role": "user", "content": "test"}]}
            )

        assert model.model_name == "gpt-4o"
        assert _match is not None
        assert _match.target_model == "gpt-4o"

    async def test_auto_no_rule_matches(self):
        svc = ChatService(_make_pool(), ENCRYPTION_KEY)
        config = _make_tenant_config(rules=[])

        with pytest.raises(NoRuleMatchedError, match="No routing rule matched"):
            await svc.resolve_model(
                config, {"model": "auto", "messages": [{"role": "user", "content": "test"}]}
            )

    async def test_auto_rule_targets_unregistered_model(self):
        svc = ChatService(_make_pool(), ENCRYPTION_KEY)
        config = _make_tenant_config(
            models={
                "gpt-4o": TenantModel(
                    model_name="gpt-4o",
                    provider="openai",
                    litellm_model="openai/gpt-4o",
                )
            },
        )

        with patch.object(svc._engine, "evaluate", new_callable=AsyncMock) as mock_eval:
            mock_eval.return_value = RuleMatch(
                rule=RoutingRule(
                    id=str(uuid4()),
                    tenant_id=str(TENANT_ID),
                    name="missing-target",
                    priority=1,
                    is_active=True,
                    is_default=False,
                    target_model="nonexistent-model",
                ),
                target_model="nonexistent-model",
            )
            with pytest.raises(ModelNotFoundError, match="not registered"):
                await svc.resolve_model(
                    config, {"model": "auto", "messages": [{"role": "user", "content": "test"}]}
                )

    async def test_missing_model_defaults_to_auto(self):
        """If model key is absent, treat as 'auto'."""
        svc = ChatService(_make_pool(), ENCRYPTION_KEY)
        config = _make_tenant_config()

        with patch.object(svc._engine, "evaluate", new_callable=AsyncMock) as mock_eval:
            mock_eval.return_value = RuleMatch(
                rule=config.rules[0],
                target_model="gpt-4o",
            )
            model, _match = await svc.resolve_model(
                config, {"messages": [{"role": "user", "content": "test"}]}
            )

        assert model.model_name == "gpt-4o"
        mock_eval.assert_called_once()


class TestComplete:
    """Test the full completion pipeline."""

    async def test_happy_path_non_streaming(self):
        pool = _make_pool()
        svc = ChatService(pool, ENCRYPTION_KEY)

        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"id": "chatcmpl-123", "choices": []}

        with (
            patch.object(svc, "load_tenant_config", new_callable=AsyncMock) as mock_load,
            patch.object(svc, "resolve_model", new_callable=AsyncMock) as mock_resolve,
            patch("bsgateway.chat.service.decrypt_value", return_value="sk-real-key"),
            patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response),
        ):
            mock_load.return_value = _make_tenant_config()
            model = TenantModel(
                model_name="gpt-4o",
                provider="openai",
                litellm_model="openai/gpt-4o",
                api_key_encrypted="enc_key",
            )
            mock_resolve.return_value = (model, None)

            result = await svc.complete(
                TENANT_ID,
                {"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}]},
            )

        assert result == mock_response

    async def test_litellm_called_with_correct_params(self):
        pool = _make_pool()
        svc = ChatService(pool, ENCRYPTION_KEY)

        mock_response = MagicMock()

        with (
            patch.object(svc, "load_tenant_config", new_callable=AsyncMock) as mock_load,
            patch.object(svc, "resolve_model", new_callable=AsyncMock) as mock_resolve,
            patch("bsgateway.chat.service.decrypt_value", return_value="sk-test-key"),
            patch(
                "litellm.acompletion",
                new_callable=AsyncMock,
                return_value=mock_response,
            ) as mock_acomp,
        ):
            config = _make_tenant_config()
            mock_load.return_value = config
            model = config.models["gpt-4o"]
            mock_resolve.return_value = (model, None)

            await svc.complete(
                TENANT_ID,
                {
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hello"}],
                    "temperature": 0.7,
                    "max_tokens": 100,
                },
            )

        call_kwargs = mock_acomp.call_args.kwargs
        assert call_kwargs["model"] == "openai/gpt-4o"
        assert call_kwargs["api_key"] == "sk-test-key"
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["max_tokens"] == 100
        assert call_kwargs["stream"] is False

    async def test_streaming_passes_stream_flag(self):
        pool = _make_pool()
        svc = ChatService(pool, ENCRYPTION_KEY)

        mock_response = AsyncMock()

        with (
            patch.object(svc, "load_tenant_config", new_callable=AsyncMock) as mock_load,
            patch.object(svc, "resolve_model", new_callable=AsyncMock) as mock_resolve,
            patch("bsgateway.chat.service.decrypt_value", return_value="sk-key"),
            patch(
                "litellm.acompletion",
                new_callable=AsyncMock,
                return_value=mock_response,
            ) as mock_acomp,
        ):
            mock_load.return_value = _make_tenant_config()
            model = _make_tenant_config().models["gpt-4o"]
            mock_resolve.return_value = (model, None)

            await svc.complete(
                TENANT_ID,
                {
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )

        assert mock_acomp.call_args.kwargs["stream"] is True

    async def test_no_api_key_still_works(self):
        """Models without encrypted keys should still call litellm (for local models)."""
        pool = _make_pool()
        svc = ChatService(pool, ENCRYPTION_KEY)

        mock_response = MagicMock()

        with (
            patch.object(svc, "load_tenant_config", new_callable=AsyncMock) as mock_load,
            patch.object(svc, "resolve_model", new_callable=AsyncMock) as mock_resolve,
            patch(
                "litellm.acompletion",
                new_callable=AsyncMock,
                return_value=mock_response,
            ) as mock_acomp,
        ):
            mock_load.return_value = _make_tenant_config()
            model = TenantModel(
                model_name="local-llm",
                provider="ollama",
                litellm_model="ollama/llama3",
                api_key_encrypted=None,  # No key needed
            )
            mock_resolve.return_value = (model, None)

            await svc.complete(
                TENANT_ID,
                {"model": "local-llm", "messages": [{"role": "user", "content": "hi"}]},
            )

        assert "api_key" not in mock_acomp.call_args.kwargs

    async def test_api_base_passed_to_litellm(self):
        pool = _make_pool()
        svc = ChatService(pool, ENCRYPTION_KEY)

        mock_response = MagicMock()

        with (
            patch.object(svc, "load_tenant_config", new_callable=AsyncMock) as mock_load,
            patch.object(svc, "resolve_model", new_callable=AsyncMock) as mock_resolve,
            patch("bsgateway.chat.service.decrypt_value", return_value="key"),
            patch(
                "litellm.acompletion",
                new_callable=AsyncMock,
                return_value=mock_response,
            ) as mock_acomp,
        ):
            mock_load.return_value = _make_tenant_config()
            model = TenantModel(
                model_name="custom",
                provider="openai",
                litellm_model="openai/gpt-4o",
                api_key_encrypted="enc",
                api_base="https://custom.api.com/v1",
            )
            mock_resolve.return_value = (model, None)

            await svc.complete(
                TENANT_ID,
                {"model": "custom", "messages": [{"role": "user", "content": "hi"}]},
            )

        assert mock_acomp.call_args.kwargs["api_base"] == "https://custom.api.com/v1"


class TestLoadTenantConfig:
    """Test TenantConfig batch loading from DB."""

    async def test_loads_rules_models_and_settings(self):
        from contextlib import asynccontextmanager

        rule_id = uuid4()
        model_id = uuid4()

        rule_rows = [
            {
                "id": rule_id,
                "tenant_id": TENANT_ID,
                "name": "test-rule",
                "priority": 1,
                "is_active": True,
                "is_default": False,
                "target_model": "gpt-4o",
                "created_at": None,
                "updated_at": None,
            }
        ]
        cond_rows = [
            {
                "id": uuid4(),
                "rule_id": rule_id,
                "condition_type": "token_count",
                "operator": "gt",
                "field": "estimated_tokens",
                "value": "100",
                "negate": False,
            }
        ]
        model_rows = [
            {
                "id": model_id,
                "tenant_id": TENANT_ID,
                "model_name": "gpt-4o",
                "provider": "openai",
                "litellm_model": "openai/gpt-4o",
                "api_key_encrypted": "enc_key",
                "api_base": None,
                "is_active": True,
                "extra_params": "{}",
            }
        ]
        tenant_row = {
            "id": TENANT_ID,
            "name": "Acme",
            "slug": "acme",
            "is_active": True,
            "settings": '{"rate_limit": {"rpm": 60}}',
            "created_at": None,
            "updated_at": None,
        }

        conn = AsyncMock()
        # 4 fetches: rules, conditions, models, intent_examples (5th query in load_tenant_config)
        conn.fetch = AsyncMock(side_effect=[rule_rows, cond_rows, model_rows, []])
        conn.fetchrow = AsyncMock(return_value=tenant_row)

        pool = AsyncMock()

        @asynccontextmanager
        async def mock_acquire():
            yield conn

        pool.acquire = mock_acquire

        svc = ChatService(pool, ENCRYPTION_KEY)

        with (
            patch("bsgateway.chat.service._sql") as mock_sql,
            patch("bsgateway.chat.service._rules_sql") as mock_rules_sql,
        ):
            mock_sql.query.side_effect = lambda q: q
            mock_rules_sql.query.side_effect = lambda q: q

            config = await svc.load_tenant_config(TENANT_ID)

        assert config.tenant_id == str(TENANT_ID)
        assert config.slug == "acme"
        assert len(config.rules) == 1
        assert config.rules[0].name == "test-rule"
        assert len(config.rules[0].conditions) == 1
        assert config.rules[0].conditions[0].condition_type == "token_count"
        assert "gpt-4o" in config.models
        assert config.settings == {"rate_limit": {"rpm": 60}}

    async def test_empty_tenant_has_no_rules_or_models(self):
        from contextlib import asynccontextmanager

        conn = AsyncMock()
        # 4 fetches: rules, conditions, models, intent_examples
        conn.fetch = AsyncMock(side_effect=[[], [], [], []])
        conn.fetchrow = AsyncMock(
            return_value={
                "id": TENANT_ID,
                "name": "Empty",
                "slug": "empty",
                "is_active": True,
                "settings": "{}",
                "created_at": None,
                "updated_at": None,
            }
        )

        pool = AsyncMock()

        @asynccontextmanager
        async def mock_acquire():
            yield conn

        pool.acquire = mock_acquire

        svc = ChatService(pool, ENCRYPTION_KEY)

        with (
            patch("bsgateway.chat.service._sql") as mock_sql,
            patch("bsgateway.chat.service._rules_sql") as mock_rules_sql,
        ):
            mock_sql.query.side_effect = lambda q: q
            mock_rules_sql.query.side_effect = lambda q: q

            config = await svc.load_tenant_config(TENANT_ID)

        assert config.rules == []
        assert config.models == {}


class TestLogRequest:
    """Test fire-and-forget logging."""

    async def test_log_request_does_not_raise(self):
        """Logging errors should be swallowed, not propagate."""
        from bsgateway.tests.conftest import MockAcquire

        pool = _make_pool()
        conn = AsyncMock()
        conn.execute = AsyncMock(side_effect=Exception("DB error"))
        pool.acquire.return_value = MockAcquire(conn)

        svc = ChatService(pool, ENCRYPTION_KEY)

        with patch("bsgateway.chat.service._sql") as mock_log_sql:
            mock_log_sql.query.side_effect = lambda q: q

            # Should not raise
            await svc._log_request(
                TENANT_ID,
                None,
                {"messages": [{"role": "user", "content": "test"}], "model": "auto"},
                TenantModel(
                    model_name="gpt-4o",
                    provider="openai",
                    litellm_model="openai/gpt-4o",
                ),
            )

    async def test_budget_tracking_with_redis(self):
        """Verify _log_request increments budget tracker when redis is present."""
        pool = _make_pool()
        mock_redis = AsyncMock()
        svc = ChatService(pool, ENCRYPTION_KEY, redis=mock_redis)

        with (
            patch("bsgateway.chat.service._sql") as mock_log_sql,
            patch(
                "bsgateway.rules.budget.BudgetTracker.increment_request_count",
                new_callable=AsyncMock,
            ) as mock_budget,
        ):
            mock_log_sql.query.side_effect = lambda q: q

            await svc._log_request(
                TENANT_ID,
                None,
                {"messages": [{"role": "user", "content": "test"}], "model": "auto"},
                TenantModel(
                    model_name="gpt-4o",
                    provider="openai",
                    litellm_model="openai/gpt-4o",
                ),
            )

        mock_budget.assert_called_once_with(str(TENANT_ID))
