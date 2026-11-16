"""Security Test: Log Redaction Filter (TST-14 / ISS-019).

Verifies that GitHub tokens, Google/Gemini API keys, OpenAI keys, Bearer tokens,
and credentials are automatically redacted when formatted and emitted by the logging pipeline.
"""

from __future__ import annotations

import io
import json
import logging

from app.core.logging import JsonFormatter
from app.core.secret_redaction import REDACTED, SecretRedactingFilter


def test_tst14_log_redaction_handler_redacts_tokens_in_json() -> None:
    """SecretRedactingFilter and JsonFormatter must redact sensitive tokens from emitted log output."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SecretRedactingFilter())

    test_logger = logging.getLogger("test_security_redaction_logger")
    test_logger.handlers = [handler]
    test_logger.propagate = False
    test_logger.setLevel(logging.INFO)

    # Log messages with various sensitive token patterns
    test_logger.info("Connecting with token ghp_111122223333444455556666777788889999")
    test_logger.info("Using gemini key AIzaSyD9876543210zyxwvutsrqponmlkjihgfe")
    test_logger.info("OpenAI sk-proj-1234567890abcdef1234567890")
    test_logger.info("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature123")
    test_logger.info("Payload data", extra={"token": "github_pat_11AAAA2222BBBB3333CCCC_0123456789"})

    lines = stream.getvalue().strip().split("\n")
    assert len(lines) == 5

    raw_tokens = [
        "ghp_111122223333444455556666777788889999",
        "AIzaSyD9876543210zyxwvutsrqponmlkjihgfe",
        "sk-proj-1234567890abcdef1234567890",
        "doNotLeakThisSignature123",
        "github_pat_11AAAA2222BBBB3333CCCC_0123456789",
    ]

    for line in lines:
        parsed = json.loads(line)
        # Ensure none of the raw secrets appear anywhere in the JSON output
        for secret in raw_tokens:
            assert secret not in line, f"Secret {secret} leaked in log line: {line}"

        # Ensure REDACTED is present in the formatted message or extra field
        message = parsed.get("message", "")
        extra_token = parsed.get("token", "")
        assert REDACTED in message or REDACTED in extra_token
