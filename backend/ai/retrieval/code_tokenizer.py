"""
Code-aware Tokenizer & Search Text Generator.

Produces normalized, identifier-split, and path-aware text for PostgreSQL
simple-dictionary full-text search.

Handles:
- CamelCase and PascalCase splitting (e.g. getUserById -> get, user, by, id)
- snake_case and kebab-case splitting (e.g. auth_token_expired -> auth, token, expired)
- Acronym preservation (e.g. HTTPResponse -> http, response, HTTPResponse)
- Numeric identifiers and version fragments (e.g. v2, sha256 -> v2, 2, sha, 256)
- File paths and extensions (e.g. src/auth/token_service.py -> src, auth, token, service, py)
- Deduplication while preserving high-signal terms.
"""

from __future__ import annotations

import os
import re
from typing import Final

__all__ = [
    "generate_code_search_text",
    "normalize_identifier",
    "split_identifier",
    "tokenize_code",
]

# Regex patterns for identifier tokenization
# Identifies camelCase transitions: lower to Upper
_CAMEL_CASE_RE: Final[re.Pattern[str]] = re.compile(r"([a-z0-9])([A-Z])")
# Identifies acronym transitions: consecutive Uppercase followed by Upper+Lower (e.g. HTTPResponse -> HTTP Response)
_ACRONYM_RE: Final[re.Pattern[str]] = re.compile(r"([A-Z]+)([A-Z][a-z])")
# Splits on underscores, hyphens, and non-alphanumeric boundaries
_DELIMITER_RE: Final[re.Pattern[str]] = re.compile(r"[_\-\.\s/\\]+")
# Matches valid identifiers or words
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_]+|[A-Za-z0-9\-]+")
# Matches standalone digits or alphanumeric tokens with digits
_DIGIT_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"([a-zA-Z]+)([0-9]+)|([0-9]+)([a-zA-Z]+)")

# Stop tokens to avoid polluting search index
_TRIVIAL_TOKENS: Final[frozenset[str]] = frozenset({
    "", " ", "\t", "\n", "\r",
})


def split_identifier(identifier: str) -> list[str]:
    """
    Split an identifier into semantic sub-word components.

    Examples:
        - 'getUserById' -> ['getUserById', 'get', 'user', 'by', 'id', 'get_user_by_id']
        - 'UserAuthenticationService' -> ['UserAuthenticationService', 'user', 'authentication', 'service']
        - 'AUTH_TOKEN_EXPIRED' -> ['AUTH_TOKEN_EXPIRED', 'auth', 'token', 'expired']
        - 'HTTPResponse' -> ['HTTPResponse', 'http', 'response']
        - 'token-service.py' -> ['token-service.py', 'token', 'service', 'py']
    """
    if not identifier or not identifier.strip():
        return []

    cleaned = identifier.strip()
    results: list[str] = [cleaned]

    # Pre-process acronyms: e.g. "HTTPServer" -> "HTTP Server"
    s1 = _ACRONYM_RE.sub(r"\1 \2", cleaned)
    # Process camel case: e.g. "getUserById" -> "get User By Id"
    s2 = _CAMEL_CASE_RE.sub(r"\1 \2", s1)

    # Split on delimiters: spaces, underscores, hyphens, dots, slashes
    parts = _DELIMITER_RE.split(s2)

    sub_words: list[str] = []
    for part in parts:
        part_clean = part.strip()
        if not part_clean:
            continue
        sub_words.append(part_clean.lower())

        # Sub-split alphanumeric segments with numbers, e.g. "sha256" -> "sha", "256", "v2" -> "v", "2"
        match = _DIGIT_SPLIT_RE.match(part_clean)
        if match:
            for g in match.groups():
                if g and len(g) > 0 and g.lower() != part_clean.lower():
                    sub_words.append(g.lower())

    # Build snake_case equivalent if multiple sub-words
    if len(sub_words) > 1:
        snake = "_".join(sub_words)
        if snake != cleaned.lower():
            results.append(snake)

    results.extend(sub_words)

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for token in results:
        token_lower = token.lower()
        if token_lower not in _TRIVIAL_TOKENS and token_lower not in seen:
            seen.add(token_lower)
            deduped.append(token)

    return deduped


def normalize_identifier(identifier: str) -> list[str]:
    """Alias for split_identifier to conform to specification."""
    return split_identifier(identifier)


def tokenize_code(text: str, max_tokens: int = 2000) -> list[str]:
    """
    Tokenize code content extracting original identifiers and their sub-components.

    Bounded by max_tokens to prevent memory expansion on large files.
    """
    if not text or not text.strip():
        return []

    raw_tokens = _WORD_RE.findall(text)
    token_results: list[str] = []
    seen: set[str] = set()

    for raw in raw_tokens:
        if len(token_results) >= max_tokens:
            break
        if len(raw) <= 1:
            continue
        sub_tokens = split_identifier(raw)
        for st in sub_tokens:
            st_lower = st.lower()
            if st_lower not in seen and len(st_lower) > 1:
                seen.add(st_lower)
                token_results.append(st)
                if len(token_results) >= max_tokens:
                    break

    return token_results


def generate_code_search_text(
    content: str,
    file_path: str = "",
    symbol_name: str = "",
    symbol_kind: str = "",
    max_chars: int = 30000,
) -> str:
    """
    Generate the rich, searchable code_search_text representation for a chunk.

    Includes:
    1. Symbol name and split tokens (boosted priority at head)
    2. File path and normalized path components
    3. Symbol kind / metadata
    4. Code content identifier tokens
    5. Raw code content (truncated to max_chars)

    Returns:
        Space-separated search text ready for PostgreSQL 'simple' tsvector indexing.
    """
    sections: list[str] = []

    # 1. Symbol name and tokens
    if symbol_name:
        sym_tokens = split_identifier(symbol_name)
        sections.append(" ".join(sym_tokens))

    # 2. File path tokens
    if file_path:
        norm_path = file_path.replace("\\", "/")
        sections.append(norm_path)
        path_base = os.path.basename(norm_path)
        sections.append(path_base)
        path_tokens = split_identifier(norm_path)
        sections.append(" ".join(path_tokens))

    # 3. Symbol kind
    if symbol_kind:
        sections.append(symbol_kind.lower())

    # 4. Tokenized content identifiers
    content_sample = content[:max_chars] if content else ""
    if content_sample:
        tokens = tokenize_code(content_sample, max_tokens=500)
        if tokens:
            sections.append(" ".join(tokens))
        sections.append(content_sample)

    return " ".join(s for s in sections if s.strip())
