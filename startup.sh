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

if [ -z "${RERANKER_MODEL_PATH:-}" ] && [ -f "$(pwd)/model_cache/reranker/config.json" ]; then
    export RERANKER_MODEL_PATH="$(pwd)/model_cache/reranker"
fi
if [ -n "${RERANKER_MODEL_PATH:-}" ] && [ -f "${RERANKER_MODEL_PATH}/config.json" ]; then
    export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
    export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
fi
export HF_HUB_DISABLE_TELEMETRY="${HF_HUB_DISABLE_TELEMETRY:-1}"

echo "Starting AI-Powered Software Development Platform..."

# Locate alembic.ini (check backend/alembic.ini first, then ./alembic.ini)
ALEMBIC_CONFIG="backend/alembic.ini"
if [ ! -f "$ALEMBIC_CONFIG" ] && [ -f "alembic.ini" ]; then
    ALEMBIC_CONFIG="alembic.ini"
fi

ROLE="${SERVICE_ROLE:-${1:-api}}"

if [ "$ROLE" = "migrate" ]; then
    echo "Running release database migrations once per release using $ALEMBIC_CONFIG (T9.2)..."
    exec $PY_BIN -m alembic -c "$ALEMBIC_CONFIG" upgrade head
fi

if [ "$ROLE" = "worker" ] || [ "$ROLE" = "sync_worker" ]; then
    echo "Starting standalone background sync worker process..."
    exec $PY_BIN -m app.workers.sync_worker
fi

if [ "$ROLE" = "sync_worker_web" ]; then
    exec $PY_BIN -m uvicorn app.workers.sync_worker:worker_app \
        --host 0.0.0.0 --port "${WEBSITES_PORT:-${PORT:-8000}}"
fi

if [ "$ROLE" = "webhook_worker" ]; then
    echo "Starting standalone background webhook worker process..."
    exec $PY_BIN -m app.workers.webhook_worker
fi

if [ "$ROLE" = "runner" ]; then
    echo "Starting isolated sandbox runner daemon..."
    exec $PY_BIN -m runner.main
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
# Must exceed the Azure front-end / Vercel proxy idle reuse window to avoid reconnects and 502s.
KEEP_ALIVE="${UVICORN_KEEP_ALIVE:-75}"

ENV_LOWER=$(echo "${APP_ENV:-development}" | tr '[:upper:]' '[:lower:]')
# Default to 1 Uvicorn worker to stay within Azure App Service B1/B2 memory and DB pool limits.
# Opt into multi-worker mode explicitly by setting UVICORN_WORKERS=2+ on larger SKUs.
WORKERS="${UVICORN_WORKERS:-1}"
WORKER_ARGS=()
if [ "$WORKERS" -gt 1 ] 2>/dev/null; then
    WORKER_ARGS=(--workers "$WORKERS")
fi

PROXY_ARGS=()
TRUST_PROXY_LOWER=$(echo "${TRUST_PROXY_HEADERS:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$TRUST_PROXY_LOWER" = "true" ] || [ "$TRUST_PROXY_LOWER" = "1" ] || [ "$TRUST_PROXY_LOWER" = "yes" ]; then
    DEFAULT_IPS="*"
    if [ "$ENV_LOWER" = "production" ] || [ "$ENV_LOWER" = "prod" ]; then
        DEFAULT_IPS="127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    fi
    FORWARDED_IPS="${FORWARDED_ALLOW_IPS:-$DEFAULT_IPS}"
    PROXY_ARGS=(--proxy-headers --forwarded-allow-ips="$FORWARDED_IPS")
    echo "Starting Uvicorn server on port $PORT_TO_USE (workers=$WORKERS, trusted proxy headers enabled: $FORWARDED_IPS)..."
else
    echo "Starting Uvicorn server on port $PORT_TO_USE (workers=$WORKERS)..."
fi

exec $PY_BIN -m uvicorn main:app \
    --host 0.0.0.0 \
    --port "$PORT_TO_USE" \
    --timeout-graceful-shutdown "$GRACEFUL_TIMEOUT" \
    --timeout-keep-alive "$KEEP_ALIVE" \
    "${WORKER_ARGS[@]}" \
    "${PROXY_ARGS[@]}"
