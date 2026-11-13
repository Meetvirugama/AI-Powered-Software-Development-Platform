#!/bin/bash
set -e

export PYTHONPATH="${PYTHONPATH}:$(pwd)/backend:$(pwd)"

if command -v python3 &>/dev/null; then
    PY_BIN=python3
elif command -v python &>/dev/null; then
    PY_BIN=python
else
    echo "Python binary not found!"
    exit 1
fi

echo "Starting AI-Powered Software Development Platform..."

ROLE="${SERVICE_ROLE:-${1:-api}}"

if [ "$ROLE" = "worker" ] || [ "$ROLE" = "sync_worker" ]; then
    echo "Starting standalone background sync worker process..."
    exec $PY_BIN -m app.workers.sync_worker
fi

if [ "$ROLE" = "webhook_worker" ]; then
    echo "Starting standalone background webhook worker process..."
    exec $PY_BIN -m app.workers.webhook_worker
fi

# Locate alembic.ini (check backend/alembic.ini first, then ./alembic.ini)
ALEMBIC_CONFIG="backend/alembic.ini"
if [ ! -f "$ALEMBIC_CONFIG" ] && [ -f "alembic.ini" ]; then
    ALEMBIC_CONFIG="alembic.ini"
fi

# Run alembic migrations if database is configured (Supabase / Azure Postgres / local Postgres)
if [ -n "$DATABASE_URL" ] && [[ "$DATABASE_URL" == *"postgres"* ]] && [ "${RUN_MIGRATIONS_ON_STARTUP:-true}" != "false" ]; then
    echo "Applying database migrations using $ALEMBIC_CONFIG..."
    ENV_LOWER=$(echo "${APP_ENV:-development}" | tr '[:upper:]' '[:lower:]')
    if [ "$ENV_LOWER" = "production" ] || [ "$ENV_LOWER" = "prod" ]; then
        $PY_BIN -m alembic -c "$ALEMBIC_CONFIG" upgrade head
    else
        $PY_BIN -m alembic -c "$ALEMBIC_CONFIG" upgrade head || echo "Database migration notice: Continuing local startup."
    fi
fi

# Prefer Azure's explicit WEBSITES_PORT when provided, then PORT (Dockerfile default 8000)
PORT_TO_USE="${WEBSITES_PORT:-${PORT:-8000}}"
GRACEFUL_TIMEOUT="${UVICORN_GRACEFUL_TIMEOUT:-15}"
KEEP_ALIVE="${UVICORN_KEEP_ALIVE:-5}"

PROXY_ARGS=()
TRUST_PROXY_LOWER=$(echo "${TRUST_PROXY_HEADERS:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$TRUST_PROXY_LOWER" = "true" ] || [ "$TRUST_PROXY_LOWER" = "1" ] || [ "$TRUST_PROXY_LOWER" = "yes" ]; then
    PROXY_ARGS=(--proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}")
    echo "Starting Uvicorn server on port $PORT_TO_USE (trusted proxy headers enabled)..."
else
    echo "Starting Uvicorn server on port $PORT_TO_USE..."
fi

exec $PY_BIN -m uvicorn main:app \
    --host 0.0.0.0 \
    --port "$PORT_TO_USE" \
    --timeout-graceful-shutdown "$GRACEFUL_TIMEOUT" \
    --timeout-keep-alive "$KEEP_ALIVE" \
    "${PROXY_ARGS[@]}"
