"""TASK-004 — admin MCP tools as first-class :class:`Tool` definitions.

Pins the contract for the 30 admin tools that mirror the ``bsgateway``
CLI sub-apps. Naming follows ``bsgateway_<subapp>_<action>`` (with the
collapsed ``bsgateway_execute`` for the root-callback ``execute``
sub-app — the inventory in ``.agent/mcp-inventory.md`` enumerates the
full catalog).

The contract under test:

* ``register_admin_tools`` registers exactly the catalog enumerated in
  the inventory (30 tools) on the supplied :class:`ToolRegistry`.
* Each tool has explicit Pydantic ``input_schema`` / ``output_schema``
  (NO Typer auto-conversion) — the dispatcher's contract from TASK-002
  is preserved.
* Required scopes mirror the REST surface the equivalent CLI command
  hits (``bsgateway:models:write`` for ``models add``, etc.).
* ``audit_event`` is set on every mutating tool; reads emit nothing.
* Handlers delegate the actual request to an injected ``loopback``
  callable so tests can stub it. Production wiring (TASK-005) plumbs
  the real ASGI loopback against the FastAPI app.

We test ONE CallTool per CLI sub-app (11 sub-apps → 11 dispatch tests)
plus presence assertions for the full 30-tool catalog.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from bsvibe_authz import User

from bsgateway.mcp.admin_tools import (
    EXPECTED_ADMIN_TOOL_NAMES,
    register_admin_tools,
)
from bsgateway.mcp.api import ToolContext, ToolRegistry

TENANT_ID = uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(scopes: list[str] | None = None) -> User:
    return User(
        id="user-1",
        email="u@example.com",
        active_tenant_id=str(TENANT_ID),
        tenants=[],
        is_service=False,
        scope=["bsgateway:*"] if scopes is None else scopes,
    )


def _make_ctx(user: User | None = None) -> ToolContext:
    return ToolContext(
        settings=MagicMock(),
        user=user or _make_user(),
        db=None,
        audit_app_state=None,
        log=MagicMock(),
    )


class _StubLoopback:
    """Records loopback calls and returns canned per-route responses."""

    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = responses or {}

    async def __call__(
        self,
        ctx: ToolContext,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "params": params,
                "headers": headers,
            }
        )
        # Match by exact (method, path); fall back to method+prefix.
        if (method, path) in self._responses:
            return self._responses[(method, path)]
        for (m, p), resp in self._responses.items():
            if m == method and path.startswith(p):
                return resp
        return {}


def _build_registry(loopback: _StubLoopback) -> ToolRegistry:
    reg = ToolRegistry()
    register_admin_tools(reg, loopback=loopback)
    return reg


# ---------------------------------------------------------------------------
# Catalog presence
# ---------------------------------------------------------------------------


class TestAdminCatalog:
    def test_registers_thirty_tools(self) -> None:
        reg = _build_registry(_StubLoopback())
        assert len(reg) == 30

    def test_tool_names_match_inventory(self) -> None:
        reg = _build_registry(_StubLoopback())
        assert set(reg.names()) == set(EXPECTED_ADMIN_TOOL_NAMES)

    def test_tool_naming_pattern(self) -> None:
        reg = _build_registry(_StubLoopback())
        for name in reg.names():
            assert name == "bsgateway_execute" or name.startswith("bsgateway_"), (
                f"unexpected tool name: {name}"
            )

    def test_no_collision_with_domain_tools(self) -> None:
        reg = _build_registry(_StubLoopback())
        # Domain tools use bsgateway_mcp_*; admin must not.
        for name in reg.names():
            assert not name.startswith("bsgateway_mcp_")

    def test_input_and_output_schemas_explicit(self) -> None:
        from pydantic import BaseModel

        reg = _build_registry(_StubLoopback())
        for name in reg.names():
            tool = reg.get(name)
            assert tool is not None
            # Explicit Pydantic models, not auto-derived dicts.
            assert isinstance(tool.input_schema, type)
            assert issubclass(tool.input_schema, BaseModel)
            assert isinstance(tool.output_schema, type)
            assert issubclass(tool.output_schema, BaseModel)


class TestScopeAndAudit:
    """Required scopes + audit_event match the REST routes the CLI hits."""

    def test_models_write_scopes(self) -> None:
        reg = _build_registry(_StubLoopback())
        for name in (
            "bsgateway_models_add",
            "bsgateway_models_update",
            "bsgateway_models_remove",
        ):
            tool = reg.get(name)
            assert tool is not None
            assert "bsgateway:models:write" in tool.required_scopes

    def test_models_read_scopes(self) -> None:
        reg = _build_registry(_StubLoopback())
        for name in ("bsgateway_models_list", "bsgateway_models_show"):
            tool = reg.get(name)
            assert tool is not None
            assert "bsgateway:models:read" in tool.required_scopes

    def test_routing_write_scope_for_rule_mutations(self) -> None:
        reg = _build_registry(_StubLoopback())
        for name in (
            "bsgateway_rules_add",
            "bsgateway_rules_update",
            "bsgateway_rules_delete",
        ):
            tool = reg.get(name)
            assert tool is not None
            assert "bsgateway:routing:write" in tool.required_scopes

    def test_audit_event_set_on_every_mutating_tool(self) -> None:
        reg = _build_registry(_StubLoopback())
        mutating = {
            "bsgateway_models_add",
            "bsgateway_models_update",
            "bsgateway_models_remove",
            "bsgateway_rules_add",
            "bsgateway_rules_update",
            "bsgateway_rules_delete",
            "bsgateway_intents_add",
            "bsgateway_intents_update",
            "bsgateway_intents_delete",
            "bsgateway_tenants_add",
            "bsgateway_tenants_update",
            "bsgateway_tenants_delete",
            "bsgateway_presets_apply",
            "bsgateway_feedback_add",
            "bsgateway_workers_register",
            "bsgateway_workers_revoke",
            "bsgateway_execute",
        }
        for name in mutating:
            tool = reg.get(name)
            assert tool is not None, f"missing tool: {name}"
            assert tool.audit_event, f"{name} must declare audit_event"

    def test_no_audit_event_on_reads(self) -> None:
        reg = _build_registry(_StubLoopback())
        reads = {
            "bsgateway_models_list",
            "bsgateway_models_show",
            "bsgateway_rules_list",
            "bsgateway_intents_list",
            "bsgateway_tenants_list",
            "bsgateway_tenants_show",
            "bsgateway_audit_list",
            "bsgateway_usage_report",
            "bsgateway_usage_sparklines",
            "bsgateway_feedback_list",
            "bsgateway_presets_list",
            "bsgateway_routes_test",
            "bsgateway_workers_list",
        }
        for name in reads:
            tool = reg.get(name)
            assert tool is not None, f"missing tool: {name}"
            assert tool.audit_event is None, f"{name} must NOT declare audit_event"


# ---------------------------------------------------------------------------
# Per-sub-app dispatch (one CallTool per sub-app — 11 sub-apps)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPerSubAppDispatch:
    async def test_models_list(self) -> None:
        canned = [{"id": str(uuid4()), "name": "m1", "origin": "custom"}]
        lb = _StubLoopback({("GET", "/admin/models"): canned})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_models_list",
            {"tenant_id": str(TENANT_ID), "type": "all"},
            _make_ctx(),
        )
        assert result == canned
        assert lb.calls[0]["method"] == "GET"
        assert lb.calls[0]["path"] == "/admin/models"

    async def test_routes_test(self) -> None:
        canned = {"matched_rule": "default", "target_model": "qwen3"}
        lb = _StubLoopback({("POST", f"/tenants/{TENANT_ID}/rules/test"): canned})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_routes_test",
            {"tenant_id": str(TENANT_ID), "prompt": "hello", "model": "auto"},
            _make_ctx(),
        )
        assert result == canned
        assert lb.calls[0]["method"] == "POST"
        assert lb.calls[0]["path"] == f"/tenants/{TENANT_ID}/rules/test"
        assert lb.calls[0]["body"]["model"] == "auto"
        assert lb.calls[0]["body"]["messages"] == [{"role": "user", "content": "hello"}]

    async def test_rules_add(self) -> None:
        rule = {"id": str(uuid4()), "name": "r1"}
        lb = _StubLoopback({("POST", f"/tenants/{TENANT_ID}/rules"): rule})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_rules_add",
            {
                "tenant_id": str(TENANT_ID),
                "name": "r1",
                "priority": 10,
                "target_model": "qwen3",
                "is_default": False,
            },
            _make_ctx(),
        )
        assert result == rule
        body = lb.calls[0]["body"]
        assert body["name"] == "r1"
        assert body["priority"] == 10
        assert body["conditions"] == []

    async def test_intents_list(self) -> None:
        canned = [{"id": str(uuid4()), "name": "i1"}]
        lb = _StubLoopback({("GET", f"/tenants/{TENANT_ID}/intents"): canned})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_intents_list",
            {"tenant_id": str(TENANT_ID)},
            _make_ctx(),
        )
        assert result == canned

    async def test_presets_apply(self) -> None:
        canned = {"applied": True, "rules_created": 3}
        lb = _StubLoopback({("POST", f"/tenants/{TENANT_ID}/presets/apply"): canned})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_presets_apply",
            {
                "tenant_id": str(TENANT_ID),
                "preset": "balanced",
                "economy": "ollama:qwen",
                "balanced": "ollama:llama3",
                "premium": "anthropic:claude",
            },
            _make_ctx(),
        )
        assert result == canned
        body = lb.calls[0]["body"]
        assert body["preset_name"] == "balanced"
        assert body["model_mapping"]["economy"] == "ollama:qwen"

    async def test_tenants_list(self) -> None:
        canned = [{"id": str(uuid4()), "name": "t1"}]
        lb = _StubLoopback({("GET", "/tenants"): canned})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_tenants_list",
            {"limit": 50, "offset": 0},
            _make_ctx(),
        )
        assert result == canned
        assert lb.calls[0]["params"] == {"limit": 50, "offset": 0}

    async def test_audit_list(self) -> None:
        canned = {"items": [], "total": 0}
        lb = _StubLoopback({("GET", f"/tenants/{TENANT_ID}/audit"): canned})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_audit_list",
            {"tenant_id": str(TENANT_ID), "limit": 50, "offset": 0},
            _make_ctx(),
        )
        assert result == canned

    async def test_usage_report(self) -> None:
        canned = {"total_requests": 42}
        lb = _StubLoopback({("GET", f"/tenants/{TENANT_ID}/usage"): canned})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_usage_report",
            {"tenant_id": str(TENANT_ID), "period": "day"},
            _make_ctx(),
        )
        assert result == canned
        assert lb.calls[0]["params"]["period"] == "day"

    async def test_feedback_add(self) -> None:
        canned = {"id": str(uuid4()), "rating": 5}
        lb = _StubLoopback({("POST", f"/tenants/{TENANT_ID}/feedback"): canned})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_feedback_add",
            {
                "tenant_id": str(TENANT_ID),
                "routing_id": str(uuid4()),
                "rating": 5,
                "comment": "great",
            },
            _make_ctx(),
        )
        assert result == canned

    async def test_workers_list(self) -> None:
        canned = [{"id": str(uuid4()), "name": "w1"}]
        lb = _StubLoopback({("GET", "/workers"): canned})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_workers_list",
            {},
            _make_ctx(),
        )
        assert result == canned

    async def test_execute(self) -> None:
        canned = {"task_id": str(uuid4()), "status": "queued"}
        lb = _StubLoopback({("POST", "/execute"): canned})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_execute",
            {
                "tenant_id": str(TENANT_ID),
                "executor_type": "claude_code",
                "prompt": "hello",
            },
            _make_ctx(),
        )
        assert result == canned
        assert lb.calls[0]["body"]["executor_type"] == "claude_code"


# ---------------------------------------------------------------------------
# Edge cases — update sends only set fields, delete idempotency, etc.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEdgeCases:
    async def test_models_update_excludes_unset(self) -> None:
        model_id = uuid4()
        lb = _StubLoopback({("PATCH", f"/admin/models/{model_id}"): {"id": str(model_id)}})
        reg = _build_registry(lb)
        await reg.call_tool(
            "bsgateway_models_update",
            {"tenant_id": str(TENANT_ID), "model_id": str(model_id), "name": "new-name"},
            _make_ctx(),
        )
        body = lb.calls[0]["body"]
        assert body == {"name": "new-name"}

    async def test_rules_update_includes_only_set_fields(self) -> None:
        rule_id = uuid4()
        lb = _StubLoopback(
            {("PATCH", f"/tenants/{TENANT_ID}/rules/{rule_id}"): {"id": str(rule_id)}}
        )
        reg = _build_registry(lb)
        await reg.call_tool(
            "bsgateway_rules_update",
            {
                "tenant_id": str(TENANT_ID),
                "rule_id": str(rule_id),
                "priority": 99,
            },
            _make_ctx(),
        )
        body = lb.calls[0]["body"]
        assert body == {"priority": 99}

    async def test_workers_register_passes_install_token_header(self) -> None:
        lb = _StubLoopback({("POST", "/workers/register"): {"id": "w1"}})
        reg = _build_registry(lb)
        await reg.call_tool(
            "bsgateway_workers_register",
            {
                "name": "host-1",
                "install_token": "bsv_install_abcdef",
                "labels": ["gpu"],
                "capabilities": ["claude_code"],
            },
            _make_ctx(),
        )
        # install_token must NOT leak into body — only headers.
        assert lb.calls[0]["headers"] == {"X-Install-Token": "bsv_install_abcdef"}
        body = lb.calls[0]["body"]
        assert "install_token" not in body
        assert body["name"] == "host-1"
        assert body["labels"] == ["gpu"]

    async def test_scope_enforced_before_dispatch(self) -> None:
        lb = _StubLoopback()
        reg = _build_registry(lb)
        from bsgateway.mcp.api import ToolError

        # Caller has no scopes — must be rejected by the dispatcher
        # before the loopback runs.
        with pytest.raises(ToolError) as excinfo:
            await reg.call_tool(
                "bsgateway_models_add",
                {
                    "tenant_id": str(TENANT_ID),
                    "name": "custom/m",
                    "origin": "custom",
                    "provider": "ollama_chat/qwen",
                    "passthrough": True,
                },
                _make_ctx(_make_user(scopes=[])),
            )
        assert excinfo.value.code == "permission_denied"
        assert lb.calls == []

    async def test_input_validation_rejects_bad_uuid(self) -> None:
        lb = _StubLoopback()
        reg = _build_registry(lb)
        from bsgateway.mcp.api import ToolError

        with pytest.raises(ToolError) as excinfo:
            await reg.call_tool(
                "bsgateway_models_list",
                {"tenant_id": "not-a-uuid"},
                _make_ctx(),
            )
        assert excinfo.value.code == "invalid_input"
        assert lb.calls == []

    async def test_models_show_returns_match(self) -> None:
        model_id = uuid4()
        rows = [
            {"id": str(uuid4()), "name": "other"},
            {"id": str(model_id), "name": "matched"},
        ]
        lb = _StubLoopback({("GET", "/admin/models"): rows})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_models_show",
            {"tenant_id": str(TENANT_ID), "model_id": str(model_id)},
            _make_ctx(),
        )
        assert result == {"id": str(model_id), "name": "matched"}

    async def test_models_show_returns_none_for_non_list(self) -> None:
        lb = _StubLoopback({("GET", "/admin/models"): {"unexpected": "shape"}})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_models_show",
            {"tenant_id": str(TENANT_ID), "model_id": str(uuid4())},
            _make_ctx(),
        )
        assert result is None

    async def test_models_list_filter_custom(self) -> None:
        rows = [
            {"id": str(uuid4()), "origin": "custom"},
            {"id": str(uuid4()), "origin": "system"},
        ]
        lb = _StubLoopback({("GET", "/admin/models"): rows})
        reg = _build_registry(lb)
        result = await reg.call_tool(
            "bsgateway_models_list",
            {"tenant_id": str(TENANT_ID), "type": "custom"},
            _make_ctx(),
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["origin"] == "custom"

    async def test_models_add_hide_system_omits_litellm(self) -> None:
        lb = _StubLoopback({("POST", "/admin/models"): {"id": "x"}})
        reg = _build_registry(lb)
        await reg.call_tool(
            "bsgateway_models_add",
            {
                "tenant_id": str(TENANT_ID),
                "name": "anthropic/claude",
                "origin": "hide_system",
                "passthrough": False,
            },
            _make_ctx(),
        )
        body = lb.calls[0]["body"]
        assert body == {
            "name": "anthropic/claude",
            "origin": "hide_system",
            "is_passthrough": False,
        }

    async def test_models_update_passes_all_field_renames(self) -> None:
        model_id = uuid4()
        lb = _StubLoopback({("PATCH", f"/admin/models/{model_id}"): {"id": str(model_id)}})
        reg = _build_registry(lb)
        await reg.call_tool(
            "bsgateway_models_update",
            {
                "tenant_id": str(TENANT_ID),
                "model_id": str(model_id),
                "name": "new",
                "provider": "ollama_chat/qwen3:8b",
                "params": {"temperature": 0.1},
                "passthrough": False,
                "origin": "custom",
            },
            _make_ctx(),
        )
        body = lb.calls[0]["body"]
        assert body == {
            "name": "new",
            "litellm_model": "ollama_chat/qwen3:8b",
            "litellm_params": {"temperature": 0.1},
            "is_passthrough": False,
            "origin": "custom",
        }


# ---------------------------------------------------------------------------
# Smoke dispatch — every tool gets exercised once with valid input.
# Pushes per-handler coverage above the 80% gate.
# ---------------------------------------------------------------------------


def _smoke_args(tool_name: str) -> dict[str, Any]:
    """Minimal valid args for each registered admin tool."""
    t = str(TENANT_ID)
    rid = str(uuid4())
    iid = str(uuid4())
    mid = str(uuid4())
    wid = str(uuid4())
    table: dict[str, dict[str, Any]] = {
        "bsgateway_audit_list": {"tenant_id": t},
        "bsgateway_execute": {
            "executor_type": "claude_code",
            "prompt": "hi",
            "worker_id": wid,
        },
        "bsgateway_feedback_add": {
            "tenant_id": t,
            "routing_id": rid,
            "rating": 4,
            "comment": "ok",
        },
        "bsgateway_feedback_list": {"tenant_id": t},
        "bsgateway_intents_list": {"tenant_id": t},
        "bsgateway_intents_add": {
            "tenant_id": t,
            "name": "hello",
            "examples": ["hi", "hey"],
        },
        "bsgateway_intents_update": {
            "tenant_id": t,
            "intent_id": iid,
            "name": "renamed",
        },
        "bsgateway_intents_delete": {"tenant_id": t, "intent_id": iid},
        "bsgateway_models_list": {"tenant_id": t},
        "bsgateway_models_show": {"tenant_id": t, "model_id": mid},
        "bsgateway_models_add": {
            "tenant_id": t,
            "name": "custom/m",
            "origin": "custom",
            "provider": "ollama_chat/qwen",
            "params": {"temperature": 0.2},
        },
        "bsgateway_models_update": {"tenant_id": t, "model_id": mid, "name": "n2"},
        "bsgateway_models_remove": {"tenant_id": t, "model_id": mid},
        "bsgateway_presets_list": {},
        "bsgateway_presets_apply": {
            "tenant_id": t,
            "preset": "balanced",
            "economy": "a",
            "balanced": "b",
            "premium": "c",
        },
        "bsgateway_routes_test": {
            "tenant_id": t,
            "prompt": "p",
            "model": "auto",
            "profile_context": [{"role": "system", "content": "you are X"}],
        },
        "bsgateway_rules_list": {"tenant_id": t},
        "bsgateway_rules_add": {
            "tenant_id": t,
            "name": "r",
            "priority": 1,
            "target_model": "m",
        },
        "bsgateway_rules_update": {
            "tenant_id": t,
            "rule_id": rid,
            "name": "renamed",
        },
        "bsgateway_rules_delete": {"tenant_id": t, "rule_id": rid},
        "bsgateway_tenants_list": {},
        "bsgateway_tenants_add": {
            "name": "Tenant",
            "slug": "tenant",
            "settings": {"k": "v"},
        },
        "bsgateway_tenants_show": {"tenant_id": t},
        "bsgateway_tenants_update": {"tenant_id": t, "name": "renamed"},
        "bsgateway_tenants_delete": {"tenant_id": t},
        "bsgateway_usage_report": {
            "tenant_id": t,
            "period": "week",
            "from": "2026-01-01",
            "to": "2026-01-31",
        },
        "bsgateway_usage_sparklines": {"tenant_id": t, "days": 14},
        "bsgateway_workers_list": {},
        "bsgateway_workers_register": {
            "name": "worker-1",
            "install_token": "bsv_install_x",
            "labels": ["gpu"],
            "capabilities": ["claude_code"],
        },
        "bsgateway_workers_revoke": {"worker_id": wid},
    }
    return table[tool_name]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", list(EXPECTED_ADMIN_TOOL_NAMES))
async def test_every_admin_tool_dispatches(tool_name: str) -> None:
    lb = _StubLoopback()
    reg = _build_registry(lb)
    await reg.call_tool(tool_name, _smoke_args(tool_name), _make_ctx())
    assert len(lb.calls) == 1, f"{tool_name}: handler must call loopback exactly once"


# ---------------------------------------------------------------------------
# Round 4 Finding 18 — auto-derive tenant_id from PAT JWT when omitted
# ---------------------------------------------------------------------------


class TestAutoDeriveTenant:
    async def test_models_list_uses_ctx_active_tenant_when_tenant_id_omitted(self):
        """When the LLM omits ``tenant_id``, the handler resolves it from
        ``ctx.user.active_tenant_id`` (carried in the PAT JWT). The CLI does
        the same — MCP must match. Round 4 Finding 18."""
        from uuid import uuid4

        from bsgateway.mcp.admin_tools import ModelsListInput, _resolve_tenant_id

        tenant = uuid4()
        ctx = MagicMock()
        ctx.user.active_tenant_id = tenant

        args = ModelsListInput()  # no tenant_id
        assert _resolve_tenant_id(args, ctx) == tenant

    async def test_explicit_tenant_id_overrides_active(self):
        """When the LLM passes ``tenant_id`` explicitly, that wins."""
        from uuid import uuid4

        from bsgateway.mcp.admin_tools import ModelsListInput, _resolve_tenant_id

        active = uuid4()
        explicit = uuid4()
        ctx = MagicMock()
        ctx.user.active_tenant_id = active

        args = ModelsListInput(tenant_id=explicit)
        assert _resolve_tenant_id(args, ctx) == explicit

    async def test_neither_explicit_nor_active_raises_invalid_input(self):
        """When tenant_id is missing AND the caller has no active tenant
        claim, raise a ToolError with a clear message instead of silently
        falling back to a wrong tenant."""
        from bsgateway.mcp.admin_tools import ModelsListInput, _resolve_tenant_id
        from bsgateway.mcp.api import ToolError

        ctx = MagicMock()
        ctx.user.active_tenant_id = None

        args = ModelsListInput()
        with pytest.raises(ToolError) as excinfo:
            _resolve_tenant_id(args, ctx)
        assert excinfo.value.code == "invalid_input"
        assert "tenant_id" in excinfo.value.message
