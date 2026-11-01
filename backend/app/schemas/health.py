"""Schemas for service-health responses."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


class ComponentHealth(BaseModel):
    status: str  # "healthy", "degraded", "unhealthy"
    message: str | None = None


class ReadinessResponse(BaseModel):
    status: str  # "ready", "degraded", "not_ready"
    version: str = "1.0.0"
    database: ComponentHealth
    redis: ComponentHealth
    llm_gateway: ComponentHealth
    rag_pipeline: ComponentHealth
    services: dict[str, str]
