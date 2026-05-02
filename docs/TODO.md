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
| E1 | Replace DB polling with Redis pub/sub in `_await_task_completion` — worker `/result` handler publishes to `task:{id}:done`, dispatcher awaits via `SUBSCRIBE` with timeout. Cuts up to `timeout/poll_interval` DB hits per task. | `bsgateway/chat/service.py::_await_task_completion` | Worker throughput grows, or DB load from polling becomes visible | Open |
| E2 | Extract shared `executor_core` package for the subprocess logic that twins `bsgateway/executor/{claude_code,codex}.py` and `worker/executors.py`. Keep stdlib-only so the worker stays dependency-light. | `worker/executors.py` module docstring | Adding a 3rd executor type (e.g. `aider`, `opencode`) | Open |
| E3 | Add partial expression index on `tenants.settings->>'worker_install_token_hash'` so `resolve_install_token_tenant` lookups don't seq-scan. DDL:<br>`CREATE INDEX tenants_worker_install_token_hash ON tenants ((settings->>'worker_install_token_hash')) WHERE settings ? 'worker_install_token_hash';` | `bsgateway/api/routers/workers.py` (above `_invalidate_models_cache`) | Tenant count reaches ~10k, or install-token lookup p99 shows in profiler | Open |

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
