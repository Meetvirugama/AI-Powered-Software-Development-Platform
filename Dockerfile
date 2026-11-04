# Production Dockerfile for Azure App Service & Azure Container Apps
FROM python:3.11-slim

# Install system dependencies: git (for workspace operations), build tools, curl (health checks), and libpq
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache dependency installations
COPY requirements.txt ./
COPY backend/requirements.txt ./backend/requirements.txt
COPY backend/requirements-dev.txt ./backend/requirements-dev.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy platform source tree
COPY . .

# Set execution permissions for Azure startup script
RUN chmod +x /app/startup.sh

# Configure Python runtime and Azure networking environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app/backend:/app" \
    PORT=8000 \
    APP_ENV=production

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/v1/health/live || exit 1

ENTRYPOINT ["/app/startup.sh"]
