"""Audit Sprint 0 follow-up (docs/TODO.md S1): plumb tenant_id all the
way to ``data["metadata"]["tenant_id"]`` so the LiteLLM proxy callback
records the originating tenant.

Pre-fix:

* ``ChatService.complete`` resolves ``tenant_id`` from the authenticated
  request, but it is **not** propagated into the ``metadata`` argument
  passed to ``litellm.acompletion``. The hook's ``async_pre_call_hook``
  therefore sees ``data["metadata"]`` without ``tenant_id`` and
  ``RoutingCollector.record`` fall-backs to skip-with-debug.
* The proxy-direct path (a request that hits LiteLLM with the gateway
  master key but never traverses the chat router) had no path to
  resolve a tenant at all — even for legitimate proxy users.

Post-fix:

* ``ChatService.complete`` injects
  ``litellm_kwargs["metadata"]["tenant_id"] = str(tenant_id)`` before
  delegating to ``litellm.acompletion``.
* The hook's ``_extract_tenant_id`` additionally consults the LiteLLM
  ``UserAPIKeyAuth`` payload (``team_id``, ``metadata.tenant_id``)
  when ``data["metadata"]["tenant_id"]`` is absent.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from bsgateway.chat.service import ChatService
from bsgateway.routing.hook import BSGatewayRouter
from bsgateway.routing.models import (
    ClassifierConfig,
    ClassifierWeights,
    CollectorConfig,
    RoutingConfig,
    TierConfig,
)
from bsgateway.rules.models import (
    RoutingRule,
    RuleMatch,
    TenantConfig,
    TenantModel,
)
from bsgateway.tests.conftest import make_mock_pool


@pytest.fixture
def mock_litellm_response() -> MagicMock:
    response = MagicMock()
    response.model_dump = MagicMock(return_value={"choices": []})
    return response


class TestChatServiceInjectsTenantIdMetadata:
    """``ChatService.complete`` must put tenant_id into the litellm
    metadata so the downstream BSGateway hook can scope its log."""

    @pytest.mark.asyncio
    async def test_litellm_acompletion_receives_tenant_id_in_metadata(
        self,
        mock_litellm_response: MagicMock,
    ) -> None:
        pool, _conn = make_mock_pool()
        encryption_key = b"\x00" * 32
        svc = ChatService(pool, encryption_key)

        tenant_id = uuid4()

        # Pre-build a tenant config that resolves directly to a model
        # so we skip the rule-engine path and exercise the litellm call.
        model = TenantModel(
            model_name="gpt-4o-mini",
            provider="openai",
            litellm_model="openai/gpt-4o-mini",
            api_key_encrypted=None,
            api_base=None,
            extra_params=None,
        )
        tenant_config = TenantConfig(
            tenant_id=str(tenant_id),
            slug="t",
            models={"gpt-4o-mini": model},
            rules=[],
            settings={},
            embedding_settings=None,
            intent_definitions=[],
        )

        with (
            patch.object(svc, "load_tenant_config", new=AsyncMock(return_value=tenant_config)),
            patch("bsgateway.chat.service.litellm") as mock_litellm,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            await svc.complete(
                tenant_id,
                {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )

        kwargs = mock_litellm.acompletion.call_args.kwargs
        metadata = kwargs.get("metadata") or {}
        assert metadata.get("tenant_id") == str(tenant_id), (
            "ChatService must inject tenant_id into the litellm metadata so "
            "BSGatewayRouter._extract_tenant_id can scope routing_logs writes"
        )

    @pytest.mark.asyncio
    async def test_existing_metadata_is_preserved(
        self,
        mock_litellm_response: MagicMock,
    ) -> None:
        """If the caller passed metadata of their own (e.g. trace ids),
        we must merge rather than clobber."""
        pool, _conn = make_mock_pool()
        encryption_key = b"\x00" * 32
        svc = ChatService(pool, encryption_key)

        tenant_id = uuid4()
        model = TenantModel(
            model_name="gpt-4o-mini",
            provider="openai",
            litellm_model="openai/gpt-4o-mini",
            api_key_encrypted=None,
            api_base=None,
            extra_params=None,
        )
        tenant_config = TenantConfig(
            tenant_id=str(tenant_id),
            slug="t",
            models={"gpt-4o-mini": model},
            rules=[],
            settings={},
            embedding_settings=None,
            intent_definitions=[],
        )

        # Caller-supplied metadata must survive.
        with (
            patch.object(svc, "load_tenant_config", new=AsyncMock(return_value=tenant_config)),
            patch("bsgateway.chat.service.litellm") as mock_litellm,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            await svc.complete(
                tenant_id,
                {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "hi"}],
                    "metadata": {"trace_id": "abc-123"},
                },
            )

        kwargs = mock_litellm.acompletion.call_args.kwargs
        metadata = kwargs.get("metadata") or {}
        assert metadata.get("tenant_id") == str(tenant_id)
        assert metadata.get("trace_id") == "abc-123", (
            "caller-supplied metadata fields must be preserved when tenant_id is injected"
        )


class TestHookExtractTenantIdFromUserAPIKey:
    """For proxy-direct traffic (no BSGateway chat router hop) the hook
    can fall back to the ``UserAPIKeyAuth`` payload. LiteLLM commonly
    surfaces tenant identifiers as ``team_id`` or as a ``metadata``
    dict on the auth object."""

    @pytest.fixture
    def routing_config(self) -> RoutingConfig:
        return RoutingConfig(
            tiers=[TierConfig(name="medium", score_range=(0, 100), model="gpt-4o-mini")],
            classifier=ClassifierConfig(weights=ClassifierWeights()),
            fallback_tier="medium",
            classifier_strategy="static",
            collector=CollectorConfig(enabled=False),
        )

    @pytest.fixture
    def router(self, routing_config: RoutingConfig) -> BSGatewayRouter:
        return BSGatewayRouter(config=routing_config)

    def test_extract_falls_back_to_user_api_key_metadata(self, router: BSGatewayRouter) -> None:
        tenant_id = uuid4()
        user_api_key = MagicMock()
        user_api_key.metadata = {"tenant_id": str(tenant_id)}
        user_api_key.team_id = None

        data: dict = {}  # No data["metadata"]["tenant_id"]

        result = router._extract_tenant_id(data, user_api_key=user_api_key)
        assert result == tenant_id

    def test_extract_falls_back_to_user_api_key_team_id(self, router: BSGatewayRouter) -> None:
        tenant_id = uuid4()
        user_api_key = MagicMock()
        # No metadata field, but team_id is set.
        user_api_key.metadata = None
        user_api_key.team_id = str(tenant_id)

        data: dict = {}

        result = router._extract_tenant_id(data, user_api_key=user_api_key)
        assert result == tenant_id

    def test_data_metadata_takes_priority_over_user_api_key(self, router: BSGatewayRouter) -> None:
        """If both are present, prefer the explicit data["metadata"]
        value — it is the active runtime decision rather than the
        cached key claim."""
        tenant_in_data = uuid4()
        tenant_in_key = uuid4()
        assert tenant_in_data != tenant_in_key

        user_api_key = MagicMock()
        user_api_key.metadata = {"tenant_id": str(tenant_in_key)}

        data = {"metadata": {"tenant_id": str(tenant_in_data)}}

        result = router._extract_tenant_id(data, user_api_key=user_api_key)
        assert result == tenant_in_data

    def test_returns_none_when_no_source_provides_tenant_id(self, router: BSGatewayRouter) -> None:
        user_api_key = MagicMock()
        user_api_key.metadata = None
        user_api_key.team_id = None

        result = router._extract_tenant_id({}, user_api_key=user_api_key)
        assert result is None

    def test_invalid_uuid_in_user_api_key_returns_none(self, router: BSGatewayRouter) -> None:
        user_api_key = MagicMock()
        user_api_key.metadata = {"tenant_id": "not-a-uuid"}
        user_api_key.team_id = None

        result = router._extract_tenant_id({}, user_api_key=user_api_key)
        assert result is None

    def test_signature_remains_backward_compatible(self, router: BSGatewayRouter) -> None:
        """The new ``user_api_key`` arg must be optional so existing
        call sites that only pass ``data`` keep working."""
        tenant_id = uuid4()
        result = router._extract_tenant_id({"metadata": {"tenant_id": str(tenant_id)}})
        assert result == tenant_id


class TestHookAutoRoutePassesUserAPIKeyToExtract:
    """The hook actually plumbs ``user_api_key_dict`` into
    ``_extract_tenant_id`` during ``async_pre_call_hook``."""

    @pytest.mark.asyncio
    async def test_proxy_direct_traffic_logs_with_tenant(self) -> None:
        from bsgateway.routing.classifiers.base import ClassificationResult

        config = RoutingConfig(
            tiers=[TierConfig(name="medium", score_range=(0, 100), model="gpt-4o-mini")],
            classifier=ClassifierConfig(weights=ClassifierWeights()),
            fallback_tier="medium",
            classifier_strategy="static",
            collector=CollectorConfig(enabled=False),
        )
        router = BSGatewayRouter(config=config)
        # Stand up a fake collector so we can pin the tenant arg.
        fake_collector = MagicMock()
        fake_collector.record = AsyncMock()
        router.collector = fake_collector
        router.classifier.classify = AsyncMock(
            return_value=ClassificationResult(tier="medium", strategy="static", score=50)
        )

        tenant_id = uuid4()
        user_api_key = MagicMock()
        user_api_key.metadata = {"tenant_id": str(tenant_id)}
        user_api_key.team_id = None

        # The proxy-direct request supplies no tenant_id in data["metadata"].
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
        }

        await router.async_pre_call_hook(user_api_key, MagicMock(), data, "completion")
        # Allow the asyncio.create_task'd record() to run.
        import asyncio

        for _ in range(5):
            if fake_collector.record.await_count >= 1:
                break
            await asyncio.sleep(0)

        fake_collector.record.assert_awaited_once()
        kwargs = fake_collector.record.call_args.kwargs
        assert kwargs["tenant_id"] == tenant_id
        # Sanity: it should be a UUID, not a string.
        assert isinstance(kwargs["tenant_id"], UUID)


class TestRuleMatchUnused:
    """Smoke check that we don't accidentally regress RuleMatch import."""

    def test_rule_match_imports(self) -> None:
        # Just exercises the import to keep linters from pruning it
        # if a future refactor needs to inspect rule resolution.
        assert RuleMatch is not None
        assert RoutingRule is not None
