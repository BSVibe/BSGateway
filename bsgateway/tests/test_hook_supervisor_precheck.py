"""Phase 0 P0.7 — LiteLLM proxy hook absorbs BSupervisor run.pre/run.post.

Architectural shift (Lockin §2 #1): BSGateway now calls BSupervisor with
run.pre BEFORE dispatching to the upstream LLM, and fires run.post after
the call returns. BSNexus no longer calls BSupervisor directly for
LLM events.

These tests pin the contract that BSGateway:

1. Builds ``RunMetadata`` from ``data["metadata"]`` (which BSNexus sets via
   the LiteLLM proxy callback metadata bag).
2. Calls ``BSupervisorClient.run_pre`` synchronously inside
   ``async_pre_call_hook`` with a 200ms timeout.
3. On a denial (allowed=false), aborts the request by raising
   ``litellm.exceptions.BadRequestError`` (LiteLLM-native abort).
4. Schedules ``run_post`` fire-and-forget after success (via
   LiteLLM ``async_log_success_event``) and failure (via
   ``async_log_failure_event``).
5. **Skips** the precheck when ``BSupervisorClient`` is not configured —
   BSGateway must keep working when BSupervisor is unavailable (Noop).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from bsgateway.routing.classifiers.base import ClassificationResult
from bsgateway.routing.hook import BSGatewayRouter
from bsgateway.routing.models import (
    ClassifierConfig,
    ClassifierWeights,
    CollectorConfig,
    RoutingConfig,
    TierConfig,
)
from bsgateway.supervisor.client import AuditResult


def _make_router() -> BSGatewayRouter:
    config = RoutingConfig(
        tiers=[TierConfig(name="medium", score_range=(0, 100), model="gpt-4o-mini")],
        classifier=ClassifierConfig(weights=ClassifierWeights()),
        fallback_tier="medium",
        classifier_strategy="static",
        collector=CollectorConfig(enabled=False),
    )
    router = BSGatewayRouter(config=config)
    router.classifier.classify = AsyncMock(
        return_value=ClassificationResult(tier="medium", strategy="static", score=50)
    )
    return router


@pytest.mark.asyncio
class TestHookCallsRunPre:
    async def test_run_pre_called_with_metadata_from_request(self) -> None:
        router = _make_router()
        sup = MagicMock()
        sup.run_pre = AsyncMock(return_value=AuditResult(blocked=False))
        sup.run_post = AsyncMock()
        router.supervisor = sup

        tenant_id = uuid4()
        run_id = uuid4()
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {
                "tenant_id": str(tenant_id),
                "run_id": str(run_id),
                "project_id": "proj-1",
                "request_id": "req-1",
                "agent_name": "founder-arch",
                "composition_id": "comp-1",
                "cost_estimate_cents": 5,
                "parent_run_id": None,
            },
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

        sup.run_pre.assert_awaited_once()
        meta = sup.run_pre.await_args.args[0]
        assert meta.tenant_id == str(tenant_id)
        assert meta.run_id == str(run_id)
        assert meta.project_id == "proj-1"
        assert meta.request_id == "req-1"
        assert meta.agent_name == "founder-arch"
        assert meta.composition_id == "comp-1"
        assert meta.cost_estimate_cents == 5
        # Resolved model is what BSupervisor sees (post-routing).
        assert meta.model == "gpt-4o-mini"

    async def test_request_aborted_when_supervisor_blocks(self) -> None:
        router = _make_router()
        sup = MagicMock()
        sup.run_pre = AsyncMock(
            return_value=AuditResult(blocked=True, reason="policy", degraded=False)
        )
        sup.run_post = AsyncMock()
        router.supervisor = sup

        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {
                "tenant_id": str(uuid4()),
                "run_id": str(uuid4()),
                "project_id": "p",
                "request_id": "r",
                "agent_name": "a",
            },
        }
        # Hook must raise to short-circuit the dispatch. BSGateway raises
        # the LiteLLM-native exception so existing error paths apply.
        with pytest.raises(Exception) as excinfo:
            await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        # The exception class name signals we abort via litellm-aware error;
        # we don't bind to the exact symbol because litellm may rename it.
        msg = str(excinfo.value).lower()
        assert "policy" in msg or "blocked" in msg or "denied" in msg

    async def test_run_pre_skipped_for_non_completion_call_types(self) -> None:
        router = _make_router()
        sup = MagicMock()
        sup.run_pre = AsyncMock(return_value=AuditResult(blocked=False))
        router.supervisor = sup
        await router.async_pre_call_hook(
            MagicMock(),
            MagicMock(),
            {"model": "any", "input": "hi"},
            "embeddings",
        )
        sup.run_pre.assert_not_called()

    async def test_no_supervisor_configured_is_noop(self) -> None:
        """When BSupervisor is unconfigured the router proceeds without
        any precheck — degraded mode preserved (Lockin §10.4)."""
        router = _make_router()
        router.supervisor = None  # explicit Noop
        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"tenant_id": str(uuid4())},
        }
        # Should not raise.
        out = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        assert out["model"] == "gpt-4o-mini"

    async def test_run_pre_skipped_when_no_run_id_in_metadata(self) -> None:
        """Pure proxy traffic (no BSNexus dispatching) carries no run_id.
        The router must not synthesise audit events in that case — there is
        nothing for BSupervisor to correlate against, and we'd inflate event
        ingestion. Only proceed when a run_id is supplied."""
        router = _make_router()
        sup = MagicMock()
        sup.run_pre = AsyncMock(return_value=AuditResult(blocked=False))
        router.supervisor = sup

        data = {
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"tenant_id": str(uuid4())},  # no run_id
        }
        await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")
        sup.run_pre.assert_not_called()


@pytest.mark.asyncio
class TestHookSchedulesRunPost:
    async def test_async_log_success_schedules_run_post(self) -> None:
        router = _make_router()
        sup = MagicMock()
        sup.run_post = AsyncMock()
        router.supervisor = sup

        kwargs = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {
                "tenant_id": str(uuid4()),
                "run_id": str(uuid4()),
                "project_id": "p",
                "request_id": "r",
                "agent_name": "founder",
            },
        }
        # Simulate LiteLLM's success event payload.
        response_obj = MagicMock()
        response_obj.usage = MagicMock(prompt_tokens=10, completion_tokens=20)

        await router.async_log_success_event(kwargs, response_obj, 0.0, 0.5)
        # The post is fire-and-forget — give the loop a tick to run it.
        for _ in range(10):
            if sup.run_post.await_count >= 1:
                break
            await asyncio.sleep(0)

        sup.run_post.assert_awaited_once()
        kw = sup.run_post.await_args.kwargs
        assert kw["status"] == "success"
        assert kw["tokens_in"] == 10
        assert kw["tokens_out"] == 20

    async def test_async_log_failure_schedules_run_post_with_error(self) -> None:
        router = _make_router()
        sup = MagicMock()
        sup.run_post = AsyncMock()
        router.supervisor = sup

        kwargs = {
            "model": "gpt-4o-mini",
            "metadata": {
                "tenant_id": str(uuid4()),
                "run_id": str(uuid4()),
                "project_id": "p",
                "request_id": "r",
                "agent_name": "founder",
            },
        }
        await router.async_log_failure_event(kwargs, "RateLimitError: 429", 0.0, 0.5)
        for _ in range(10):
            if sup.run_post.await_count >= 1:
                break
            await asyncio.sleep(0)

        sup.run_post.assert_awaited_once()
        kw = sup.run_post.await_args.kwargs
        assert kw["status"] == "error"
        assert "RateLimitError" in str(kw.get("error", ""))

    async def test_run_post_skipped_when_no_run_id(self) -> None:
        router = _make_router()
        sup = MagicMock()
        sup.run_post = AsyncMock()
        router.supervisor = sup
        kwargs = {"model": "gpt-4o-mini", "metadata": {"tenant_id": str(uuid4())}}

        await router.async_log_success_event(kwargs, MagicMock(), 0.0, 0.5)
        await asyncio.sleep(0)
        sup.run_post.assert_not_called()
