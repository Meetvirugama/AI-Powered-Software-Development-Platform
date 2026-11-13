"""Shared exceptions, constants, and sanitization helpers for Task persistence aggregates."""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.errors import APIError, ErrorCode
from app.models.task import TaskStatus
from app.schemas.task import VALID_TASK_TRANSITIONS




class InvalidStateTransitionError(APIError, ValueError):
    """Raised when an illegal lifecycle state transition is requested."""

    def __init__(
        self,
        message: str = "Invalid state transition.",
        status_code: int = 409,
        code: str = ErrorCode.INVALID_STATE_TRANSITION,
        *,
        retryable: bool = False,
    ):
        APIError.__init__(self, status_code=status_code, code=code, message=message, retryable=retryable)
        ValueError.__init__(self, message)


class TaskNotFoundError(APIError, LookupError):
    """Raised when a task cannot be found in the specified repository."""

    def __init__(
        self,
        message: str = "Task not found.",
        status_code: int = 404,
        code: str = ErrorCode.TASK_NOT_FOUND,
        *,
        retryable: bool = False,
    ):
        APIError.__init__(self, status_code=status_code, code=code, message=message, retryable=retryable)
        LookupError.__init__(self, message)


class PlanNotFoundError(APIError, LookupError):
    """Raised when a referenced plan version does not exist."""

    def __init__(
        self,
        message: str = "Plan not found.",
        status_code: int = 404,
        code: str = ErrorCode.NOT_FOUND,
        *,
        retryable: bool = False,
    ):
        APIError.__init__(self, status_code=status_code, code=code, message=message, retryable=retryable)
        LookupError.__init__(self, message)


# ---------------------------------------------------------------------------
# State-Transition Rules Specification (Week 3 — §7.1 & §7.2)
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    status: set(targets) for status, targets in VALID_TASK_TRANSITIONS.items()
}


# ---------------------------------------------------------------------------
# Sensitive Data Sanitization Patterns (Zero Credential Invariant)
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("jwt_token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("db_connection_uri", re.compile(r"(?i)\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?):\/\/([^:\s]+):([^@\s]+)@")),
    (
        "credential_assignment",
        re.compile(
            r"(?i)(\b\w*(?:api_?key|secret|password|passwd|private_?key|access_?token|auth_?token|token)\w*[\x22\x27]?\s*[:=]\s*[\x22\x27])([^\x22\x27\s]{8,})([\x22\x27])"
        ),
    ),
)


def scrub_sensitive_text(text: Optional[str]) -> Optional[str]:
    """Redact raw secrets, tokens, and credentials from text before persistence."""
    if not text or not isinstance(text, str):
        return text
    redacted = text
    for name, pattern in _SECRET_PATTERNS:
        if name == "credential_assignment":
            redacted = pattern.sub(r"\1[REDACTED]\3", redacted)
        elif name == "db_connection_uri":
            redacted = pattern.sub(r"\1://\2:[REDACTED]@", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def scrub_sensitive_data(val: Any) -> Any:
    """Recursively scrub sensitive credential strings in text, dicts, or lists."""
    if isinstance(val, str):
        return scrub_sensitive_text(val)
    elif isinstance(val, dict):
        return {k: scrub_sensitive_data(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [scrub_sensitive_data(item) for item in val]
    elif isinstance(val, tuple):
        return tuple(scrub_sensitive_data(item) for item in val)
    return val


def _ensure_uuid(val: Any) -> Optional[uuid.UUID]:
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return None



class TaskRepositoryBase:
    """Base SQLAlchemy session holder shared by all Task domain aggregates."""

    def __init__(self, session: Session) -> None:
        self.session = session
