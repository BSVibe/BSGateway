"""End-to-end Phase 0 P0.7 — BSGateway dispatching an LLM call routes
``run.pre`` and ``run.post`` to a mock BSupervisor.

This is the integration-level guard that the architectural shift in
Lockin §2 #1 actually fires the right HTTP calls with the right
headers + body, exercised through ``BSGatewayRouter.async_pre_call_hook``
and ``async_log_success_event``.

Mocks (everything outside BSGateway):
- BSVibe-Auth ``POST /api/oauth/token`` (OAuth2 client_credentials) —
  returns a deterministic service JWT.
- BSupervisor ``POST /api/events`` — captures payloads.
- LiteLLM is not invoked; we drive the hook directly.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
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
from bsgateway.supervisor import BSupervisorClient, ServiceTokenMinter


def _routing_config() -> RoutingConfig:
    return RoutingConfig(
        tiers=[TierConfig(name="medium", score_range=(0, 100), model="gpt-4o-mini")],
        classifier=ClassifierConfig(weights=ClassifierWeights()),
        fallback_tier="medium",
        classifier_strategy="static",
        collector=CollectorConfig(enabled=False),
    )


def _make_router_with_supervisor(
    *,
    supervisor_response: dict | None = None,
) -> tuple[BSGatewayRouter, list[dict], list[dict]]:
    """Build a BSGatewayRouter wired to a mock BSupervisor over a real
    ``BSupervisorClient`` (we patch httpx.AsyncClient.post to capture
    calls)."""
    minter = ServiceTokenMinter(
        auth_url="https://auth.bsvibe.test",
        client_id="bsgateway-test",
        client_secret="bootstrap-secret",
        audience="bsupervisor",
        scope=["bsupervisor:audit.write"],
    )
    client = BSupervisorClient(
        base_url="https://api-supervisor.bsvibe.test",
        token_minter=minter,
        timeout_ms=2000,  # extra headroom for unit tests
        fail_mode="open",
    )

    router = BSGatewayRouter(config=_routing_config())
    router.classifier.classify = AsyncMock(
        return_value=ClassificationResult(tier="medium", strategy="static", score=50)
    )
    router.attach_supervisor(client)

    auth_calls: list[dict] = []
    sup_calls: list[dict] = []

    auth_token_resp = MagicMock(spec=httpx.Response)
    auth_token_resp.status_code = 200
    auth_token_resp.json = MagicMock(
        return_value={"access_token": "svc.jwt.zz", "expires_in": 600, "token_type": "service"}
    )
    auth_token_resp.raise_for_status = MagicMock(return_value=None)

    sup_resp = MagicMock(spec=httpx.Response)
    sup_resp.status_code = 201
    sup_resp.json = MagicMock(
        return_value=supervisor_response or {"event_id": "evt", "allowed": True}
    )
    sup_resp.raise_for_status = MagicMock(return_value=None)

    async def _mocked_post(*args, **kw):
        # bsvibe-authz refactored ServiceTokenMinter onto HttpClientBase
        # (post-67da60e), so ``url`` arrives positionally now. BSupervisor
        # client still calls with ``url=...`` kwarg. Accept both shapes.
        url = kw.pop("url", None) or (args[0] if args else None)
        headers = kw.get("headers")
        if url and url.endswith("/api/oauth/token"):
            auth_calls.append({"url": url, "data": kw.get("data"), "headers": headers})
            return auth_token_resp
        if url and url.endswith("/api/events"):
            sup_calls.append({"url": url, "json": kw.get("json"), "headers": headers})
            return sup_resp
        raise AssertionError(f"unexpected URL {url!r}")

    # Apply once for the duration of the test through monkeypatch in the
    # caller — we expose the spy through closures.
    router._auth_calls = auth_calls  # type: ignore[attr-defined]
    router._sup_calls = sup_calls  # type: ignore[attr-defined]
    router._mocked_post = _mocked_post  # type: ignore[attr-defined]
    return router, auth_calls, sup_calls


@pytest.mark.asyncio
async def test_e2e_run_pre_uses_minted_service_token_and_hits_events(monkeypatch) -> None:
    router, auth_calls, sup_calls = _make_router_with_supervisor(
        supervisor_response={"event_id": "evt-pre", "allowed": True}
    )
    monkeypatch.setattr("httpx.AsyncClient.post", AsyncMock(side_effect=router._mocked_post))

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
            "cost_estimate_cents": 7,
        },
    }
    out = await router.async_pre_call_hook(MagicMock(), MagicMock(), data, "completion")

    # The hook resolved the model.
    assert out["model"] == "gpt-4o-mini"

    # Service JWT was minted exactly once via OAuth2 client_credentials.
    import base64

    assert len(auth_calls) == 1
    body = auth_calls[0]["data"]
    assert body["grant_type"] == "client_credentials"
    assert body["audience"] == "bsupervisor"
    assert body["scope"] == "bsupervisor:audit.write"
    auth_header = auth_calls[0]["headers"]["Authorization"]
    assert auth_header.startswith("Basic ")
    decoded = base64.b64decode(auth_header[len("Basic ") :]).decode()
    assert decoded == "bsgateway-test:bootstrap-secret"

    # BSupervisor saw the run.pre event with full metadata.
    assert len(sup_calls) == 1
    pre_body = sup_calls[0]["json"]
    assert pre_body["event_type"] == "run.pre"
    assert pre_body["action"] == "llm.dispatch"
    assert pre_body["source"] == "bsgateway"
    assert pre_body["agent_id"] == "founder-arch"
    assert pre_body["target"] == "gpt-4o-mini"
    assert pre_body["metadata"]["tenant_id"] == str(tenant_id)
    assert pre_body["metadata"]["run_id"] == str(run_id)
    assert pre_body["metadata"]["request_id"] == "req-1"
    assert pre_body["metadata"]["cost_estimate_cents"] == 7
    assert sup_calls[0]["headers"]["Authorization"] == "Bearer svc.jwt.zz"


@pytest.mark.asyncio
async def test_e2e_run_post_fires_after_success(monkeypatch) -> None:
    router, _auth_calls, sup_calls = _make_router_with_supervisor(
        supervisor_response={"event_id": "evt-post", "allowed": True}
    )
    monkeypatch.setattr("httpx.AsyncClient.post", AsyncMock(side_effect=router._mocked_post))

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
    response_obj = MagicMock()
    response_obj.usage = MagicMock(prompt_tokens=42, completion_tokens=58)

    await router.async_log_success_event(kwargs, response_obj, 1.0, 1.5)
    # Allow the create_task to run.
    for _ in range(20):
        if any(c["json"]["event_type"] == "run.post" for c in sup_calls):
            break
        await asyncio.sleep(0)

    post_calls = [c for c in sup_calls if c["json"]["event_type"] == "run.post"]
    assert len(post_calls) == 1
    body = post_calls[0]["json"]
    assert body["action"] == "llm.complete"
    assert body["metadata"]["status"] == "success"
    assert body["metadata"]["tokens_in"] == 42
    assert body["metadata"]["tokens_out"] == 58
    # duration_ms = (1.5 - 1.0) * 1000 = 500
    assert body["metadata"]["duration_ms"] == 500
