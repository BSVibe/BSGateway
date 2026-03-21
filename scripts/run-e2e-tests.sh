#!/bin/bash
set -e

# Resolve project root relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configurable ports and temp directory
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
TMP_DIR="${E2E_TMP_DIR:-$(mktemp -d)}"
mkdir -p "$TMP_DIR"

# Cleanup on exit or signal
cleanup() {
  echo -e "\n${YELLOW}Cleaning up...${NC}"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

echo -e "${YELLOW}[E2E Test Suite]${NC} Starting BSGateway E2E Tests\n"

# Check prerequisites
echo -e "${YELLOW}[1/5]${NC} Checking prerequisites..."
if ! which npm &> /dev/null; then
  echo -e "${RED}Error: npm not found${NC}"
  exit 1
fi
if ! uv --version &> /dev/null; then
  echo -e "${RED}Error: uv not found${NC}"
  exit 1
fi
echo -e "${GREEN}✓${NC} npm and uv are installed\n"

# Install frontend dependencies
echo -e "${YELLOW}[2/5]${NC} Installing frontend dependencies..."
cd "$PROJECT_ROOT/frontend"
npm install --silent
echo -e "${GREEN}✓${NC} Frontend dependencies installed\n"

# Build frontend
echo -e "${YELLOW}[3/5]${NC} Building frontend..."
npm run build
echo -e "${GREEN}✓${NC} Frontend built successfully\n"

# Start backend in background
echo -e "${YELLOW}[4/5]${NC} Starting backend API server..."
cd "$PROJECT_ROOT"
uv run uvicorn bsgateway.api.app:create_app \
  --factory \
  --host 127.0.0.1 \
  --port "$BACKEND_PORT" \
  --log-level error > "$TMP_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Wait for backend to be ready (use /health endpoint)
echo "Waiting for API to be ready..."
max_attempts=30
attempt=0
while ! curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" > /dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ $attempt -gt $max_attempts ]; then
    echo -e "${RED}✗ API server failed to start${NC}"
    echo "Backend logs:"
    cat "$TMP_DIR/backend.log"
    exit 1
  fi
  sleep 1
done
echo -e "${GREEN}✓${NC} API server is ready\n"

# Start frontend dev server in background
echo -e "${YELLOW}[5/5]${NC} Starting frontend dev server..."
cd "$PROJECT_ROOT/frontend"
npm run dev > "$TMP_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "Frontend PID: $FRONTEND_PID"

# Wait for frontend to be ready
echo "Waiting for frontend to be ready..."
max_attempts=30
attempt=0
while ! curl -sf "http://localhost:${FRONTEND_PORT}" > /dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ $attempt -gt $max_attempts ]; then
    echo -e "${RED}✗ Frontend dev server failed to start${NC}"
    echo "Frontend logs:"
    cat "$TMP_DIR/frontend.log"
    exit 1
  fi
  sleep 1
done
echo -e "${GREEN}✓${NC} Frontend dev server is ready\n"

# Run E2E tests
echo -e "${YELLOW}[Running E2E Tests]${NC}\n"
cd "$PROJECT_ROOT/frontend"
E2E_RESULT=0
npm run test:e2e || E2E_RESULT=$?

if [ $E2E_RESULT -eq 0 ]; then
  echo -e "${GREEN}✓ All E2E tests passed!${NC}"
else
  echo -e "${RED}✗ E2E tests failed${NC}"
  echo "Backend logs:"
  tail -20 "$TMP_DIR/backend.log"
  echo -e "\nFrontend logs:"
  tail -20 "$TMP_DIR/frontend.log"
fi

exit $E2E_RESULT
