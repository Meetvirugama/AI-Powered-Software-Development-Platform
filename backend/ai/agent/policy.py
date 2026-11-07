"""
Tool Execution and Permission Policy (task.md §11).

Enforces:
- Repository isolation and ownership bounds.
- Path traversal protection (rejection of '..', leading slashes, null bytes).
- Line range clamping and maximum line span bounds.
- Tool input argument validation and sanitization.
- Secret redaction on tool execution outputs.
- Byte size truncation on tool results.
"""

from __future__ import annotations

import re
import urllib.parse

from app.core.secret_redaction import redact

from ai.agent.errors import AgentToolValidationError

# Safety bounds from task.md §13
MAX_READ_LINES: int = 150
MAX_QUERY_CHARS: int = 1_000
DEFAULT_SEARCH_TOP_K: int = 5
MAX_SEARCH_TOP_K: int = 10
MAX_SYMBOL_CHARS: int = 200
MAX_TOOL_RESULT_BYTES: int = 8_192
MAX_TOTAL_EVIDENCE_BYTES: int = 24_576


def sanitize_relative_path(path: str) -> str:
    """
    Validate and normalize repository-relative file paths.

    Rejects:
    - Path traversal sequences ('..', '%2e%2e', etc.).
    - Absolute paths (leading '/' or Windows drive letters).
    - Null bytes or control characters.

    Returns:
        Cleaned, forward-slash-delimited relative path.

    Raises:
        AgentToolValidationError: If the path contains dangerous sequences.
    """
    if not path or not path.strip():
        raise AgentToolValidationError("File path must not be empty.")

    raw = path.strip()

    # URL decode to catch obfuscated traversal attempts
    decoded = urllib.parse.unquote(raw)

    # Reject null bytes or ASCII control codes
    if "\x00" in decoded or any(ord(c) < 32 for c in decoded):
        raise AgentToolValidationError("File path contains forbidden control characters.")

    # Normalize backslashes
    normalized = decoded.replace("\\", "/")

    # Reject absolute paths
    if normalized.startswith("/") or bool(re.match(r"^[a-zA-Z]:", normalized)):
        raise AgentToolValidationError("Absolute paths are not permitted; provide a repository-relative path.")

    # Reject traversal sequences
    parts = normalized.split("/")
    for part in parts:
        if part in ("..", "."):
            raise AgentToolValidationError(f"Path traversal sequence '{part}' is forbidden.")

    # Clean redundant slashes
    clean_path = "/".join(p for p in parts if p)
    if not clean_path:
        raise AgentToolValidationError("Invalid empty file path after normalization.")

    return clean_path


def validate_line_range(start_line: int, end_line: int) -> tuple[int, int]:
    """
    Validate line boundaries for source inspection.

    Rules:
    - start_line >= 1
    - end_line >= start_line
    - span <= MAX_READ_LINES (150 lines)

    Raises:
        AgentToolValidationError: If bounds are violated.
    """
    try:
        s = int(start_line)
        e = int(end_line)
    except (ValueError, TypeError) as exc:
        raise AgentToolValidationError(f"Invalid non-integer line numbers: {exc}") from exc

    if s < 1:
        raise AgentToolValidationError(f"start_line must be at least 1, got {s}.")
    if e < s:
        raise AgentToolValidationError(f"end_line ({e}) cannot be less than start_line ({s}).")

    span = e - s + 1
    if span > MAX_READ_LINES:
        raise AgentToolValidationError(
            f"Requested line range ({span} lines) exceeds maximum allowable span of {MAX_READ_LINES} lines."
        )

    return s, e


def validate_search_query(query: str, top_k: int | None = None) -> tuple[str, int]:
    """
    Validate code search query parameters.

    Rules:
    - query must be non-empty and <= MAX_QUERY_CHARS
    - top_k clamped to 1..MAX_SEARCH_TOP_K
    """
    if not query or not query.strip():
        raise AgentToolValidationError("Search query must contain non-whitespace text.")

    cleaned_query = query.strip()
    if len(cleaned_query) > MAX_QUERY_CHARS:
        cleaned_query = cleaned_query[:MAX_QUERY_CHARS]

    effective_top_k = DEFAULT_SEARCH_TOP_K
    if top_k is not None:
        try:
            tk = int(top_k)
            effective_top_k = max(1, min(tk, MAX_SEARCH_TOP_K))
        except (ValueError, TypeError):
            effective_top_k = DEFAULT_SEARCH_TOP_K

    return cleaned_query, effective_top_k


def validate_symbol_name(name: str) -> str:
    """
    Validate symbol identifier query.

    Rules:
    - Non-empty, <= MAX_SYMBOL_CHARS
    - Stripped of illegal symbols
    """
    if not name or not name.strip():
        raise AgentToolValidationError("Symbol name must not be empty.")

    clean_name = name.strip()
    if len(clean_name) > MAX_SYMBOL_CHARS:
        raise AgentToolValidationError(f"Symbol name exceeds maximum length of {MAX_SYMBOL_CHARS} characters.")

    # Basic regex check allowing typical programming identifiers (including namespaces and operators)
    if not re.match(r"^[a-zA-Z0-9_\.:<>\$#-]+$", clean_name):
        raise AgentToolValidationError(f"Symbol name '{clean_name[:30]}' contains invalid characters.")

    return clean_name


def truncate_tool_output(content: str, max_bytes: int = MAX_TOOL_RESULT_BYTES) -> tuple[str, bool]:
    """
    Ensure tool output payload does not exceed configured byte limits.

    Returns:
        (truncated_content, is_truncated)
    """
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content, False

    # Truncate at safe byte boundary and append indicator
    truncated_bytes = encoded[: max_bytes - 128]
    safe_text = truncated_bytes.decode("utf-8", errors="ignore")
    truncated_notice = f"\n\n[... Truncated: output exceeded {max_bytes} bytes limit ...]"
    return safe_text + truncated_notice, True


def sanitize_and_redact(content: str) -> str:
    """Apply standard secret redaction on tool output before returning to model."""
    if not content:
        return ""
    return redact(content)
