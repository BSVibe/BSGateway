# BSNexus → BSGateway request metadata (Phase 0 P0.7)

Lockin §2 architectural shift #1 moves the LLM `run.pre` / `run.post`
precheck from BSNexus's `audit_sink.py` to the BSGateway LiteLLM proxy
hook. BSGateway now owns the BSupervisor call; BSNexus only has to
forward the run-correlation identifiers it already has.

## Where the metadata enters

BSNexus calls `litellm.acompletion(metadata={...})` (or any equivalent
that lands at `data["metadata"]` inside the LiteLLM proxy callback).
The chat-service path that BSNexus already uses for the tenant-id plumb
fix (`docs/TODO.md` S1) is the right place to add the new keys.

## Required keys

| Key                    | Type             | Required        | Notes |
|------------------------|------------------|-----------------|-------|
| `tenant_id`            | UUID string      | yes             | Existing key from Sprint-0 plumb (`test_litellm_tenant_id_plumb`). |
| `run_id`               | UUID string      | yes (for audit) | When **omitted**, BSGateway skips BSupervisor entirely (proxy-direct traffic has no run to correlate). |
| `project_id`           | UUID string      | recommended     | Lets BSupervisor scope incidents per project. |
| `request_id`           | UUID/opaque      | recommended     | Mirrors `Request.id` so the founder can trace which user message produced which audit row. |
| `parent_run_id`        | UUID string      | optional        | Set on hierarchical runs (subagent, retry). |
| `composition_id`       | UUID string      | optional        | `CompositionSnapshot.id` — already in BSNexus's old `audit_sink.preflight` payload. |
| `agent_name`           | string           | recommended     | Becomes `agent_id` on the BSupervisor `EventRequest`. Defaults to `service:bsgateway` when missing. |
| `cost_estimate_cents`  | int              | optional        | Surfaces in incident dashboards alongside the actual cost reported by `run.post`. |

Any additional keys are forwarded under `metadata.extras` on the
BSupervisor event payload (preserved untouched). BSGateway will not
parse them.

## Wire shape BSGateway emits

For one user-facing chat completion BSGateway will issue **two**
BSupervisor `POST /api/events` calls (when audit is enabled):

```jsonc
// run.pre — synchronous, blocks dispatch with a 200ms budget.
{
  "agent_id": "<agent_name|service:bsgateway>",
  "source": "bsgateway",
  "event_type": "run.pre",
  "action": "llm.dispatch",
  "target": "<resolved_model>",
  "metadata": {
    "tenant_id": "...",
    "run_id": "...",
    "project_id": "...",
    "request_id": "...",
    "agent_name": "...",
    "composition_id": "...",
    "cost_estimate_cents": 12,
    "model": "<resolved_model>",
    /* + any extras BSNexus passed through */
  }
}

// run.post — fire-and-forget after the LLM responds (success or error).
{
  "agent_id": "...",
  "source": "bsgateway",
  "event_type": "run.post",
  "action": "llm.complete",
  "target": "<resolved_model>",
  "metadata": {
    "tenant_id": "...",
    "run_id": "...",
    "status": "success" | "error",
    "tokens_in": 120,
    "tokens_out": 80,
    "duration_ms": 842,
    "error": "<exc message>" /* present only on failure */
  }
}
```

`Authorization: Bearer <service-jwt>` carries an `aud=bsupervisor`,
`scope=bsupervisor.events` token minted by BSGateway's
`ServiceTokenMinter`. BSupervisor's `POST /api/events` is service-only
(`bsupervisor_service_auth` from BSupervisor PR #4) — user JWTs are
rejected.

## Migration order

1. **This PR (BSGateway P0.5 + P0.7)** — BSGateway is wired to call
   BSupervisor; default `BSUPERVISOR_AUDIT_ENABLED=false`. With the
   flag off the gateway behaves exactly like Sprint 4.
2. **BSNexus P0.7 PR (separate)** — `audit_sink.py` becomes a Noop;
   instead `audit_sink.preflight` only logs a debug line, and chat
   service forwards `run_id` / `project_id` / `request_id` /
   `agent_name` / `cost_estimate_cents` / `composition_id` via the
   LiteLLM `metadata` bag.
3. **Cutover** — flip `BSUPERVISOR_AUDIT_ENABLED=true` on BSGateway.
   Until then both paths can coexist (BSNexus calls BSupervisor
   directly; BSGateway is dark for audit).

## Rollback

Setting `BSUPERVISOR_AUDIT_ENABLED=false` (or unsetting the
service-account credentials) immediately disables the BSGateway path
without restarting BSNexus. The BSupervisor receiver continues to
accept service tokens — there is no schema change to revert.
