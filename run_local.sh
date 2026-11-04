#!/usr/bin/env bash
# =============================================================================
# Run AI-Powered Software Development Platform Locally
# Starts both Backend (FastAPI on :8000) and Frontend (Vite on :5173)
# =============================================================================

set -e

# Change directory to the repository root
cd "$(dirname "$0")"

echo "===================================================================="
echo " Starting AI-Powered Software Development Platform (Local Dev Mode) "
echo "===================================================================="

# 1. Resolve Python interpreter (virtual environment first)
if [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
    UVICORN_BIN=".venv/bin/uvicorn"
elif [ -f "venv/bin/python" ]; then
    PYTHON_BIN="venv/bin/python"
    UVICORN_BIN="venv/bin/uvicorn"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
    UVICORN_BIN="uvicorn"
else
    echo "Error: Python 3 not found. Please activate your virtual environment."
    exit 1
fi

# 2. Check if .env exists
if [ ! -f ".env" ]; then
    echo "Warning: .env not found. Creating from .env.example..."
    cp .env.example .env
fi

# 3. Check if frontend/.env.local exists
if [ ! -f "frontend/.env.local" ]; then
    echo "Creating frontend/.env.local with VITE_API_BASE_URL=http://localhost:8000/api/v1"
    echo "VITE_API_BASE_URL=http://localhost:8000/api/v1" > frontend/.env.local
fi

# 4. Run database migrations if database is configured
echo "Applying database migrations..."
$PYTHON_BIN -m alembic -c backend/alembic.ini upgrade head || echo "Database migration notice: Continuing local startup."

# 5. Trap Ctrl+C (SIGINT) and SIGTERM to kill all background processes cleanly
cleanup() {
    echo ""
    echo "Shutting down local servers..."
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    echo "Local servers stopped."
    exit 0
}
trap cleanup SIGINT SIGTERM

# 6. Start Backend (Uvicorn with auto-reload)
echo "Starting Backend API on http://localhost:8000..."
$UVICORN_BIN main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# 7. Start Frontend (Vite)
echo "Starting Frontend UI on http://localhost:5173..."
(cd frontend && npm run dev -- --host 0.0.0.0 --port 5173) &
FRONTEND_PID=$!

echo ""
echo "===================================================================="
echo "Platform running locally:"
echo "   - Frontend UI:   http://localhost:5173"
echo "   - Backend API:   http://localhost:8000"
echo "   - Swagger Docs:  http://localhost:8000/docs"
echo "   - Health Check:  http://localhost:8000/api/v1/health/ready"
echo "===================================================================="
echo "Press [Ctrl+C] to stop all local services."
echo ""

# Wait for both processes
wait
