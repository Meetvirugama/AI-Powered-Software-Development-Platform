"""Secret redaction for repository content, analysis results and logs.
Owner: Sukun — W2, Day 1 (Security Baseline)

Repository code is untrusted and may contain real credentials. Anything the
platform *emits* — LLM context, analysis results (explanations, findings,
generated tests, review reports), error messages and log lines — must pass
through ``redact_secrets`` first.

Rules:
  * A matched value is replaced with ``[REDACTED]``; the key name is kept
    (``API_KEY = "[REDACTED]"``) so the output still makes sense.
  * Findings record WHERE and WHICH pattern matched — never the value.
  * Redaction is idempotent: redacting already-redacted text changes nothing.

Usage::

    from app.core.secret_redaction import redact

    safe_text = redact(model_output)

    result = redact_secrets(chunk_text)
    result.text        # redacted text
    result.findings    # [SecretFinding(pattern="openai_key", line=12), ...]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class SecretFinding:
    pattern: str
    line: int  # 1-based line number in the scanned text


@dataclass
class RedactionResult:
    text: str
    findings: list[SecretFinding] = field(default_factory=list)

    @property
    def redacted(self) -> bool:
        return bool(self.findings)


# Order matters: whole-block and token-format patterns run before the generic
# "KEY = value" pattern so a value is only reported once.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # -----BEGIN RSA PRIVATE KEY----- ... -----END RSA PRIVATE KEY----- (whole block)
    ("private_key_block", re.compile(
        r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----.*?(?:-----END (?:[A-Z]+ )?PRIVATE KEY-----|\Z)",
        re.DOTALL,
    )),
    ("openai_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("groq_api_key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    # https://user:password@host  (e.g. git clone URLs with x-access-token)
    ("url_credentials", re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")),
    # Authorization: Bearer <token>
    ("bearer_token", re.compile(r"(?i)(?<=bearer )[A-Za-z0-9_\-\.=+/]{12,}")),
]

# KEY = "value" / KEY: 'value' / "key": "value" — quoted literals only, so code
# such as `token = request.cookies.get(...)` is left alone.
_QUOTED_ASSIGNMENT = re.compile(
    r"(?i)(?P<key>\b\w*(?:api_?key|secret|password|passwd|pwd|private_?key|access_?key|token|auth)\w*[\"']?)"
    r"(?P<sep>\s*[:=]\s*)(?P<q>[\"'])(?P<value>[^\"'\n]{6,})(?P=q)"
)
# .env style:  OPENAI_API_KEY=abc123...   (unquoted, at the start of a line)
_ENV_ASSIGNMENT = re.compile(
    r"(?m)^(?P<key>\s*(?:export\s+)?[A-Z0-9_]*(?:API_KEY|SECRET|PASSWORD|PRIVATE_KEY|TOKEN|ACCESS_KEY)[A-Z0-9_]*)"
    r"(?P<sep>=)(?P<value>[^\s#\"']{6,})"
)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def redact_secrets(text: str | None) -> RedactionResult:
    """Return ``text`` with every detected secret replaced by ``[REDACTED]``."""
    if not text:
        return RedactionResult(text or "")

    findings: list[SecretFinding] = []

    # Match positions are relative to the string passed to each .sub() call,
    # so line numbers are computed against that same string (`current`).
    for name, pattern in _PATTERNS:
        current = text

        def _sub(match: re.Match[str], _name: str = name, _current: str = current) -> str:
            if match.group(0) == REDACTED:
                return match.group(0)
            findings.append(SecretFinding(_name, _line_of(_current, match.start())))
            if _name == "private_key_block":
                # Keep the same number of lines so later line numbers stay correct.
                newlines = "\n" * match.group(0).count("\n")
                return f"-----BEGIN PRIVATE KEY-----{REDACTED}{newlines}-----END PRIVATE KEY-----"
            return REDACTED
        text = pattern.sub(_sub, text)

    for name, pattern in (("credential_assignment", _QUOTED_ASSIGNMENT), ("env_assignment", _ENV_ASSIGNMENT)):
        current = text

        def _sub_assignment(match: re.Match[str], _name: str = name, _current: str = current) -> str:
            value = match.group("value")
            if REDACTED in value:
                return match.group(0)
            findings.append(SecretFinding(_name, _line_of(_current, match.start())))
            quote = match.groupdict().get("q") or ""
            return f"{match.group('key')}{match.group('sep')}{quote}{REDACTED}{quote}"
        text = pattern.sub(_sub_assignment, text)

    findings.sort(key=lambda f: f.line)
    return RedactionResult(text, findings)


def redact(text: str | None) -> str:
    """Convenience wrapper returning only the redacted text."""
    return redact_secrets(text).text


def redact_obj(value: object) -> object:
    """Recursively redact strings inside dicts/lists/tuples (e.g. a JSON result payload)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_obj(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_obj(v) for v in value)
    return value


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_STANDARD_RECORD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class SecretRedactingFilter(logging.Filter):
    """Logging filter that redacts secrets from the message and any `extra=` fields.

    Attach it to a *handler* so it applies to every record the handler emits,
    including records from child loggers.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — never let logging crash the app
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        for key, value in list(vars(record).items()):
            if key not in _STANDARD_RECORD_ATTRS and isinstance(value, (str, dict, list, tuple)):
                setattr(record, key, redact_obj(value))
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True
