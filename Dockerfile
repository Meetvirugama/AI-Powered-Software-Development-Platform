# syntax=docker/dockerfile:1

# =============================================================================
# Stage 1: Dependency Builder (compiles wheels & installs prod deps into /opt/venv)
# Pinned by OCI manifest digest for python:3.11-slim
# =============================================================================
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r backend/requirements.txt

ARG RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
ENV HF_HOME=/opt/hf_cache
RUN mkdir -p /opt/models && \
    python -c "import os; from sentence_transformers import CrossEncoder; CrossEncoder(os.environ['RERANKER_MODEL']).save_pretrained('/opt/models/reranker')" && \
    test -f /opt/models/reranker/config.json


# =============================================================================
# Stage 2: Minimal Hardened Production Runtime (no compilers, non-root user)
# =============================================================================
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid appuser --shell /bin/sh --create-home appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=appuser:appuser /opt/models /opt/models
COPY --chown=appuser:appuser . .

RUN chmod +x /app/startup.sh && \
    mkdir -p /app/.workspaces /opt/hf_cache && \
    chown -R appuser:appuser /app/.workspaces /opt/hf_cache

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app/backend:/app" \
    PORT=8000 \
    APP_ENV=production \
    HF_HOME=/opt/hf_cache \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    RERANKER_MODEL_PATH=/opt/models/reranker

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/api/v1/health/live || exit 1

ENTRYPOINT ["/app/startup.sh"]
