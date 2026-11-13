"""Shared sanitization helpers and session base for AnalysisRun persistence aggregates."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Sensitive Data Sanitization Patterns (Aligned with Sukun's security gate)
# ---------------------------------------------------------------------------

_SECRET_REDACTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}")),
    ("groq_key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
    ("gemini_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("jwt_token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("db_connection_uri", re.compile(r"(?i)\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?):\/\/([^:\s]+):([^@\s]+)@")),
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z]+ )?PRIVATE KEY-----"
        ),
    ),
    (
        "private_key_header",
        re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    ),
    (
        "credential_assignment",
        re.compile(
            r"(?i)(\b\w*(?:api_?key|secret|password|passwd|private_?key|access_?token|auth_?token|token)\w*[\x22\x27]?\s*[:=]\s*[\x22\x27])([^\x22\x27\s]{8,})([\x22\x27])"
        ),
    ),
)

_PLACEHOLDER_HINTS = re.compile(
    r"(?i)(\[REDACTED\]|<[^>]*>|\.\.\.|x{4,}|example|placeholder|changeme|your[_-]|dummy|fake|mock|"
    r"test|sample|os\.environ|getenv|settings\.|process\.env|\$\{|none|null|true|false)"
)


def scrub_sensitive_text(text: Optional[str]) -> Optional[str]:
    """Redact raw secrets, tokens, credentials, and connection strings from text before persistence."""
    if not text or not isinstance(text, str):
        return text
    redacted = text
    for name, pattern in _SECRET_REDACTION_PATTERNS:
        if name == "credential_assignment":
            def _repl_assign(match: re.Match[str]) -> str:
                prefix, val, suffix = match.group(1), match.group(2), match.group(3)
                if _PLACEHOLDER_HINTS.search(val):
                    return match.group(0)
                return f"{prefix}[REDACTED]{suffix}"

            redacted = pattern.sub(_repl_assign, redacted)
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


def _ensure_datetime(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    return None



class AnalysisRepositoryBase:
    """Base SQLAlchemy session holder shared by all AnalysisRun domain aggregates."""

    def __init__(self, session: Session) -> None:
        self.session = session
