"""Phase 0 P0.7 — BSGateway → BSupervisor /api/events client.

The client absorbs BSNexus's old run.pre/run.post calls so the architectural
shift in Lockin §2 ("LLM run.pre/run.post 위치 이동") completes inside the
gateway hook. Contract:

- ``run_pre`` blocks with a 200ms timeout (default), fail-open by default
  per BSNexus's existing behaviour. Returns ``AuditResult(blocked, reason,
  degraded)``.
- ``run_post`` is fire-and-forget (callers schedule ``asyncio.create_task``).
- Service JWT minted via :class:`ServiceTokenMinter` and sent in the
  ``Authorization`` header on every request.
- Body shape matches BSupervisor ``EventRequest`` schema:
  ``{agent_id, source, event_type, action, target, metadata, timestamp?}``.
- BSGateway-specific run_id / project_id / composition_id / tenant_id
  / cost_estimate metadata is preserved on the ``metadata`` field for
  downstream consumers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from bsgateway.supervisor.client import (
    AuditResult,
    BSupervisorClient,
    RunMetadata,
)


def _ok_response(allowed: bool = True, reason: str | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 201
    resp.json = MagicMock(
        return_value={
            "event_id": "evt-1",
            "allowed": allowed,
            "reason": reason,
        }
    )
    resp.raise_for_status = MagicMock(return_value=None)
    return resp


def _denied_response(reason: str = "blocked by rule") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 201
    resp.json = MagicMock(
        return_value={
            "event_id": "evt-2",
            "allowed": False,
            "reason": reason,
        }
    )
    resp.raise_for_status = MagicMock(return_value=None)
    return resp


def _make_client(
    *,
    timeout_ms: int = 200,
    fail_mode: str = "open",
) -> BSupervisorClient:
    minter = MagicMock()
    minter.get_token = AsyncMock(return_value="svc.jwt")
    minter.invalidate = MagicMock()
    return BSupervisorClient(
        base_url="https://api-supervisor.bsvibe.dev",
        token_minter=minter,
        timeout_ms=timeout_ms,
        fail_mode=fail_mode,
    )


def _make_metadata() -> RunMetadata:
    return RunMetadata(
        tenant_id=str(uuid4()),
        run_id=str(uuid4()),
        project_id=str(uuid4()),
        agent_name="founder-architect",
        request_id="req-abc",
        parent_run_id=None,
        composition_id="comp-1",
        cost_estimate_cents=12,
        model="gpt-4o-mini",
    )


@pytest.mark.asyncio
class TestRunPre:
    async def test_returns_allowed_when_supervisor_says_allowed(self) -> None:
        client = _make_client()
        meta = _make_metadata()
        post = AsyncMock(return_value=_ok_response(allowed=True))
        with patch("httpx.AsyncClient.post", new=post):
            result = await client.run_pre(meta)

        assert isinstance(result, AuditResult)
        assert result.blocked is False
        assert result.degraded is False

    async def test_returns_blocked_when_supervisor_denies(self) -> None:
        client = _make_client()
        meta = _make_metadata()
        post = AsyncMock(return_value=_denied_response("policy-violation"))
        with patch("httpx.AsyncClient.post", new=post):
            result = await client.run_pre(meta)

        assert result.blocked is True
        assert result.reason == "policy-violation"
        assert result.degraded is False

    async def test_payload_matches_supervisor_event_schema(self) -> None:
        client = _make_client()
        meta = _make_metadata()
        post = AsyncMock(return_value=_ok_response(allowed=True))
        with patch("httpx.AsyncClient.post", new=post):
            await client.run_pre(meta)

        body = post.await_args_list[0].kwargs["json"]
        # BSupervisor EventRequest required fields (cf. BSupervisor PR #4 schema).
        assert body["source"] == "bsgateway"
        assert body["event_type"] == "run.pre"
        assert body["action"] == "llm.dispatch"
        assert body["agent_id"] == "founder-architect"
        assert body["target"] == "gpt-4o-mini"
        # Custom run metadata travels under the metadata key (free-form).
        assert body["metadata"]["tenant_id"] == meta.tenant_id
        assert body["metadata"]["run_id"] == meta.run_id
        assert body["metadata"]["project_id"] == meta.project_id
        assert body["metadata"]["request_id"] == meta.request_id
        assert body["metadata"]["composition_id"] == meta.composition_id
        assert body["metadata"]["cost_estimate_cents"] == 12

    async def test_timeout_is_fail_open_by_default(self) -> None:
        client = _make_client(timeout_ms=200, fail_mode="open")
        meta = _make_metadata()

        async def _raises_timeout(*_a, **_kw):
            raise httpx.TimeoutException("slow")

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=_raises_timeout)):
            result = await client.run_pre(meta)

        assert result.blocked is False  # fail-open
        assert result.degraded is True
        assert result.reason and "timeout" in result.reason.lower()

    async def test_timeout_fail_closed_blocks(self) -> None:
        client = _make_client(timeout_ms=200, fail_mode="closed")
        meta = _make_metadata()

        async def _raises_timeout(*_a, **_kw):
            raise httpx.TimeoutException("slow")

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=_raises_timeout)):
            result = await client.run_pre(meta)

        assert result.blocked is True
        assert result.degraded is True

    async def test_general_error_is_degraded_fail_open(self) -> None:
        client = _make_client()
        meta = _make_metadata()

        async def _raises(*_a, **_kw):
            raise httpx.ConnectError("nope")

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=_raises)):
            result = await client.run_pre(meta)

        assert result.blocked is False
        assert result.degraded is True

    async def test_uses_minted_service_jwt(self) -> None:
        client = _make_client()
        meta = _make_metadata()
        post = AsyncMock(return_value=_ok_response())
        with patch("httpx.AsyncClient.post", new=post):
            await client.run_pre(meta)

        headers = post.await_args_list[0].kwargs["headers"]
        assert headers["Authorization"] == "Bearer svc.jwt"

    async def test_401_invalidates_token_and_does_not_retry_inline(self) -> None:
        """A 401 from BSupervisor means our minted token was rejected (rotated
        signing secret, expired, etc). We invalidate the cache so the *next*
        call will mint fresh — but do not retry inline (preserves 200ms budget).
        """
        client = _make_client()
        meta = _make_metadata()

        unauth_resp = MagicMock(spec=httpx.Response)
        unauth_resp.status_code = 401
        unauth_resp.json = MagicMock(return_value={"detail": "bad token"})
        unauth_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "401",
                request=MagicMock(),
                response=unauth_resp,
            ),
        )
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=unauth_resp)):
            result = await client.run_pre(meta)

        assert result.degraded is True
        assert result.blocked is False  # default fail-open
        client.token_minter.invalidate.assert_called_once()


@pytest.mark.asyncio
class TestRunPost:
    async def test_run_post_payload_matches_event_schema(self) -> None:
        client = _make_client()
        meta = _make_metadata()
        post = AsyncMock(return_value=_ok_response())
        with patch("httpx.AsyncClient.post", new=post):
            await client.run_post(
                meta,
                status="success",
                actual_cost_cents=25,
                tokens_in=120,
                tokens_out=80,
                duration_ms=842,
            )

        body = post.await_args_list[0].kwargs["json"]
        assert body["event_type"] == "run.post"
        assert body["action"] == "llm.complete"
        assert body["target"] == "gpt-4o-mini"
        assert body["metadata"]["status"] == "success"
        assert body["metadata"]["actual_cost_cents"] == 25
        assert body["metadata"]["tokens_in"] == 120
        assert body["metadata"]["tokens_out"] == 80
        assert body["metadata"]["duration_ms"] == 842
        assert body["metadata"]["run_id"] == meta.run_id

    async def test_run_post_swallows_errors(self) -> None:
        """Fire-and-forget — callers should never see exceptions surface."""
        client = _make_client()
        meta = _make_metadata()

        async def _raises(*_a, **_kw):
            raise httpx.ConnectError("down")

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=_raises)):
            # Must not raise.
            await client.run_post(meta, status="error")
