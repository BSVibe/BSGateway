"""Tests for ChatService intent classifier wiring.

These tests focus on the contract between ChatService and the embedding layer:
when does it build a classifier, when does it skip, and does it pass through
correctly to the rule engine.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from bsgateway.chat.service import ChatService
from bsgateway.embedding.serialization import serialize_embedding
from bsgateway.embedding.settings import EmbeddingSettings
from bsgateway.rules.intent import IntentDefinition
from bsgateway.rules.models import (
    RoutingRule,
    RuleCondition,
    TenantConfig,
    TenantModel,
)

TENANT_ID = uuid4()
ENCRYPTION_KEY = bytes.fromhex("a" * 64)


def _config_with_intent(
    *,
    embedding_settings: EmbeddingSettings | None,
    intent_definitions: list[IntentDefinition] | None = None,
) -> TenantConfig:
    return TenantConfig(
        tenant_id=str(TENANT_ID),
        slug="acme",
        models={
            "gpt-4o": TenantModel(
                model_name="gpt-4o",
                provider="openai",
                litellm_model="openai/gpt-4o",
                api_key_encrypted="enc",
            )
        },
        rules=[
            RoutingRule(
                id=str(uuid4()),
                tenant_id=str(TENANT_ID),
                name="intent-rule",
                priority=1,
                is_active=True,
                is_default=False,
                target_model="gpt-4o",
                conditions=[
                    RuleCondition(
                        condition_type="intent",
                        field="classified_intent",
                        operator="eq",
                        value="code-review",
                    )
                ],
            ),
        ],
        embedding_settings=embedding_settings,
        intent_definitions=intent_definitions or [],
    )


class TestBuildIntentClassifier:
    def test_returns_none_when_no_embedding_settings(self):
        config = _config_with_intent(embedding_settings=None)
        assert ChatService._build_intent_classifier(config) is None

    def test_returns_none_when_no_intent_definitions(self):
        config = _config_with_intent(
            embedding_settings=EmbeddingSettings(model="text-embedding-3-small"),
            intent_definitions=[],
        )
        assert ChatService._build_intent_classifier(config) is None

    def test_builds_classifier_when_settings_and_intents_present(self):
        config = _config_with_intent(
            embedding_settings=EmbeddingSettings(model="text-embedding-3-small"),
            intent_definitions=[
                IntentDefinition(
                    name="code-review",
                    example_embeddings=[[0.1, 0.2, 0.3]],
                )
            ],
        )
        classifier = ChatService._build_intent_classifier(config)
        assert classifier is not None


class TestResolveModelPassesClassifier:
    @pytest.mark.asyncio
    async def test_passes_classifier_to_engine_when_intents_match(self):
        from bsgateway.tests.conftest import make_mock_pool

        pool, _ = make_mock_pool()
        svc = ChatService(pool, ENCRYPTION_KEY)

        config = _config_with_intent(
            embedding_settings=EmbeddingSettings(model="text-embedding-3-small"),
            intent_definitions=[
                IntentDefinition(
                    name="code-review",
                    example_embeddings=[[0.1, 0.2, 0.3]],
                )
            ],
        )

        with patch.object(svc._engine, "evaluate", new_callable=AsyncMock) as mock_evaluate:
            mock_evaluate.return_value = type(
                "M",
                (),
                {"target_model": "gpt-4o", "rule": type("R", (), {"name": "intent-rule"})()},
            )()
            await svc.resolve_model(config, {"model": "auto", "messages": []})

        mock_evaluate.assert_awaited_once()
        call_kwargs = mock_evaluate.call_args.kwargs
        assert call_kwargs["intent_classifier"] is not None

    @pytest.mark.asyncio
    async def test_passes_none_when_no_embedding_settings(self):
        from bsgateway.tests.conftest import make_mock_pool

        pool, _ = make_mock_pool()
        svc = ChatService(pool, ENCRYPTION_KEY)

        config = _config_with_intent(embedding_settings=None)

        with patch.object(svc._engine, "evaluate", new_callable=AsyncMock) as mock_evaluate:
            mock_evaluate.return_value = type(
                "M",
                (),
                {"target_model": "gpt-4o", "rule": type("R", (), {"name": "intent-rule"})()},
            )()
            await svc.resolve_model(config, {"model": "auto", "messages": []})

        assert mock_evaluate.call_args.kwargs["intent_classifier"] is None


class TestLoadTenantConfigHydratesIntents:
    @pytest.mark.asyncio
    async def test_loads_intent_examples_with_active_model(self):
        from contextlib import asynccontextmanager

        emb = serialize_embedding([0.1, 0.2])
        intent_rows = [
            {
                "intent_name": "code-review",
                "embedding": emb,
                "embedding_model": "text-embedding-3-small",
                "threshold": 0.7,
            }
        ]
        tenant_row = {
            "id": TENANT_ID,
            "name": "Acme",
            "slug": "acme",
            "is_active": True,
            "settings": '{"embedding": {"model": "text-embedding-3-small"}}',
            "created_at": None,
            "updated_at": None,
        }

        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=[[], [], [], intent_rows])
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

        assert config.embedding_settings is not None
        assert config.embedding_settings.model == "text-embedding-3-small"
        assert len(config.intent_definitions) == 1
        assert config.intent_definitions[0].name == "code-review"

    @pytest.mark.asyncio
    async def test_drops_stale_intent_examples(self):
        from contextlib import asynccontextmanager

        emb = serialize_embedding([0.1, 0.2])
        intent_rows = [
            {
                "intent_name": "code-review",
                "embedding": emb,
                "embedding_model": "old-model",
                "threshold": 0.7,
            }
        ]
        tenant_row = {
            "id": TENANT_ID,
            "name": "Acme",
            "slug": "acme",
            "is_active": True,
            "settings": '{"embedding": {"model": "new-model"}}',
            "created_at": None,
            "updated_at": None,
        }

        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=[[], [], [], intent_rows])
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

        # Intent existed but its only embedding was stale → no usable intent
        assert config.intent_definitions == []
