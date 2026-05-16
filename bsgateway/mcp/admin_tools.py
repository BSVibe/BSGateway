"""Admin MCP tools wired as first-class :class:`Tool` definitions (TASK-004).

One tool per ``bsgateway`` CLI sub-app command. Naming follows
``bsgateway_<subapp>_<action>`` (with the collapsed ``bsgateway_execute``
for the root-callback ``execute`` sub-app — see
``.agent/mcp-inventory.md`` for the full catalog).

Design contract:

* Inputs are explicit Pydantic v2 models — NOT auto-derived from the
  Typer signature. Each model mirrors the CLI flags (and any path
  parameters the REST surface needs).
* Output is :class:`AdminToolResponse` (a :class:`pydantic.RootModel`
  over ``Any``) so the dispatcher's ``output_schema`` contract holds
  while preserving the natural JSON shape each REST route returns.
* Required scopes match the REST route the equivalent CLI command hits.
* ``audit_event`` matches the typed event the REST router fires on
  success — set on every mutating tool, ``None`` on reads.
* Handlers delegate the actual transport to an injected
  :data:`LoopbackCaller`. In production (TASK-005) the caller wraps an
  ASGI loopback against the FastAPI app so admin tools share the EXACT
  same request handlers the CLI hits over HTTP — no router-logic
  duplication. Tests inject a stub caller for in-process verification.

The dispatcher in :mod:`bsgateway.mcp.api` enforces scopes and emits
``audit_event`` on success — admin handlers never touch audit
themselves.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, RootModel

from bsgateway.mcp.api import Tool, ToolContext, ToolError, ToolRegistry

# ---------------------------------------------------------------------------
# Loopback caller — injected by lifespan wiring (TASK-005); stubbed in tests.
# ---------------------------------------------------------------------------


LoopbackCaller = Callable[..., Awaitable[Any]]
"""Production caller signature::

    async def caller(
        ctx: ToolContext,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any: ...
"""


# ---------------------------------------------------------------------------
# Output envelope — relaxed Any so each tool's natural JSON shape passes
# through verbatim while still satisfying the dispatcher contract.
# ---------------------------------------------------------------------------


class AdminToolResponse(RootModel[Any]):
    """Permissive output envelope for admin tools.

    The dispatcher accepts any JSON-serialisable shape that comes back
    from the REST surface — enforcing exact response models per tool
    would mean re-declaring every REST router's return shape here, with
    no extra safety since the REST handler is the source of truth.
    """


def _ok(data: Any) -> AdminToolResponse:
    return AdminToolResponse(data)


def _resolve_tenant_id(args: BaseModel, ctx: ToolContext) -> UUID:
    """Return the tenant the handler should target.

    Round 4 Finding 18: schemas now declare ``tenant_id: UUID | None``;
    when omitted the active tenant from the caller's PAT JWT is used
    (mirrors the CLI). Raises :class:`ToolError`(``invalid_input``) when
    neither source is available so the LLM gets a clear error instead
    of a silent fallback to a wrong tenant.
    """
    explicit = getattr(args, "tenant_id", None)
    if explicit is not None:
        return explicit  # type: ignore[no-any-return]
    active = getattr(ctx.user, "active_tenant_id", None)
    if active is None:
        raise ToolError(
            code="invalid_input",
            message=(
                "tenant_id is required and the caller's PAT does not carry an "
                "active tenant claim — pass tenant_id explicitly or re-login "
                "with --tenant-id."
            ),
        )
    return active if isinstance(active, UUID) else UUID(str(active))


# ---------------------------------------------------------------------------
# Input schemas — explicit Pydantic v2 models per tool.
# ---------------------------------------------------------------------------


class _TenantPath(BaseModel):
    """Mixin: tools whose REST path includes ``{tenant_id}``.

    Round 4 Finding 18: ``tenant_id`` is optional. When omitted, the
    handler resolves it from ``ctx.user.active_tenant_id`` (the tenant
    embedded in the caller's PAT JWT, same as the CLI). LLM callers no
    longer need to pass the tenant UUID for every operation on their
    active tenant. Tools that operate on tenants other than the active
    one (Tenants CRUD) keep their own required ``tenant_id`` and do
    NOT inherit this mixin.
    """

    tenant_id: UUID | None = None


# audit ----------------------------------------------------------------------


class AuditListInput(_TenantPath):
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


# execute --------------------------------------------------------------------


class ExecuteInput(BaseModel):
    executor_type: str
    prompt: str
    worker_id: str | None = None


# feedback -------------------------------------------------------------------


class FeedbackAddInput(_TenantPath):
    routing_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: str = ""


class FeedbackListInput(_TenantPath):
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


# intents --------------------------------------------------------------------


class IntentsListInput(_TenantPath):
    pass


class IntentsAddInput(_TenantPath):
    name: str
    description: str = ""
    threshold: float = 0.7
    examples: list[str] = Field(default_factory=list)


class IntentsUpdateInput(_TenantPath):
    intent_id: UUID
    name: str | None = None
    description: str | None = None
    threshold: float | None = None


class IntentsDeleteInput(_TenantPath):
    intent_id: UUID


# models ---------------------------------------------------------------------


class ModelsListInput(_TenantPath):
    type: str = "all"


class ModelsShowInput(_TenantPath):
    model_id: UUID


class ModelsAddInput(_TenantPath):
    name: str
    origin: str = "custom"
    provider: str | None = None
    passthrough: bool = True
    params: dict[str, Any] | None = None


class ModelsUpdateInput(_TenantPath):
    model_id: UUID
    name: str | None = None
    provider: str | None = None
    params: dict[str, Any] | None = None
    passthrough: bool | None = None
    origin: str | None = None


class ModelsRemoveInput(_TenantPath):
    model_id: UUID


# presets --------------------------------------------------------------------


class PresetsListInput(BaseModel):
    pass


class PresetsApplyInput(_TenantPath):
    preset: str
    economy: str
    balanced: str
    premium: str


# routes ---------------------------------------------------------------------


class RoutesTestInput(_TenantPath):
    prompt: str
    model: str = "auto"
    profile_context: list[dict[str, Any]] | None = None


# rules ----------------------------------------------------------------------


class RulesListInput(_TenantPath):
    pass


class RulesAddInput(_TenantPath):
    name: str
    priority: int
    target_model: str
    is_default: bool = False
    conditions: list[dict[str, Any]] = Field(default_factory=list)


class RulesUpdateInput(_TenantPath):
    rule_id: UUID
    name: str | None = None
    priority: int | None = None
    target_model: str | None = None
    is_default: bool | None = None
    conditions: list[dict[str, Any]] | None = None


class RulesDeleteInput(_TenantPath):
    rule_id: UUID


# tenants --------------------------------------------------------------------


class TenantsListInput(BaseModel):
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class TenantsAddInput(BaseModel):
    name: str
    slug: str
    settings: dict[str, Any] = Field(default_factory=dict)


class TenantsShowInput(BaseModel):
    tenant_id: UUID


class TenantsUpdateInput(BaseModel):
    tenant_id: UUID
    name: str | None = None
    slug: str | None = None
    settings: dict[str, Any] | None = None


class TenantsDeleteInput(BaseModel):
    tenant_id: UUID


# usage ----------------------------------------------------------------------


class UsageReportInput(_TenantPath):
    period: str = "day"
    from_date: str | None = Field(default=None, alias="from")
    to_date: str | None = Field(default=None, alias="to")

    model_config = {"populate_by_name": True}


class UsageSparklinesInput(_TenantPath):
    days: int = Field(7, ge=1, le=90)


# workers --------------------------------------------------------------------


class WorkersListInput(BaseModel):
    pass


class WorkersRegisterInput(BaseModel):
    name: str
    install_token: str
    labels: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class WorkersRevokeInput(BaseModel):
    worker_id: UUID


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


EXPECTED_ADMIN_TOOL_NAMES: tuple[str, ...] = (
    "bsgateway_audit_list",
    "bsgateway_execute",
    "bsgateway_feedback_add",
    "bsgateway_feedback_list",
    "bsgateway_intents_list",
    "bsgateway_intents_add",
    "bsgateway_intents_update",
    "bsgateway_intents_delete",
    "bsgateway_models_list",
    "bsgateway_models_show",
    "bsgateway_models_add",
    "bsgateway_models_update",
    "bsgateway_models_remove",
    "bsgateway_presets_list",
    "bsgateway_presets_apply",
    "bsgateway_routes_test",
    "bsgateway_rules_list",
    "bsgateway_rules_add",
    "bsgateway_rules_update",
    "bsgateway_rules_delete",
    "bsgateway_tenants_list",
    "bsgateway_tenants_add",
    "bsgateway_tenants_show",
    "bsgateway_tenants_update",
    "bsgateway_tenants_delete",
    "bsgateway_usage_report",
    "bsgateway_usage_sparklines",
    "bsgateway_workers_list",
    "bsgateway_workers_register",
    "bsgateway_workers_revoke",
)


# ---------------------------------------------------------------------------
# Handler factories — each closes over the injected loopback caller.
# ---------------------------------------------------------------------------


def _h_audit_list(lb: LoopbackCaller):
    async def handler(args: AuditListInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        return _ok(
            await lb(
                ctx,
                "GET",
                f"/tenants/{tenant_id}/audit",
                params={"limit": args.limit, "offset": args.offset},
            )
        )

    return handler


def _h_execute(lb: LoopbackCaller):
    async def handler(args: ExecuteInput, ctx: ToolContext) -> AdminToolResponse:
        body: dict[str, Any] = {
            "executor_type": args.executor_type,
            "prompt": args.prompt,
        }
        if args.worker_id:
            body["worker_id"] = args.worker_id
        return _ok(await lb(ctx, "POST", "/execute", body=body))

    return handler


def _h_feedback_add(lb: LoopbackCaller):
    async def handler(args: FeedbackAddInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        body = {
            "routing_id": args.routing_id,
            "rating": args.rating,
            "comment": args.comment,
        }
        return _ok(await lb(ctx, "POST", f"/tenants/{tenant_id}/feedback", body=body))

    return handler


def _h_feedback_list(lb: LoopbackCaller):
    async def handler(args: FeedbackListInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        return _ok(
            await lb(
                ctx,
                "GET",
                f"/tenants/{tenant_id}/feedback",
                params={"limit": args.limit, "offset": args.offset},
            )
        )

    return handler


def _h_intents_list(lb: LoopbackCaller):
    async def handler(args: IntentsListInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        return _ok(await lb(ctx, "GET", f"/tenants/{tenant_id}/intents"))

    return handler


def _h_intents_add(lb: LoopbackCaller):
    async def handler(args: IntentsAddInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        body = {
            "name": args.name,
            "description": args.description,
            "threshold": args.threshold,
            "examples": list(args.examples),
        }
        return _ok(await lb(ctx, "POST", f"/tenants/{tenant_id}/intents", body=body))

    return handler


def _h_intents_update(lb: LoopbackCaller):
    async def handler(args: IntentsUpdateInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        body = args.model_dump(exclude_unset=True, exclude={"tenant_id", "intent_id"}, mode="json")
        return _ok(
            await lb(
                ctx,
                "PATCH",
                f"/tenants/{tenant_id}/intents/{args.intent_id}",
                body=body,
            )
        )

    return handler


def _h_intents_delete(lb: LoopbackCaller):
    async def handler(args: IntentsDeleteInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        return _ok(
            await lb(
                ctx,
                "DELETE",
                f"/tenants/{tenant_id}/intents/{args.intent_id}",
            )
        )

    return handler


def _h_models_list(lb: LoopbackCaller):
    async def handler(args: ModelsListInput, ctx: ToolContext) -> AdminToolResponse:
        rows = await lb(ctx, "GET", "/admin/models")
        if args.type != "all" and isinstance(rows, list):
            rows = [r for r in rows if r.get("origin") == args.type]
        return _ok(rows)

    return handler


def _h_models_show(lb: LoopbackCaller):
    async def handler(args: ModelsShowInput, ctx: ToolContext) -> AdminToolResponse:
        rows = await lb(ctx, "GET", "/admin/models")
        if not isinstance(rows, list):
            return _ok(None)
        match = next((r for r in rows if str(r.get("id")) == str(args.model_id)), None)
        return _ok(match)

    return handler


def _h_models_add(lb: LoopbackCaller):
    async def handler(args: ModelsAddInput, ctx: ToolContext) -> AdminToolResponse:
        body: dict[str, Any] = {
            "name": args.name,
            "origin": args.origin,
            "is_passthrough": args.passthrough,
        }
        if args.origin == "custom":
            if args.provider is not None:
                body["litellm_model"] = args.provider
            if args.params is not None:
                body["litellm_params"] = args.params
        return _ok(await lb(ctx, "POST", "/admin/models", body=body))

    return handler


def _h_models_update(lb: LoopbackCaller):
    async def handler(args: ModelsUpdateInput, ctx: ToolContext) -> AdminToolResponse:
        fields = args.model_dump(exclude_unset=True, exclude={"tenant_id", "model_id"}, mode="json")
        body: dict[str, Any] = {}
        if "name" in fields:
            body["name"] = fields["name"]
        if "provider" in fields:
            body["litellm_model"] = fields["provider"]
        if "params" in fields:
            body["litellm_params"] = fields["params"]
        if "passthrough" in fields:
            body["is_passthrough"] = fields["passthrough"]
        if "origin" in fields:
            body["origin"] = fields["origin"]
        return _ok(await lb(ctx, "PATCH", f"/admin/models/{args.model_id}", body=body))

    return handler


def _h_models_remove(lb: LoopbackCaller):
    async def handler(args: ModelsRemoveInput, ctx: ToolContext) -> AdminToolResponse:
        return _ok(await lb(ctx, "DELETE", f"/admin/models/{args.model_id}"))

    return handler


def _h_presets_list(lb: LoopbackCaller):
    async def handler(args: PresetsListInput, ctx: ToolContext) -> AdminToolResponse:
        return _ok(await lb(ctx, "GET", "/presets"))

    return handler


def _h_presets_apply(lb: LoopbackCaller):
    async def handler(args: PresetsApplyInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        body = {
            "preset_name": args.preset,
            "model_mapping": {
                "economy": args.economy,
                "balanced": args.balanced,
                "premium": args.premium,
            },
        }
        return _ok(await lb(ctx, "POST", f"/tenants/{tenant_id}/presets/apply", body=body))

    return handler


def _h_routes_test(lb: LoopbackCaller):
    async def handler(args: RoutesTestInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        messages: list[dict[str, Any]] = []
        if args.profile_context:
            messages.extend(args.profile_context)
        messages.append({"role": "user", "content": args.prompt})
        body = {"messages": messages, "model": args.model}
        return _ok(await lb(ctx, "POST", f"/tenants/{tenant_id}/rules/test", body=body))

    return handler


def _h_rules_list(lb: LoopbackCaller):
    async def handler(args: RulesListInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        return _ok(await lb(ctx, "GET", f"/tenants/{tenant_id}/rules"))

    return handler


def _h_rules_add(lb: LoopbackCaller):
    async def handler(args: RulesAddInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        body = {
            "name": args.name,
            "priority": args.priority,
            "target_model": args.target_model,
            "is_default": args.is_default,
            "conditions": list(args.conditions),
        }
        return _ok(await lb(ctx, "POST", f"/tenants/{tenant_id}/rules", body=body))

    return handler


def _h_rules_update(lb: LoopbackCaller):
    async def handler(args: RulesUpdateInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        body = args.model_dump(exclude_unset=True, exclude={"tenant_id", "rule_id"}, mode="json")
        return _ok(
            await lb(
                ctx,
                "PATCH",
                f"/tenants/{tenant_id}/rules/{args.rule_id}",
                body=body,
            )
        )

    return handler


def _h_rules_delete(lb: LoopbackCaller):
    async def handler(args: RulesDeleteInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        return _ok(
            await lb(
                ctx,
                "DELETE",
                f"/tenants/{tenant_id}/rules/{args.rule_id}",
            )
        )

    return handler


def _h_tenants_list(lb: LoopbackCaller):
    async def handler(args: TenantsListInput, ctx: ToolContext) -> AdminToolResponse:
        return _ok(
            await lb(
                ctx,
                "GET",
                "/tenants",
                params={"limit": args.limit, "offset": args.offset},
            )
        )

    return handler


def _h_tenants_add(lb: LoopbackCaller):
    async def handler(args: TenantsAddInput, ctx: ToolContext) -> AdminToolResponse:
        body = {
            "name": args.name,
            "slug": args.slug,
            "settings": dict(args.settings),
        }
        return _ok(await lb(ctx, "POST", "/tenants", body=body))

    return handler


def _h_tenants_show(lb: LoopbackCaller):
    async def handler(args: TenantsShowInput, ctx: ToolContext) -> AdminToolResponse:
        return _ok(await lb(ctx, "GET", f"/tenants/{args.tenant_id}"))

    return handler


def _h_tenants_update(lb: LoopbackCaller):
    async def handler(args: TenantsUpdateInput, ctx: ToolContext) -> AdminToolResponse:
        body = args.model_dump(exclude_unset=True, exclude={"tenant_id"}, mode="json")
        return _ok(await lb(ctx, "PATCH", f"/tenants/{args.tenant_id}", body=body))

    return handler


def _h_tenants_delete(lb: LoopbackCaller):
    async def handler(args: TenantsDeleteInput, ctx: ToolContext) -> AdminToolResponse:
        return _ok(await lb(ctx, "DELETE", f"/tenants/{args.tenant_id}"))

    return handler


def _h_usage_report(lb: LoopbackCaller):
    async def handler(args: UsageReportInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        params: dict[str, Any] = {"period": args.period}
        if args.from_date is not None:
            params["from"] = args.from_date
        if args.to_date is not None:
            params["to"] = args.to_date
        return _ok(await lb(ctx, "GET", f"/tenants/{tenant_id}/usage", params=params))

    return handler


def _h_usage_sparklines(lb: LoopbackCaller):
    async def handler(args: UsageSparklinesInput, ctx: ToolContext) -> AdminToolResponse:
        tenant_id = _resolve_tenant_id(args, ctx)
        return _ok(
            await lb(
                ctx,
                "GET",
                f"/tenants/{tenant_id}/usage/sparklines",
                params={"days": args.days},
            )
        )

    return handler


def _h_workers_list(lb: LoopbackCaller):
    async def handler(args: WorkersListInput, ctx: ToolContext) -> AdminToolResponse:
        return _ok(await lb(ctx, "GET", "/workers"))

    return handler


def _h_workers_register(lb: LoopbackCaller):
    async def handler(args: WorkersRegisterInput, ctx: ToolContext) -> AdminToolResponse:
        body = {
            "name": args.name,
            "labels": list(args.labels),
            "capabilities": list(args.capabilities),
        }
        # The install token authorises registration — pass via header,
        # never the body. Header value is never logged (loopback caller
        # is responsible for redaction at the transport layer).
        return _ok(
            await lb(
                ctx,
                "POST",
                "/workers/register",
                body=body,
                headers={"X-Install-Token": args.install_token},
            )
        )

    return handler


def _h_workers_revoke(lb: LoopbackCaller):
    async def handler(args: WorkersRevokeInput, ctx: ToolContext) -> AdminToolResponse:
        return _ok(await lb(ctx, "DELETE", f"/workers/{args.worker_id}"))

    return handler


# ---------------------------------------------------------------------------
# Public registration
# ---------------------------------------------------------------------------


def register_admin_tools(registry: ToolRegistry, *, loopback: LoopbackCaller) -> None:
    """Register the 30 admin tools mirroring the ``bsgateway`` CLI sub-apps.

    ``loopback`` is the per-call transport — production wiring (TASK-005)
    plumbs an ASGI-loopback against the FastAPI app; tests inject a stub.
    """
    tools: list[Tool] = [
        # audit ---------------------------------------------------------
        Tool(
            name="bsgateway_audit_list",
            description="List audit log entries for the active tenant.",
            input_schema=AuditListInput,
            output_schema=AdminToolResponse,
            handler=_h_audit_list(loopback),
            required_permission="bsgateway.audit.read",
        ),
        # execute -------------------------------------------------------
        Tool(
            name="bsgateway_execute",
            description="Submit an executor task (claude_code / codex / opencode).",
            input_schema=ExecuteInput,
            output_schema=AdminToolResponse,
            handler=_h_execute(loopback),
            required_permission="bsgateway.execute.write",
            audit_event="gateway.executor.task.created",
        ),
        # feedback ------------------------------------------------------
        Tool(
            name="bsgateway_feedback_add",
            description="Submit feedback for a routing decision.",
            input_schema=FeedbackAddInput,
            output_schema=AdminToolResponse,
            handler=_h_feedback_add(loopback),
            required_permission="bsgateway.feedback.write",
            audit_event="gateway.feedback.created",
        ),
        Tool(
            name="bsgateway_feedback_list",
            description="List feedback rows for the active tenant.",
            input_schema=FeedbackListInput,
            output_schema=AdminToolResponse,
            handler=_h_feedback_list(loopback),
            required_permission="bsgateway.feedback.read",
        ),
        # intents -------------------------------------------------------
        Tool(
            name="bsgateway_intents_list",
            description="List intents for the active tenant.",
            input_schema=IntentsListInput,
            output_schema=AdminToolResponse,
            handler=_h_intents_list(loopback),
            required_permission="bsgateway.routing.read",
        ),
        Tool(
            name="bsgateway_intents_add",
            description="Create an intent (with optional examples).",
            input_schema=IntentsAddInput,
            output_schema=AdminToolResponse,
            handler=_h_intents_add(loopback),
            required_permission="bsgateway.routing.write",
            audit_event="gateway.routing.intent.created",
        ),
        Tool(
            name="bsgateway_intents_update",
            description="Patch an intent (only the fields you pass).",
            input_schema=IntentsUpdateInput,
            output_schema=AdminToolResponse,
            handler=_h_intents_update(loopback),
            required_permission="bsgateway.routing.write",
            audit_event="gateway.routing.intent.updated",
        ),
        Tool(
            name="bsgateway_intents_delete",
            description="Delete an intent.",
            input_schema=IntentsDeleteInput,
            output_schema=AdminToolResponse,
            handler=_h_intents_delete(loopback),
            required_permission="bsgateway.routing.write",
            audit_event="gateway.routing.intent.deleted",
        ),
        # models --------------------------------------------------------
        Tool(
            name="bsgateway_models_list",
            description="List effective models (yaml union DB) for the active tenant.",
            input_schema=ModelsListInput,
            output_schema=AdminToolResponse,
            handler=_h_models_list(loopback),
            required_permission="bsgateway.models.read",
        ),
        Tool(
            name="bsgateway_models_show",
            description="Show one effective model by id.",
            input_schema=ModelsShowInput,
            output_schema=AdminToolResponse,
            handler=_h_models_show(loopback),
            required_permission="bsgateway.models.read",
        ),
        Tool(
            name="bsgateway_models_add",
            description="Add a custom model (or hide a system model).",
            input_schema=ModelsAddInput,
            output_schema=AdminToolResponse,
            handler=_h_models_add(loopback),
            required_permission="bsgateway.models.write",
            audit_event="gateway.model.created",
        ),
        Tool(
            name="bsgateway_models_update",
            description="Patch a model row (only the fields you pass).",
            input_schema=ModelsUpdateInput,
            output_schema=AdminToolResponse,
            handler=_h_models_update(loopback),
            required_permission="bsgateway.models.write",
            audit_event="gateway.model.updated",
        ),
        Tool(
            name="bsgateway_models_remove",
            description="Delete a model row.",
            input_schema=ModelsRemoveInput,
            output_schema=AdminToolResponse,
            handler=_h_models_remove(loopback),
            required_permission="bsgateway.models.write",
            audit_event="gateway.model.deleted",
        ),
        # presets -------------------------------------------------------
        Tool(
            name="bsgateway_presets_list",
            description="List available preset templates.",
            input_schema=PresetsListInput,
            output_schema=AdminToolResponse,
            handler=_h_presets_list(loopback),
            required_permission="bsgateway.presets.read",
        ),
        Tool(
            name="bsgateway_presets_apply",
            description="Apply a preset template to the active tenant.",
            input_schema=PresetsApplyInput,
            output_schema=AdminToolResponse,
            handler=_h_presets_apply(loopback),
            required_permission="bsgateway.presets.write",
            audit_event="gateway.presets.applied",
        ),
        # routes --------------------------------------------------------
        Tool(
            name="bsgateway_routes_test",
            description="Resolve which rule + target model would match a prompt.",
            input_schema=RoutesTestInput,
            output_schema=AdminToolResponse,
            handler=_h_routes_test(loopback),
            required_permission="bsgateway.routing.read",
        ),
        # rules ---------------------------------------------------------
        Tool(
            name="bsgateway_rules_list",
            description="List routing rules for the active tenant.",
            input_schema=RulesListInput,
            output_schema=AdminToolResponse,
            handler=_h_rules_list(loopback),
            required_permission="bsgateway.routing.read",
        ),
        Tool(
            name="bsgateway_rules_add",
            description="Create a new routing rule.",
            input_schema=RulesAddInput,
            output_schema=AdminToolResponse,
            handler=_h_rules_add(loopback),
            required_permission="bsgateway.routing.write",
            audit_event="gateway.routing.rule.created",
        ),
        Tool(
            name="bsgateway_rules_update",
            description="Patch a rule (only the fields you pass).",
            input_schema=RulesUpdateInput,
            output_schema=AdminToolResponse,
            handler=_h_rules_update(loopback),
            required_permission="bsgateway.routing.write",
            audit_event="gateway.routing.rule.updated",
        ),
        Tool(
            name="bsgateway_rules_delete",
            description="Delete a rule.",
            input_schema=RulesDeleteInput,
            output_schema=AdminToolResponse,
            handler=_h_rules_delete(loopback),
            required_permission="bsgateway.routing.write",
            audit_event="gateway.routing.rule.deleted",
        ),
        # tenants -------------------------------------------------------
        Tool(
            name="bsgateway_tenants_list",
            description="List tenants.",
            input_schema=TenantsListInput,
            output_schema=AdminToolResponse,
            handler=_h_tenants_list(loopback),
            required_permission="bsgateway.tenants.read",
        ),
        Tool(
            name="bsgateway_tenants_add",
            description="Create a new tenant.",
            input_schema=TenantsAddInput,
            output_schema=AdminToolResponse,
            handler=_h_tenants_add(loopback),
            required_permission="bsgateway.tenants.write",
            audit_event="gateway.tenant.created",
        ),
        Tool(
            name="bsgateway_tenants_show",
            description="Get a tenant by id.",
            input_schema=TenantsShowInput,
            output_schema=AdminToolResponse,
            handler=_h_tenants_show(loopback),
            required_permission="bsgateway.tenants.read",
        ),
        Tool(
            name="bsgateway_tenants_update",
            description="Patch a tenant (only the fields you pass).",
            input_schema=TenantsUpdateInput,
            output_schema=AdminToolResponse,
            handler=_h_tenants_update(loopback),
            required_permission="bsgateway.tenants.write",
            audit_event="gateway.tenant.updated",
        ),
        Tool(
            name="bsgateway_tenants_delete",
            description="Deactivate a tenant.",
            input_schema=TenantsDeleteInput,
            output_schema=AdminToolResponse,
            handler=_h_tenants_delete(loopback),
            required_permission="bsgateway.tenants.write",
            audit_event="gateway.tenant.deleted",
        ),
        # usage ---------------------------------------------------------
        Tool(
            name="bsgateway_usage_report",
            description="Aggregate usage report for the active tenant.",
            input_schema=UsageReportInput,
            output_schema=AdminToolResponse,
            handler=_h_usage_report(loopback),
            required_permission="bsgateway.usage.read",
        ),
        Tool(
            name="bsgateway_usage_sparklines",
            description="Per-model daily request counts (sparkline arrays).",
            input_schema=UsageSparklinesInput,
            output_schema=AdminToolResponse,
            handler=_h_usage_sparklines(loopback),
            required_permission="bsgateway.usage.read",
        ),
        # workers -------------------------------------------------------
        Tool(
            name="bsgateway_workers_list",
            description="List workers registered for the active tenant.",
            input_schema=WorkersListInput,
            output_schema=AdminToolResponse,
            handler=_h_workers_list(loopback),
            required_permission="bsgateway.workers.read",
        ),
        Tool(
            name="bsgateway_workers_register",
            description="Register a new worker (admin smoke test path).",
            input_schema=WorkersRegisterInput,
            output_schema=AdminToolResponse,
            handler=_h_workers_register(loopback),
            required_permission="bsgateway.workers.write",
            audit_event="gateway.worker.registered",
        ),
        Tool(
            name="bsgateway_workers_revoke",
            description="Deregister a worker by id.",
            input_schema=WorkersRevokeInput,
            output_schema=AdminToolResponse,
            handler=_h_workers_revoke(loopback),
            required_permission="bsgateway.workers.write",
            audit_event="gateway.worker.revoked",
        ),
    ]
    for tool in tools:
        registry.register(tool)


__all__ = [
    "EXPECTED_ADMIN_TOOL_NAMES",
    "AdminToolResponse",
    "AuditListInput",
    "ExecuteInput",
    "FeedbackAddInput",
    "FeedbackListInput",
    "IntentsAddInput",
    "IntentsDeleteInput",
    "IntentsListInput",
    "IntentsUpdateInput",
    "LoopbackCaller",
    "ModelsAddInput",
    "ModelsListInput",
    "ModelsRemoveInput",
    "ModelsShowInput",
    "ModelsUpdateInput",
    "PresetsApplyInput",
    "PresetsListInput",
    "RoutesTestInput",
    "RulesAddInput",
    "RulesDeleteInput",
    "RulesListInput",
    "RulesUpdateInput",
    "TenantsAddInput",
    "TenantsDeleteInput",
    "TenantsListInput",
    "TenantsShowInput",
    "TenantsUpdateInput",
    "UsageReportInput",
    "UsageSparklinesInput",
    "WorkersListInput",
    "WorkersRegisterInput",
    "WorkersRevokeInput",
    "register_admin_tools",
]
