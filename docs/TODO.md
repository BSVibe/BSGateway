# BSGateway TODO

Central tracker for deferred follow-ups — items surfaced during review but
intentionally scoped out of their originating PR. Each entry mirrors an
inline `TODO:` comment in the source so grep-based navigation works both
ways.

Update the "Status" and "Reference PR" columns when picking an item up.
Remove completed rows once the corresponding inline comment is gone.

## Executor / worker system

| # | Item | Source | Trigger | Status |
|---|------|--------|---------|--------|
| E2 | Extract shared `executor_core` package for the subprocess logic that twins `bsgateway/executor/{claude_code,codex}.py` and `worker/executors.py`. Keep stdlib-only so the worker stays dependency-light. | `worker/executors.py` module docstring | Adding a 3rd executor type (e.g. `aider`) — opencode is already in worker | Open |
| E3 | Add partial expression index on `tenants.settings->>'worker_install_token_hash'` so `resolve_install_token_tenant` lookups don't seq-scan. DDL:<br>`CREATE INDEX tenants_worker_install_token_hash ON tenants ((settings->>'worker_install_token_hash')) WHERE settings ? 'worker_install_token_hash';` | `bsgateway/api/routers/workers.py` (above `_invalidate_models_cache`) | Tenant count reaches ~10k, or install-token lookup p99 shows in profiler | Open |
| E4 | opencode multi-turn session reuse — currently `OpenCodeExecutor.execute()` creates a fresh `/session` per task, dropping conversational state. Wire a session-cache keyed by tenant + conversation hint (e.g. an OpenAI-API `metadata.conversation_id`) so subsequent turns hit the same opencode session. Add an LRU eviction policy. | `worker/executors.py::OpenCodeExecutor.execute` | Users start sending multi-turn opencode requests | Open |
| E5 | Forward in-band OpenAI `tools` / `tool_choice` definitions to executor CLIs (claude `--allowed-tools`, opencode session `tools`). Today only `system` and out-of-band MCP servers are pass-through. | `bsgateway/chat/service.py::_execute_via_worker` | First user complaint that custom OpenAI-style `tools` aren't honored | Open |
| E5a | ~~Out-of-band MCP server injection — chat completion `metadata.mcp_servers` ⇒ worker writes claude `--mcp-config` tmpfile (chmod 0600), passes path on the CLI. Empty/missing ⇒ no flag (back-compat). codex / opencode v1 ignore `mcp_servers` (codex CLI lacks MCP, opencode follow-up).~~ | `worker/executors.py::ClaudeCodeExecutor.execute`, `bsgateway/chat/service.py::_execute_via_worker` | BSNexus M0 needs run-scoped MCP callbacks for Decisions / artifact tools | **Done (2026-05-03)** |
| E5b | ~~Extend MCP injection to opencode — pass ``mcp_servers`` from context as the ``mcpServers`` field on the session create body. codex MCP still pending the CLI feature.~~ | `worker/executors.py::OpenCodeExecutor.execute` | BSNexus / external user picks `opencode` executor and needs MCP | **Done (2026-05-03)** |
| E6 | Workspace-dir wire from `metadata.workspace_dir` to **claude + codex** executors' `cwd`. Defaults to `"."` when omitted. ``service.py`` rejects non-string values to ``"."`` so a malformed payload doesn't surface as a cryptic FileNotFoundError. Validation (absolute-only, no `..`) deferred to caller. | `worker/main.py::_handle_task`, `bsgateway/executor/dispatcher.py::dispatch_task`, `bsgateway/chat/service.py::_execute_via_worker` | Done together with E5a — BSNexus needs the worker to operate inside its repo worktree | **Done (claude+codex, 2026-05-03)** |
| E6b | Per-session workspace_dir for opencode. ``opencode serve`` is a long-lived process whose ``cwd`` is fixed at spawn — session create body has no per-session ``directory`` field today. Either (a) spawn ``opencode run --cwd <ws>`` per task instead of reusing the server, or (b) wait for opencode upstream to add a session-level cwd. v1 leaves opencode tasks running in the worker's process cwd. | `worker/executors.py::OpenCodeExecutor` | A BSNexus tenant picks ``executor_type=opencode`` and needs per-task workspace isolation | Open |
| E6c | Verify the opencode message-body model fields against the worker's pinned opencode version via ``GET /doc``. The ``ai_model`` plumbing sends ``providerID``+``modelID`` (or bare ``model``) on the ``/session/{id}/message`` body; opencode upstream has drifted these field names/locations before. Lock the shape or move model selection to the session-create body if needed. | `worker/executors.py::OpenCodeExecutor.execute` | An opencode model-pinned registry entry routes a request and the CLI ignores the model | Open |

## Infrastructure / cross-cutting

| # | Item | Source | Trigger | Status |
|---|------|--------|---------|--------|
| I1 | Register connection-level jsonb codec in `get_pool` via `init=` callback — `conn.set_type_codec('jsonb', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')`. Removes per-query Python-side JSONB decoding scattered across routers (see `list_workers`, `safe_json_loads` callers). | `bsgateway/core/database.py::get_pool` | Before the next router that adds JSONB decoding, or when touching that code | Open |

## Frontend

| # | Item | Source | Trigger | Status |
|---|------|--------|---------|--------|
| F1 | Extract a `<Sparkline bars color enabled />` component. Today it's inlined at two sites in `ModelsPage` (LLM grid / Executor Workers). Duplicated color + height ternaries. | `frontend/src/pages/ModelsPage.tsx::sparkBarsFor` | A 3rd consumer (Analytics page, per-worker detail view) appears | Open |

## Security

| # | Item | Source | Trigger | Status |
|---|------|--------|---------|--------|
| S2 | Audit other tables for tenant-scoping coverage parallel to routing_logs (executor_tasks already does it inline; rules / audit_events / api_keys / tenant_models / feedback should be re-checked at repository level). | n/a | Sprint 1+ hardening continuation | Open |

## Conventions

- Each inline `TODO:` in the code should link back here by keeping its
  wording close to the corresponding row so `rg TODO:` + this file stay
  in sync.
- When picking up an item, open a PR with the corresponding fix and
  remove both the inline `TODO:` and its row here in the same commit.
- New deferred items added during reviews go here, not into the PR
  description or a chat thread — this file is the single source of truth.
