#!/usr/bin/env bash
# BSGateway prod entrypoint — apply pending migrations, then start uvicorn.
#
# Why this exists: the runtime image used to call ``uvicorn`` directly,
# which left ``alembic upgrade head`` to whatever runs deploys. Phase 8
# dogfood (2026-05-11) caught a fresh ``relation "models" does not
# exist`` 500 because the prod DB never had migration ``0004_models_*``
# applied. Treating "image started" and "schema is at head" as one
# atomic step removes that whole class of drift.
#
# The migrations are idempotent (no-op when already at head), and we
# fail-closed: if alembic exits non-zero the container exits, which
# orchestration retries via ``restart: unless-stopped``. A half-migrated
# DB never serves traffic.

set -euo pipefail

cd /app

echo "[entrypoint] applying alembic migrations…"
alembic upgrade head
echo "[entrypoint] alembic up to date — starting uvicorn"

exec python -m uvicorn \
    bsgateway.api.app:create_app \
    --factory \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips=*
