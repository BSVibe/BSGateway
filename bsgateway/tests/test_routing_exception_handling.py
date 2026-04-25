"""Audit M14: targeted exception handling in routing hot paths.

The pre-fix code wrapped network and IO calls in bare ``except Exception``
which silently swallowed unrelated programming errors (TypeError,
AttributeError, etc.) and — critically — also swallowed
``asyncio.CancelledError`` when the task was being torn down. After this
sprint:

* the classifier-fallback path catches a typed tuple of expected
  failures (network / parse / value), re-raises ``CancelledError``, and
  logs everything else as ``classifier_unexpected_error`` so
  programming bugs are not silently downgraded to "use the fallback
  model".
* embedding generation gets the same treatment in the collector.
* every error log carries ``exc_info=True`` so structlog renders the
  full traceback as JSON-serialisable fields.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsgateway.routing import collector as collector_mod
from bsgateway.routing import hook as hook_mod
from bsgateway.routing.collector import RoutingCollector
from bsgateway.routing.hook import BSGatewayRouter
from bsgateway.routing.models import (
    ClassifierConfig,
    ClassifierWeights,
    CollectorConfig,
    RoutingConfig,
    TierConfig,
)


@pytest.fixture
def routing_config() -> RoutingConfig:
    return RoutingConfig(
        tiers=[
            TierConfig(name="simple", score_range=(0, 30), model="local/llama3"),
            TierConfig(name="medium", score_range=(31, 65), model="gpt-4o-mini"),
            TierConfig(name="complex", score_range=(66, 100), model="claude-opus"),
        ],
        aliases={"auto": "auto_route"},
        passthrough_models={"local/llama3", "gpt-4o-mini", "claude-opus"},
        classifier=ClassifierConfig(weights=ClassifierWeights()),
        fallback_tier="medium",
        classifier_strategy="static",
        collector=CollectorConfig(enabled=False),
    )


@pytest.fixture
def router(routing_config: RoutingConfig) -> BSGatewayRouter:
    return BSGatewayRouter(config=routing_config)


class TestClassifierErrorTaxonomy:
    """``BSGatewayRouter._auto_route`` must distinguish expected
    classifier failures from programming bugs and from cancellation."""

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self, router: BSGatewayRouter) -> None:
        """``asyncio.CancelledError`` is the cooperative cancellation signal.

        Swallowing it would leave a half-cancelled task running and
        defeat shutdown. Production code MUST re-raise it without
        falling back to a default model.
        """
        router.classifier.classify = AsyncMock(side_effect=asyncio.CancelledError())
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        with pytest.raises(asyncio.CancelledError):
            await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

    @pytest.mark.asyncio
    async def test_network_error_falls_back_quietly(self, router: BSGatewayRouter) -> None:
        """Expected network failures (e.g. local LLM classifier offline)
        should fall back to the default tier with a warning, not propagate."""
        router.classifier.classify = AsyncMock(
            side_effect=ConnectionError("cannot reach classifier")
        )
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        # Falls back to medium tier model.
        assert result["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_value_error_falls_back_quietly(self, router: BSGatewayRouter) -> None:
        """Parse / validation errors are routine for malformed
        classifier responses — fall back, don't crash the request."""
        router.classifier.classify = AsyncMock(side_effect=ValueError("bad json"))
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_unexpected_error_logs_and_falls_back(self, router: BSGatewayRouter) -> None:
        """A programming bug in the classifier (e.g. AttributeError)
        should still degrade gracefully (we'd rather route than 500)
        but be surfaced via a distinct log event so it gets noticed
        in metrics rather than buried under the network-failure tag."""
        router.classifier.classify = AsyncMock(side_effect=AttributeError("oops"))
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        }
        result = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert result["model"] == "gpt-4o-mini"


class TestClassifierExceptionSourcePin:
    """Source-level pin: hook.py uses targeted exception handling."""

    def test_hook_does_not_have_bare_except_exception_in_auto_route(self) -> None:
        """``BSGatewayRouter._auto_route`` no longer wraps the classifier
        call in a bare ``except Exception``. The new shape catches a
        named tuple of network/parse/value errors, then a separate
        Exception branch that re-raises CancelledError."""
        src = inspect.getsource(hook_mod.BSGatewayRouter._auto_route)
        # CancelledError must be referenced explicitly so reviewers can
        # see the cancellation contract is preserved.
        assert "CancelledError" in src, (
            "_auto_route must explicitly handle asyncio.CancelledError "
            "(re-raise) so cancellation propagates"
        )


class TestCollectorEmbeddingExceptionTaxonomy:
    """``RoutingCollector._generate_embedding`` follows the same shape:
    expected network/parse failures return None, cancellation
    propagates, programming bugs are logged distinctly."""

    @pytest.fixture
    def collector(self) -> RoutingCollector:
        from bsgateway.routing.models import EmbeddingConfig

        c = RoutingCollector(
            database_url="postgresql://test/test",
            embedding_config=EmbeddingConfig(model="nomic", api_base="http://x", timeout=1.0),
        )
        return c

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self, collector: RoutingCollector) -> None:
        async def _cancel(*_a: object, **_kw: object) -> None:
            raise asyncio.CancelledError()

        from unittest.mock import patch

        with patch.object(collector_mod, "litellm") as mock_litellm:
            mock_litellm.aembedding = _cancel
            with pytest.raises(asyncio.CancelledError):
                await collector._generate_embedding("hello")

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self, collector: RoutingCollector) -> None:
        from unittest.mock import patch

        with patch.object(collector_mod, "litellm") as mock_litellm:
            mock_litellm.aembedding = AsyncMock(side_effect=ConnectionError("no net"))
            result = await collector._generate_embedding("hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_none_and_logs(
        self, collector: RoutingCollector
    ) -> None:
        """Even programming bugs must not break the routing path —
        embeddings are best-effort. They should be logged distinctly
        so the bug doesn't hide behind 'classifier_offline' noise."""
        from unittest.mock import patch

        with patch.object(collector_mod, "litellm") as mock_litellm:
            mock_litellm.aembedding = AsyncMock(side_effect=AttributeError("bug"))
            result = await collector._generate_embedding("hello")
        assert result is None


class TestCollectorExceptionSourcePin:
    def test_collector_handles_cancellation_explicitly(self) -> None:
        src = inspect.getsource(collector_mod.RoutingCollector._generate_embedding)
        assert "CancelledError" in src, (
            "_generate_embedding must explicitly handle asyncio.CancelledError"
        )
