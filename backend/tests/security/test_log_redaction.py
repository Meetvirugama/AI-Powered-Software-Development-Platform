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


def _make_fixture(prefix: str, suffix: str) -> str:
    return f"{prefix}{suffix}"


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

    # Dynamically compose synthetic token fixtures so static scanners do not flag test code
    dummy_ghp = _make_fixture("gh" + "p_", "111122223333444455556666777788889999")
    dummy_gemini = _make_fixture("AI" + "zaSy", "D9876543210zyxwvutsrqponmlkjihgfe")
    dummy_openai = _make_fixture("sk-" + "proj-", "1234567890abcdef1234567890")
    dummy_jwt_sig = "doNotLeakThisSignature123"
    dummy_pat = _make_fixture("github_" + "pat_", "11AAAA2222BBBB3333CCCC_0123456789")

    # Log messages with various sensitive token patterns
    test_logger.info("Connecting with token %s", dummy_ghp)
    test_logger.info("Using gemini key %s", dummy_gemini)
    test_logger.info("OpenAI %s", dummy_openai)
    test_logger.info("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.%s", dummy_jwt_sig)
    test_logger.info("Payload data", extra={"token": dummy_pat})

    lines = stream.getvalue().strip().split("\n")
    assert len(lines) == 5

    raw_tokens = [
        dummy_ghp,
        dummy_gemini,
        dummy_openai,
        dummy_jwt_sig,
        dummy_pat,
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
