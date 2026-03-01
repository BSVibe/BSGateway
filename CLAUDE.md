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
- **Single config** (`config/gateway.yaml`) defines both LiteLLM models and routing rules
- `passthrough_models` are auto-derived from `model_list[].model_name` - no manual list needed
- **Classifier strategies**: `static` (heuristic), `llm` (Ollama), `ml` (sklearn stub)
- **Data collection**: PostgreSQL via asyncpg, SQL in `.sql` files (not ORM)

## Conventions

- Python 3.11+, type hints on all public functions
- `pyproject.toml` + `uv` for deps (no requirements.txt)
- `pydantic-settings` for env config, `structlog` for logging
- `dataclasses` for internal data, async for all I/O
- Tests: `pytest-asyncio`, mock all external APIs, minimum 80% coverage
- No `Co-Authored-By` in commits
- Commit format: `type(scope): description`

## Important Files

| File | Purpose |
|------|---------|
| `config/gateway.yaml` | Single source of truth for models + routing |
| `bsgateway/routing/hook.py` | Config loader, BSGatewayRouter, LiteLLM callback |
| `bsgateway/routing/models.py` | All dataclasses (TierConfig, RoutingDecision, etc.) |
| `bsgateway/routing/collector.py` | PostgreSQL data collection (asyncpg pool) |
| `bsgateway/routing/classifiers/` | Strategy pattern: base protocol, static, llm, ml |
| `bsgateway/core/config.py` | Settings(BaseSettings) - env vars |
| `bsgateway/routing/sql/` | schema.sql + queries.sql (named query pattern) |
