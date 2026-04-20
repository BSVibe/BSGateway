# CLAUDE.md

## Project

BSGateway - LLM Gateway wrapping LiteLLM Proxy with complexity-based cost-optimized routing.

## Key Commands

```bash
# Run tests
pytest bsgateway/tests/ -v

# Run with coverage
pytest bsgateway/tests/ --cov=bsgateway --cov-fail-under=80

# Lint
ruff check bsgateway/

# Start (Docker)
docker compose up
```

## Architecture

- **LiteLLM Proxy** handles OpenAI/Anthropic API compatibility
- **BSGateway hook** (`bsgateway/routing/hook.py`) intercepts via `async_pre_call_hook`
- **Single config** (`gateway.yaml`) defines both LiteLLM models and routing rules
- `passthrough_models` are auto-derived from `model_list[].model_name` - no manual list needed
- **Classifier strategies**: `static` (heuristic), `llm` (Ollama), `ml` (sklearn stub)
- **Intent-based routing**: tenants describe a request kind in natural language; the
  rules engine matches via `classified_intent` (embedding similarity in `bsgateway/rules/intent.py`)
  and routes to the user-chosen model. The dashboard exposes this as a single
  Notion Mail-style "RouteCard" that pairs an Intent + Rule under the hood.
- **Per-tenant embedding**: each tenant chooses its own embedding model via
  `tenants.settings.embedding` JSONB (set via `PUT /tenants/{id}/embedding-settings`).
  The chosen model is recorded on each `intent_examples.embedding_model` row so
  that, after a model swap, stale embeddings are automatically skipped at
  classification time and can be backfilled with `POST /tenants/{id}/intents/reembed`.
  Implementation in `bsgateway/embedding/` (Protocol-based provider, factory,
  serialization, hydration with stale-skip).
- **Data collection**: PostgreSQL via asyncpg, SQL in `.sql` files (not ORM)
- **Auth**: Supabase JWT via `bsvibe-auth` package — tenant mapping from `app_metadata.tenant_id`
- **Executor workers** (`bsgateway/executor/`, `worker/`): remote machines that run
  Claude Code / Codex CLI. Registered workers are auto-inserted into `tenant_models`
  with `provider='executor'` and `extra_params.worker_id` pinning dispatch to that
  specific worker. Routing rules target worker names just like LLM models.
  - **Install token**: admin mints via `POST /api/v1/workers/install-token`, shares
    with worker machines. Worker registration uses `X-Install-Token` header.
    One-line install: `curl http://<gateway>/api/v1/workers/install.sh | bash`.
  - **Dispatch**: `ChatService._execute_via_worker` creates an `executor_tasks` row,
    publishes to `tasks:worker:{worker_id}` Redis stream, polls for result.
  - Worker package is standalone (no bsgateway dependency) — `worker/pyproject.toml`.
- **Sparkline usage**: `GET /api/v1/tenants/{id}/usage/sparklines?days=7` returns
  per-model per-day request counts for the Model Registry page. Merges
  `routing_logs.resolved_model` (LLM) and `executor_tasks JOIN workers.name` (executor).

## Conventions

- Python 3.11+, type hints on all public functions
- `pyproject.toml` + `uv` for deps (no requirements.txt)
- `pydantic-settings` for env config, `structlog` for logging
- `dataclasses` for internal data, async for all I/O
- Tests: `pytest-asyncio`, mock all external APIs, minimum 80% coverage
- No `Co-Authored-By` in commits
- Commit format: `type(scope): description`
- Deferred follow-ups (`TODO:` comments) are mirrored in
  [`docs/TODO.md`](docs/TODO.md) for central tracking. When adding a
  `TODO:` during review, also add the row there; when picking one up,
  remove both the inline comment and the row in the same PR.

## Important Files

| File | Purpose |
|------|---------|
| `gateway.yaml` | Single source of truth for models + routing |
| `bsgateway/routing/hook.py` | Config loader, BSGatewayRouter, LiteLLM callback |
| `bsgateway/routing/models.py` | All dataclasses (TierConfig, RoutingDecision, etc.) |
| `bsgateway/routing/collector.py` | PostgreSQL data collection (asyncpg pool) |
| `bsgateway/routing/classifiers/` | Strategy pattern: base protocol, static, llm, ml |
| `bsgateway/core/config.py` | Settings(BaseSettings) - env vars |
| `bsgateway/core/security.py` | AES-256-GCM encryption for provider API keys |
| `bsgateway/api/deps.py` | GatewayAuthContext, auth dependencies (BSVibe-Auth) |
| `bsgateway/routing/sql/` | schema.sql + queries.sql (named query pattern) |
| `bsgateway/embedding/` | EmbeddingProvider protocol, LiteLLM impl, per-tenant factory, stale-skip hydration |
| `bsgateway/executor/` | Executor registry, dispatcher, install token helpers, SQL schema for `workers` + `executor_tasks` |
| `bsgateway/streams.py` | Redis Streams abstraction (`publish`/`consume`/`acknowledge`) |
| `bsgateway/api/routers/workers.py` | Worker register/heartbeat/poll/result, install token CRUD, `install.sh`/`source.tar.gz` serving |
| `bsgateway/api/routers/execute.py` | Async task endpoints (`POST /execute`, `GET /tasks/{id}`) |
| `bsgateway/api/routers/usage.py` | Daily usage + sparkline endpoint |
| `worker/` | Standalone worker package (httpx + pydantic-settings) — `main.py`, `executors.py`, `install.sh` |
