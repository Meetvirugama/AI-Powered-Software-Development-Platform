"""Shared API error types and FastAPI exception handlers."""

from __future__ import annotations

import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode:
    """Machine-readable error codes exposed by the public API."""

    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    REPOSITORY_NOT_FOUND = "REPOSITORY_NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    OAUTH_CONFIGURATION_ERROR = "OAUTH_CONFIGURATION_ERROR"
    OAUTH_STATE_INVALID = "OAUTH_STATE_INVALID"
    OAUTH_EXCHANGE_FAILED = "OAUTH_EXCHANGE_FAILED"
    GITHUB_PROFILE_FAILED = "GITHUB_PROFILE_FAILED"
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
        self.message = message
        self.retryable = retryable


def error_response(status_code: int, code: str, message: str, *, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "retryable": retryable}},
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


async def validation_exception_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        ErrorCode.INVALID_REQUEST,
        "Request validation failed.",
    )


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logging.getLogger("app.errors").exception("Unhandled API exception", exc_info=exc)
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorCode.INTERNAL_SERVER_ERROR,
        "An unexpected error occurred.",
        retryable=True,
    )
