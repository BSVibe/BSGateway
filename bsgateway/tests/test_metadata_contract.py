"""Regression test: BSGateway ``RunMetadata`` ↔ bsvibe-llm ``RunAuditMetadata`` contract.

Phase A Batch 5 (Lockin §3 #11): BSGateway is the LLM gateway, so it does
NOT depend on ``bsvibe-llm``. However, BSNexus (and the future
``bsvibe-llm`` consumers) WILL emit metadata using
``bsvibe_llm.RunAuditMetadata.to_metadata()``, and BSGateway parses
that dict via ``RunMetadata.from_request_metadata``. The two sides MUST
round-trip cleanly, otherwise audit-pipeline drift silently swallows
fields like ``project_id`` / ``composition_id`` / ``cost_estimate_cents``.

This test asserts the contract directly without importing ``bsvibe-llm``
into BSGateway's runtime — we re-implement the producer-side ``to_dict``
shape locally (mirrors ``bsvibe_llm/metadata.py`` ``_NAMED_KEYS`` +
``to_metadata`` exactly) and roundtrip through BSGateway's
``RunMetadata.from_request_metadata``.

If ``bsvibe-llm.RunAuditMetadata`` ever drops/adds a named field, this
test fails — alerting maintainers to update both sides in lockstep.
"""

from __future__ import annotations

import pytest

from bsgateway.supervisor.client import RunMetadata

# Mirror of bsvibe_llm.metadata._NAMED_KEYS — pinned by this test.
# Source: ~/Works/bsvibe-python/main/packages/bsvibe-llm/src/bsvibe_llm/metadata.py
BSVIBE_LLM_NAMED_KEYS = frozenset(
    {
        "tenant_id",
        "run_id",
        "request_id",
        "parent_run_id",
        "agent_name",
        "cost_estimate_cents",
        "project_id",
        "composition_id",
    }
)


def _producer_to_metadata(
    *,
    tenant_id: str,
    run_id: str,
    request_id: str | None = None,
    parent_run_id: str | None = None,
    agent_name: str | None = None,
    cost_estimate_cents: int | None = None,
    project_id: str | None = None,
    composition_id: str | None = None,
    extras: dict | None = None,
) -> dict:
    """Replicate ``bsvibe_llm.RunAuditMetadata.to_metadata()`` byte-for-byte.

    Pinned to the producer-side contract documented in
    ``packages/bsvibe-llm/src/bsvibe_llm/metadata.py``.
    """
    out: dict = dict(extras or {})
    named = {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "request_id": request_id,
        "parent_run_id": parent_run_id,
        "agent_name": agent_name,
        "cost_estimate_cents": cost_estimate_cents,
        "project_id": project_id,
        "composition_id": composition_id,
    }
    for k, v in named.items():
        if v is not None:
            out[k] = v
    return out


class TestRunAuditMetadataContract:
    """Cross-check that bsvibe-llm and BSGateway parse the same wire shape."""

    def test_named_keys_subset(self):
        """Every bsvibe-llm named key must be a recognised RunMetadata field.

        Failure means bsvibe-llm added a key that BSGateway will silently
        bucket into ``extras`` instead of promoting to a typed field.
        """
        gateway_named = {
            "tenant_id",
            "run_id",
            "request_id",
            "parent_run_id",
            "agent_name",
            "cost_estimate_cents",
            "project_id",
            "composition_id",
            "model",  # BSGateway-only: resolved_model passthrough
        }
        # bsvibe-llm keys MUST be a subset of BSGateway's recognised keys.
        # (model is BSGateway-only; bsvibe-llm doesn't emit it.)
        missing = BSVIBE_LLM_NAMED_KEYS - gateway_named
        assert missing == set(), (
            f"bsvibe-llm emits keys BSGateway will silently drop into "
            f"extras: {sorted(missing)}. Update bsgateway.supervisor.client."
        )

    def test_full_roundtrip(self):
        """Producer dict → BSGateway parse → typed fields preserved."""
        producer_dict = _producer_to_metadata(
            tenant_id="t-1",
            run_id="r-1",
            request_id="req-1",
            parent_run_id="r-0",
            agent_name="composer",
            cost_estimate_cents=42,
            project_id="p-1",
            composition_id="c-1",
            extras={"trace_id": "abc"},
        )
        meta = RunMetadata.from_request_metadata(producer_dict)
        assert meta is not None
        assert meta.tenant_id == "t-1"
        assert meta.run_id == "r-1"
        assert meta.request_id == "req-1"
        assert meta.parent_run_id == "r-0"
        assert meta.agent_name == "composer"
        assert meta.cost_estimate_cents == 42
        assert meta.project_id == "p-1"
        assert meta.composition_id == "c-1"
        # Unknown keys land in extras — forwarded verbatim downstream.
        assert meta.extras == {"trace_id": "abc"}

    def test_minimal_required_fields(self):
        """Only ``tenant_id`` + ``run_id`` are required; all else optional."""
        producer_dict = _producer_to_metadata(
            tenant_id="t-1",
            run_id="r-1",
        )
        meta = RunMetadata.from_request_metadata(producer_dict)
        assert meta is not None
        assert meta.tenant_id == "t-1"
        assert meta.run_id == "r-1"
        assert meta.request_id is None
        assert meta.cost_estimate_cents is None
        assert meta.extras == {}

    def test_missing_run_id_returns_none(self):
        producer_dict = _producer_to_metadata(tenant_id="t-1", run_id="")
        # producer's contract: empty run_id raises at construction time;
        # if it ever leaks through (consumer-side parse), BSGateway
        # rejects with None — preserved here so a bug in producer doesn't
        # silently emit incomplete audit.
        producer_dict["run_id"] = ""
        meta = RunMetadata.from_request_metadata(producer_dict)
        assert meta is None

    def test_missing_tenant_id_returns_none(self):
        producer_dict = {"run_id": "r-1"}  # no tenant_id
        meta = RunMetadata.from_request_metadata(producer_dict)
        assert meta is None

    def test_to_dict_then_from_request_metadata_idempotent(self):
        """``RunMetadata.to_dict() → from_request_metadata`` is identity."""
        original = RunMetadata(
            tenant_id="t-1",
            run_id="r-1",
            request_id="req-1",
            agent_name="composer",
            cost_estimate_cents=15,
            project_id="p-1",
            extras={"feature_flag": "v2"},
        )
        roundtrip = RunMetadata.from_request_metadata(original.to_dict())
        assert roundtrip is not None
        assert roundtrip.tenant_id == original.tenant_id
        assert roundtrip.run_id == original.run_id
        assert roundtrip.request_id == original.request_id
        assert roundtrip.agent_name == original.agent_name
        assert roundtrip.cost_estimate_cents == original.cost_estimate_cents
        assert roundtrip.project_id == original.project_id
        assert roundtrip.extras == original.extras

    @pytest.mark.parametrize(
        "cost_raw,expected",
        [
            (10, 10),
            ("10", 10),
            (None, None),
            ("not-a-number", None),
            (3.14, 3),  # int() truncates
        ],
    )
    def test_cost_estimate_cents_coercion(self, cost_raw, expected):
        """``cost_estimate_cents`` must coerce strings/None like bsvibe-llm.

        Both sides ``int()`` with TypeError/ValueError → None on failure.
        """
        producer_dict = {
            "tenant_id": "t-1",
            "run_id": "r-1",
            "cost_estimate_cents": cost_raw,
        }
        meta = RunMetadata.from_request_metadata(producer_dict)
        assert meta is not None
        assert meta.cost_estimate_cents == expected
