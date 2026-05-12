# BSGateway MCP

First-class MCP API for BSGateway. MCP is a peer of REST — both transports
delegate to the same service / handler layer. There is no Typer
auto-adapter; every tool has explicit Pydantic input/output schemas, the
same scope guards as the equivalent REST route, and an audit event on
mutations.

## Architecture

```
┌──────────────────────────────────────────────────┐
│ FastAPI app  (bsgateway/api/app.py)              │
│   lifespan ─▶ build_registry()                   │
│              ├─ 9 domain tools  (server.py)      │
│              └─ 30 admin tools  (admin_tools.py) │
│   Mount("/mcp", StreamableHTTP ASGI shim)        │
│   Route("/mcp/health")                           │
└──────────────────────────────────────────────────┘
         │                          │
         ▼                          ▼
   resolve_tool_context()      ToolRegistry.call_tool()
   (bsvibe-authz 3-way)        ├─ scope check
                               ├─ input validate
                               ├─ handler
                               ├─ output validate
                               └─ audit emit (success only)
```

| File                  | Purpose                                                 |
|-----------------------|---------------------------------------------------------|
| `api.py`              | `Tool`, `ToolContext`, `ToolRegistry`, `ToolError`, `resolve_tool_context` |
| `server.py`           | `register_domain_tools(registry, service_factory)`      |
| `admin_tools.py`      | `register_admin_tools(registry, loopback)` + catalog drift guard |
| `service.py`          | Domain service-layer functions reused by handlers       |
| `lifespan.py`         | `build_registry`, `make_loopback_caller`, `make_service_factory`, `build_streamable_http_app` |
| `router.py`           | Legacy router (pre-first-class) — retained for any callers |
| `schemas.py`          | Shared Pydantic schemas                                 |

## The `Tool` primitive

```python
from pydantic import BaseModel
from bsgateway.mcp.api import Tool, ToolContext

class ListModelsArgs(BaseModel):
    tenant_id: str | None = None

class ListModelsResult(BaseModel):
    models: list[dict]

async def _handler(args: ListModelsArgs, ctx: ToolContext) -> ListModelsResult:
    rows = await ctx... # call the SAME service function the REST route calls
    return ListModelsResult(models=rows)

Tool(
    name="bsgateway_models_list",
    description="List configured models for a tenant.",
    input_schema=ListModelsArgs,
    output_schema=ListModelsResult,
    handler=_handler,
    required_scopes=["gateway:models:read"],
    audit_event=None,            # read-only → no audit
)
```

Rules of the road:

- **No Typer auto-adapter.** Tools are written by hand. They mirror REST
  routes, not CLI commands.
- **Schemas live with the model.** `ListTools` derives JSON Schema from
  `input_schema.model_json_schema()` — no auto-derivation magic.
- **Scopes match the REST route.** `gateway:models:write`,
  `gateway:routing:read`, etc. The dispatcher evaluates them with the
  same `_scope_grants` semantics that `bsvibe_authz.require_scope` uses
  (super `*`, prefix `foo:*`, exact match).
- **Audit on success only.** Set `audit_event="gateway.models.created"`
  for mutations; leave `None` for reads. The registry never audits a
  failed call (validation error, scope denial, handler exception).
- **Errors are typed.** Raise `ToolError(code=..., message=...)` from
  handlers. Built-in codes: `tool_not_found`, `invalid_input`,
  `invalid_output`, `permission_denied`, `unauthenticated`. Handlers
  may use domain-specific codes (`not_found`, `conflict`).

## Adding a new tool

1. **Pick the layer.** Domain tool? Edit `server.py`. Admin tool that
   already has a REST endpoint? Edit `admin_tools.py` and bump
   `EXPECTED_ADMIN_TOOL_NAMES` (the catalog drift guard fails boot if
   they disagree).
2. **Define Pydantic input + output models.** Reuse REST request/response
   models if they exist. Output for admin tools uses
   `AdminToolResponse = RootModel[Any]` — the REST handler stays the
   source of truth for response shape.
3. **Write the handler.** Domain handlers receive `MCPService` via the
   `service_factory`. Admin handlers receive a `LoopbackCaller` and call
   the REST route in-process via `httpx.ASGITransport` — no router-logic
   duplication.
4. **Set scopes + audit_event** to match the equivalent REST route. Any
   route that emits a `gateway.*` audit event MUST set the same
   `audit_event` on the tool.
5. **Test.** Use the in-process pattern (memory
   `mcp-python-sdk-testing`) — extract `server.request_handlers`, send
   `ListToolsRequest` / `CallToolRequest` directly. Never spawn a
   subprocess.

## Catalog

39 tools register at boot (drift-guarded):

**Domain (9)** — `bsgateway_mcp_list_rules`, `bsgateway_mcp_create_rule`,
`bsgateway_mcp_update_rule`, `bsgateway_mcp_delete_rule`,
`bsgateway_mcp_list_models`, `bsgateway_mcp_register_model`,
`bsgateway_mcp_simulate_routing`, `bsgateway_mcp_get_cost_report`,
`bsgateway_mcp_get_usage_stats`.

**Admin (30)** — one per CLI sub-app action, named
`bsgateway_<subapp>_<action>`: `audit_list`, `execute`, `feedback_add`,
`feedback_list`, `intents_{list,add,update,delete}`,
`models_{list,show,add,update,remove}`, `presets_{list,apply}`,
`routes_test`, `rules_{list,add,update,delete}`,
`tenants_{list,add,show,update,delete}`,
`usage_{report,sparklines}`, `workers_{list,register,revoke}`.

## HTTP transport (`/mcp`)

Mounted by the FastAPI lifespan. Streamable-HTTP per the MCP SDK's
`StreamableHTTPSessionManager` (stateless, JSON responses). Per-request
headers are stashed on a `ContextVar` so `resolve_tool_context` can
authenticate the caller.

```bash
# Health check — exposes ready=true + tool_count
curl http://localhost:8000/mcp/health

# Auth: bsvibe-authz dispatch — pick one:
#   opaque token   (introspected, prefix bsv_sk_)
#   JWT            (from BSVibe-Auth, including PAT JWTs from the device flow)
curl -H "Authorization: Bearer ${BSV_OPAQUE_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
     http://localhost:8000/mcp/
```

## stdio launcher

```bash
# List the catalog without booting a server
bsgateway mcp list-tools                    # text, one name per line
bsgateway mcp list-tools --output json      # JSON: [{name, description, scopes}, ...]

# Run as an MCP stdio server (env: BSGATEWAY_PAT required for downstream auth)
bsgateway mcp serve --transport stdio

# HTTP — the gateway already serves /mcp; the CLI prints a hint
bsgateway mcp serve --transport http
```

The stdio path uses the same registry but stub callers — `ListTools` is
correct, but `CallTool` returns `code=unavailable` until a long-lived
HTTP loopback is wired. For production agent integrations, point the
client at the gateway's `/mcp` endpoint.

## Auth resolution

`resolve_tool_context(headers)` mirrors `bsgateway/api/deps.py` dispatch:

1. `Authorization: Bearer bsv_sk_…` → `verify_opaque_token` against the
   introspection endpoint (cached).
2. Otherwise → JWT via the bsvibe-authz JWT verifier.

The resolver returns a `ToolContext` carrying the authenticated `User`,
DB handle (when wired), audit app-state, and a structlog binder. Tokens
are NEVER logged — only the authenticated principal's id / email is
bound onto the logger.

## Testing

- **In-process only.** Build `ToolRegistry`, call `registry.call_tool()`
  directly, or build the MCP server via `build_mcp_server(registry)` and
  invoke `request_handlers[ListToolsRequest]` / `[CallToolRequest]`. No
  subprocess.
- **Loopback admin tests.** Inject a `StubLoopback` that records calls
  and returns canned bodies — verifies the dispatch path without
  requiring a live database.
- **Help-text tests.** Strip ANSI before asserting (Phase 3 lesson):

  ```python
  import re
  out = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
  assert "--profile" in out
  ```

## References

- Plan: `~/Docs/BSVibe_AI_Native_Control_Plane_Plan_2026-05-06.md`
- Phase 1 decisions: `~/Docs/BSVibe_Phase1_Decisions_2026-05-07.md`
- TDD: project rule `~/.claude/claude-skills/rules/tdd-enforcement.md`
- MCP SDK testing memory: `mcp-python-sdk-testing`
