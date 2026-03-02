# BSGateway

LLM Gateway for cost-optimized routing across local (Ollama), OpenAI, and Anthropic models.

## How It Works

BSGateway sits in front of LiteLLM Proxy and intercepts every chat completion request via `async_pre_call_hook`. Based on request complexity, it routes to the cheapest capable model:

```
Client Request
    |
    v
[LiteLLM Proxy] --> [BSGateway Hook]
                        |
              +---------+---------+
              |         |         |
           simple    medium    complex
              |         |         |
     local/glm-4.7-flash  gpt-5-mini  claude-opus
```

**Four routing methods:**
1. **Passthrough** - known model names go directly (auto-derived from `model_list`)
2. **Alias** - shorthand names resolve to specific models (`auto` -> complexity routing)
3. **Pattern match** - glob patterns auto-route matching models (`claude-*` catches any Claude Code model)
4. **Auto-route** - classifier scores complexity 0-100, maps to tier

## Classifier Strategies

| Strategy | How | When |
|----------|-----|------|
| `static` | Weighted keyword/token/structure heuristics | Fast, no external dependency |
| `llm` | Local Ollama classifies in ~1 word, falls back to static | Default, best accuracy |
| `ml` | sklearn model (stub, trained from collected data) | Future |

## Quick Start

```bash
cp .env.example .env
# Fill in API keys

docker compose up
```

The gateway starts on `http://localhost:4000`.

## Configuration

Single file: `gateway.yaml`

- **Add a model**: add to `model_list` - routing auto-recognizes it as passthrough
- **Add an alias**: add to `routing.aliases`
- **Change classifier**: set `routing.classifier.strategy` to `static`, `llm`, or `ml`

```bash
# Use via OpenAI-compatible API
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "hello"}]}'

# "auto"              -> complexity-based routing
# "claude-sonnet-4-6" -> matched by "claude-*" pattern, auto-routed
# "claude-opus"       -> passthrough (defined in model_list)
```

- **Add a pattern**: add to `routing.auto_route_patterns` (fnmatch glob syntax)

## Data Collection

Every auto-routed request is logged to PostgreSQL (`routing_logs` table) for ML training:
- Original text + system prompt (for classification validation)
- Numeric features (token count, code blocks, conversation turns, etc.)
- Classification labels (tier, strategy, score)
- Optional embedding vector (via Ollama `qwen3-embedding`)

## Project Structure

```
bsgateway/
  core/
    config.py          # pydantic-settings (env vars)
    logging.py         # structlog JSON config
  routing/
    hook.py            # LiteLLM callback + config loader + BSGatewayRouter
    models.py          # Dataclasses (TierConfig, RoutingDecision, etc.)
    collector.py       # PostgreSQL logger (asyncpg)
    classifiers/
      base.py          # Protocol + text extraction utils
      static.py        # Weighted heuristic classifier
      llm.py           # Ollama-based classifier
      ml.py            # sklearn stub
    sql/
      schema.sql       # PostgreSQL DDL
      queries.sql      # Named queries (-- name: pattern)
  tests/               # pytest-asyncio, 64 tests
gateway.yaml           # Unified config (LiteLLM + routing)
```

## Development

```bash
# Install
pip install -e ".[dev]"

# Test
pytest bsgateway/tests/ -v

# Coverage
pytest bsgateway/tests/ --cov=bsgateway --cov-fail-under=80

# Lint
ruff check bsgateway/
```
