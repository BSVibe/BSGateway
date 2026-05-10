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
COPY pyproject.toml uv.lock* gateway.yaml alembic.ini ./
COPY alembic/ ./alembic/
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
COPY --from=builder /usr/local/bin/alembic /usr/local/bin/alembic
COPY --from=builder /workspace/bsgateway ./bsgateway
COPY --from=builder /workspace/alembic ./alembic
COPY --from=builder /workspace/alembic.ini ./alembic.ini
COPY --from=builder /workspace/gateway.yaml .
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

RUN chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=10s --timeout=5s --retries=3 --start-period=15s \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# `entrypoint.sh` runs ``alembic upgrade head`` and then exec's
# uvicorn. ``--forwarded-allow-ips=*`` makes uvicorn honour
# X-Forwarded-Proto from Caddy (which is on the host network, not
# 127.0.0.1 from inside the container), so FastAPI's auto-redirect
# for trailing slashes emits https:// Location headers instead of
# http:// — without this, browser CORS rejects the redirect during
# cross-origin requests from https://gateway.bsvibe.dev.
CMD ["/usr/local/bin/entrypoint.sh"]
