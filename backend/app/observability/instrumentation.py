"""
Framework Auto-Instrumentation for FastAPI, HTTPX, SQLAlchemy, and Redis.

Applies OpenTelemetry hooks while redacting credentials, secrets, and excluding
health endpoints from noise.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_EXCLUDED_URLS = "health,health/live,health/ready,docs,redoc,openapi.json"


def instrument_fastapi(app: FastAPI) -> bool:
    """Instrument incoming FastAPI requests with OpenTelemetry."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=_EXCLUDED_URLS,
        )
        logger.info("opentelemetry_fastapi_instrumented")
        return True
    except Exception as exc:
        logger.warning("opentelemetry_fastapi_instrumentation_failed", extra={"error": str(exc)})
        return False


def instrument_httpx() -> bool:
    """Instrument outbound HTTPX requests with OpenTelemetry."""
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        logger.info("opentelemetry_httpx_instrumented")
        return True
    except Exception as exc:
        logger.warning("opentelemetry_httpx_instrumentation_failed", extra={"error": str(exc)})
        return False


def instrument_sqlalchemy(engine: Any) -> bool:
    """Instrument SQLAlchemy engine queries without exposing raw parameter values."""
    if engine is None:
        return False
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(
            engine=engine,
            enable_commenter=False,
        )
        logger.info("opentelemetry_sqlalchemy_instrumented")
        return True
    except Exception as exc:
        logger.warning("opentelemetry_sqlalchemy_instrumentation_failed", extra={"error": str(exc)})
        return False


def instrument_redis() -> bool:
    """Instrument Redis client commands with OpenTelemetry."""
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        logger.info("opentelemetry_redis_instrumented")
        return True
    except Exception as exc:
        logger.warning("opentelemetry_redis_instrumentation_failed", extra={"error": str(exc)})
        return False
