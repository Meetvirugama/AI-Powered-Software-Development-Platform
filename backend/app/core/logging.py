"""Structured JSON logging and request-correlation middleware."""

from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.secret_redaction import SecretRedactingFilter

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """Emit predictable JSON logs that can be ingested by log platforms."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if request_id := request_id_context.get():
            payload["request_id"] = request_id
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            payload["exception"] = record.exc_text
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        # Include custom extra fields passed via extra={...}
        standard_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
        }
        for key, val in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                payload[key] = val

        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Configure the application logger once at startup."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    # Security (W2 Day 1): never write secrets from repository content, model
    # output or exception text into logs.
    handler.addFilter(SecretRedactingFilter())
    root_logger = logging.getLogger()
    existing_capture_handlers = [
        h for h in root_logger.handlers if "LogCaptureHandler" in type(h).__name__ or "capture" in type(h).__name__.lower()
    ]
    root_logger.handlers = [handler, *existing_capture_handlers]
    root_logger.setLevel(level.upper())


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request ID to logs and responses for each HTTP request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        token = request_id_context.set(request_id)
        started_at = time.perf_counter()
        logger = logging.getLogger("app.http")

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request completed method=%s path=%s status_code=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - started_at) * 1000,
            )
            return response
        finally:
            request_id_context.reset(token)
