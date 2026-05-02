FROM python:3.11-slim AS builder

WORKDIR /workspace
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Install uv + node (for frontend build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python dependencies (cache layer)
COPY pyproject.toml uv.lock* gateway.yaml ./
COPY bsgateway/ ./bsgateway/
RUN uv pip install --system --compile-bytecode --no-cache .

# Build frontend (Next.js 15 static export → frontend/dist)
COPY frontend/ ./frontend/
RUN cd frontend && corepack enable && corepack prepare pnpm@10.33.0 --activate \
    && CI=true pnpm install --frozen-lockfile && pnpm run build

# Runtime stage
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

# Copy Python packages
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /workspace/bsgateway ./bsgateway
COPY --from=builder /workspace/gateway.yaml .
COPY --from=builder /workspace/frontend/dist ./frontend/dist

RUN chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=10s --timeout=5s --retries=3 --start-period=15s \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "bsgateway.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
