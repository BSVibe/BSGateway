#!/bin/bash
set -e

echo "Starting BSGateway..."
echo "====================="

# Ensure we're in the project root
cd "$(dirname "$0")/.."

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "[WARN] .env not found. Copy from .env.example and fill in your API keys:"
    echo "  cp .env.example .env"
    echo ""
fi

# Export config path for the custom hook
export GATEWAY_CONFIG_PATH="${GATEWAY_CONFIG_PATH:-config/gateway.yaml}"
export PYTHONPATH="${PYTHONPATH:-.}"

# Start LiteLLM proxy with unified config
exec litellm \
    --config "${GATEWAY_CONFIG_PATH}" \
    --port "${GATEWAY_PORT:-4000}" \
    --num_workers "${GATEWAY_WORKERS:-4}"
