"""Schemas for service-health responses."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


class ComponentHealth(BaseModel):
    status: str  # "healthy", "degraded", "unhealthy"
    message: str | None = None


class OperationalReadinessMetrics(BaseModel):
    sync_worker_heartbeat_age_s: float | None = None
    webhook_backlog: int = 0
    scanner_availability: dict[str, bool] = {}
    sandbox_backend_ok: bool = True


class ReadinessResponse(BaseModel):
    status: str  # "ready", "degraded", "not_ready"
    version: str = "1.0.0"
    database: ComponentHealth
    redis: ComponentHealth
    llm_gateway: ComponentHealth
    rag_pipeline: ComponentHealth
    services: dict[str, str]
    operations: OperationalReadinessMetrics | None = None
