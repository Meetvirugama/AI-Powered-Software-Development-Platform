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
if [ -n "$DATABASE_URL" ] && [[ "$DATABASE_URL" == *"postgres"* ]]; then
    echo "Applying database migrations using $ALEMBIC_CONFIG..."
    $PY_BIN -m alembic -c "$ALEMBIC_CONFIG" upgrade head || echo "Database migration notice: Continuing startup."
fi

PORT_TO_USE="${PORT:-${WEBSITES_PORT:-8000}}"
echo "Starting Uvicorn server on port $PORT_TO_USE (Azure proxy headers enabled)..."

exec $PY_BIN -m uvicorn main:app --host 0.0.0.0 --port "$PORT_TO_USE" --proxy-headers --forwarded-allow-ips='*'
