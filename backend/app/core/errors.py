"""Shared API error types and FastAPI exception handlers."""

from __future__ import annotations

import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.secret_redaction import redact


class ErrorCode:
    """Machine-readable error codes exposed by the public API."""

    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    REPOSITORY_NOT_FOUND = "REPOSITORY_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    ANALYSIS_RUN_NOT_FOUND = "ANALYSIS_RUN_NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_TARGET = "UNSUPPORTED_TARGET"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    CONFLICT = "CONFLICT"
    BAD_REQUEST = "BAD_REQUEST"
    OAUTH_CONFIGURATION_ERROR = "OAUTH_CONFIGURATION_ERROR"
    OAUTH_STATE_INVALID = "OAUTH_STATE_INVALID"
    OAUTH_EXCHANGE_FAILED = "OAUTH_EXCHANGE_FAILED"
    GITHUB_PROFILE_FAILED = "GITHUB_PROFILE_FAILED"
    GITHUB_API_ERROR = "GITHUB_API_ERROR"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


class APIError(Exception):
    """An expected error that is serialized using the public error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = redact(message)
        self.retryable = retryable


def error_response(status_code: int, code: str, message: str, *, retryable: bool = False) -> JSONResponse:
    safe_message = redact(message)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": safe_message, "retryable": retryable}},
    )


async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, retryable=exc.retryable)


async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        return error_response(exc.status_code, ErrorCode.NOT_FOUND, "Resource not found.")
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return error_response(exc.status_code, ErrorCode.UNAUTHORIZED, "Authentication is required.")
    if exc.status_code == status.HTTP_403_FORBIDDEN:
        return error_response(exc.status_code, ErrorCode.FORBIDDEN, "Access denied.")
    message = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."
    return error_response(exc.status_code, "HTTP_ERROR", message)


async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    _logger = logging.getLogger("app.errors")
    try:
        raw_errors = exc.errors()
        # Log structured detail at DEBUG for backend observability (never exposes values)
        _logger.debug(
            "request_validation_failed",
            extra={"error_count": len(raw_errors), "fields": [e.get("loc") for e in raw_errors]},
        )
        # Build safe field-path list: tuples like ("body", "target", "path") → "body.target.path"
        failed_fields: list[str] = [
            ".".join(str(part) for part in e.get("loc", ())) for e in raw_errors[:10]
        ]
    except Exception:
        failed_fields = []

    content: dict = {
        "error": {
            "code": ErrorCode.INVALID_REQUEST,
            "message": "Request validation failed.",
            "retryable": False,
        }
    }
    if failed_fields:
        content["error"]["details"] = {"invalid_fields": failed_fields}

    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=content)


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logging.getLogger("app.errors").exception("Unhandled API exception", exc_info=exc)
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorCode.INTERNAL_SERVER_ERROR,
        "An unexpected error occurred.",
        retryable=True,
    )
