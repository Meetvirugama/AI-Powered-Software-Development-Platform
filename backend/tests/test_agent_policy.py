"""
Tests for Agent Tool Policy and Security Boundaries (task.md §11, §22.6).

Verifies:
- Path traversal protections (relative path enforcement, dot-dot rejection, encoded traversal, null byte protection).
- Line range bounds (150 lines maximum span, positive start line, end >= start).
- Search query and symbol name sanitization.
- Secret redaction on tool outputs.
- Byte size truncation.
"""

import pytest
from ai.agent.errors import AgentToolValidationError
from ai.agent.policy import (
    sanitize_and_redact,
    sanitize_relative_path,
    truncate_tool_output,
    validate_line_range,
    validate_search_query,
    validate_symbol_name,
)

# ---------------------------------------------------------------------------
# Path Security Tests
# ---------------------------------------------------------------------------


def test_sanitize_relative_path_valid() -> None:
    assert sanitize_relative_path("backend/app/main.py") == "backend/app/main.py"
    assert sanitize_relative_path("src/components/Header.tsx") == "src/components/Header.tsx"
    assert sanitize_relative_path("utils.py") == "utils.py"


@pytest.mark.parametrize(
    "invalid_path",
    [
        "../secret.env",
        "../../etc/passwd",
        "backend/../../etc/shadow",
        "/etc/passwd",
        "/var/log/app.log",
        "C:\\Windows\\System32\\cmd.exe",
        "D:/repo/file.py",
        "backend/./file.py",
        "backend/%2e%2e/secret.env",
        "backend/foo\x00bar.py",
        "",
        "   ",
    ],
)
def test_sanitize_relative_path_rejects_malicious_paths(invalid_path: str) -> None:
    with pytest.raises(AgentToolValidationError):
        sanitize_relative_path(invalid_path)


# ---------------------------------------------------------------------------
# Line Range Tests
# ---------------------------------------------------------------------------


def test_validate_line_range_valid() -> None:
    start, end = validate_line_range(1, 100)
    assert start == 1
    assert end == 100

    # Max span exactly 150 lines
    s, e = validate_line_range(10, 159)
    assert (e - s + 1) == 150


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (0, 50),       # start < 1
        (-5, 10),      # negative start
        (50, 40),      # end < start
        (1, 200),      # span 200 > 150
        ("abc", 10),   # non-integer
    ],
)
def test_validate_line_range_invalid(start: int | str, end: int | str) -> None:
    with pytest.raises(AgentToolValidationError):
        validate_line_range(start, end)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Search and Symbol Query Tests
# ---------------------------------------------------------------------------


def test_validate_search_query() -> None:
    q, top_k = validate_search_query("  auth token refresh  ", top_k=8)
    assert q == "auth token refresh"
    assert top_k == 8

    # Clamping
    _, top_k_clamped = validate_search_query("query", top_k=50)
    assert top_k_clamped == 10

    _, top_k_clamped_min = validate_search_query("query", top_k=0)
    assert top_k_clamped_min == 1

    with pytest.raises(AgentToolValidationError):
        validate_search_query("")


def test_validate_symbol_name() -> None:
    assert validate_symbol_name("refresh_access_token") == "refresh_access_token"
    assert validate_symbol_name("AuthService.authenticate") == "AuthService.authenticate"

    with pytest.raises(AgentToolValidationError):
        validate_symbol_name("sym; DROP TABLE users;--")

    with pytest.raises(AgentToolValidationError):
        validate_symbol_name("")


# ---------------------------------------------------------------------------
# Redaction and Truncation Tests
# ---------------------------------------------------------------------------


def test_sanitize_and_redact() -> None:
    secret_text = "API_KEY = 'sk-1234567890abcdef1234567890abcdef'"
    redacted = sanitize_and_redact(secret_text)
    assert "sk-1234567890abcdef" not in redacted


def test_truncate_tool_output() -> None:
    short_text = "short output"
    res, is_trunc = truncate_tool_output(short_text, max_bytes=100)
    assert res == short_text
    assert is_trunc is False

    long_text = "A" * 500
    res_trunc, is_trunc = truncate_tool_output(long_text, max_bytes=200)
    assert is_trunc is True
    assert len(res_trunc.encode("utf-8")) <= 200
    assert "[... Truncated" in res_trunc
