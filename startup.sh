#!/bin/bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)/backend"

if command -v python3 &>/dev/null; then
    PY_BIN=python3
elif command -v python &>/dev/null; then
    PY_BIN=python
else
    echo "Python binary not found!"
    exit 1
fi

exec $PY_BIN -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}
