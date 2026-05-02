FROM python:3.11-slim AS builder

WORKDIR /workspace
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Backend image carries Python only — frontend ships from Vercel
# (gateway.bsvibe.dev) so we don't bundle/build it here. Avoids the
# private GitHub Packages auth dance during docker build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python dependencies (cache layer)
COPY pyproject.toml uv.lock* gateway.yaml ./
COPY bsgateway/ ./bsgateway/
RUN uv pip install --system --compile-bytecode --no-cache .

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

RUN chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=10s --timeout=5s --retries=3 --start-period=15s \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "bsgateway.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
