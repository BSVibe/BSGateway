#!/bin/bash
set -e

GATEWAY_URL="${GATEWAY_URL:-http://localhost:4000}"
# LITELLM_MASTER_KEY MUST be supplied via the environment — no hardcoded
# fallback so a missing env var causes an immediate, visible failure
# instead of silently authenticating with a guessable string.
if [ -z "${LITELLM_MASTER_KEY:-}" ]; then
    echo "error: LITELLM_MASTER_KEY env var is required" >&2
    exit 1
fi
API_KEY="$LITELLM_MASTER_KEY"

echo "Testing BSGateway endpoints at $GATEWAY_URL"
echo "============================================="

# 1. Health check
echo ""
echo "[1] Health check..."
curl -s "$GATEWAY_URL/health" | python3 -m json.tool
echo ""

# 2. OpenAI format - simple request (should route to local LLM)
echo "[2] OpenAI format - simple request (expect: local/llama3)..."
curl -s "$GATEWAY_URL/v1/chat/completions" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "auto",
        "messages": [{"role": "user", "content": "hello, what is 2+2?"}],
        "max_tokens": 50
    }' | python3 -m json.tool
echo ""

# 3. OpenAI format - complex request (should route to claude-opus)
echo "[3] OpenAI format - complex request (expect: claude-opus)..."
curl -s "$GATEWAY_URL/v1/chat/completions" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "auto",
        "messages": [{"role": "user", "content": "Design a microservices architect for an e-commerce platform. Consider trade-off between consistency and availability. Include security audit recommendations and optimize for performance."}],
        "max_tokens": 100
    }' | python3 -m json.tool
echo ""

# 4. Anthropic format - simple request
echo "[4] Anthropic format - simple request..."
curl -s "$GATEWAY_URL/v1/messages" \
    -H "x-api-key: $API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "auto",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "hello"}]
    }' | python3 -m json.tool
echo ""

# 5. Direct model specification (passthrough)
echo "[5] Direct model - passthrough (expect: gpt-4o-mini)..."
curl -s "$GATEWAY_URL/v1/chat/completions" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "say hi"}],
        "max_tokens": 20
    }' | python3 -m json.tool
echo ""

# 6. Alias - local
echo "[6] Alias - local (expect: local/llama3)..."
curl -s "$GATEWAY_URL/v1/chat/completions" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "local",
        "messages": [{"role": "user", "content": "say hi"}],
        "max_tokens": 20
    }' | python3 -m json.tool
echo ""

echo "============================================="
echo "Endpoint tests complete."
