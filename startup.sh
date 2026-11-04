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

# Run alembic migrations if database is configured
if [ -n "$DATABASE_URL" ] && [[ "$DATABASE_URL" == *"postgres"* ]]; then
    echo "Applying database migrations..."
    $PY_BIN -m alembic upgrade head || echo "Database migration notice: Continuing startup."
fi

exec $PY_BIN -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
