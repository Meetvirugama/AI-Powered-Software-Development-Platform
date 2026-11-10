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

# 4. Check for and free stale processes on ports 8000, 5173, and 5174 if needed
LSOF_CMD=""
if command -v lsof &>/dev/null; then
    LSOF_CMD="lsof"
elif [ -x "/usr/sbin/lsof" ]; then
    LSOF_CMD="/usr/sbin/lsof"
fi

if [ -n "$LSOF_CMD" ]; then
    for p in 8000 5173 5174; do
        PIDS=$($LSOF_CMD -i :"$p" -t 2>/dev/null || true)
        if [ -n "$PIDS" ]; then
            echo "Notice: Freeing occupied port $p (PIDs: $PIDS)..."
            echo "$PIDS" | xargs kill -9 2>/dev/null || true
            sleep 0.5
        fi
    done
fi

# 5. Run database migrations if database is configured
echo "Applying database migrations..."
$PYTHON_BIN -m alembic -c backend/alembic.ini upgrade head || echo "Database migration notice: Continuing local startup."

# 6. Trap Ctrl+C (SIGINT) and SIGTERM to kill all background processes cleanly
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
$UVICORN_BIN main:app --reload --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 1 --timeout-keep-alive 5 &
BACKEND_PID=$!

# 7. Start Frontend (Vite)
echo "Starting Frontend UI on http://localhost:5173..."
(cd frontend && npm run dev -- --host 0.0.0.0 --port 5173) &
FRONTEND_PID=$!

echo "Waiting for backend services to initialize..."
for i in {1..25}; do
    if curl -s -f http://127.0.0.1:8000/api/v1/health/ready >/dev/null 2>&1; then
        echo "Backend services are healthy and ready."
        break
    fi
    sleep 1
done

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
