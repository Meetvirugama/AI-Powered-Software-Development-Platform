"""Token budget management, estimation, and allocation routines.
Owner: Meet — W1-12
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Sequence
from typing import Any

try:
    import tiktoken
except ImportError:
    tiktoken = None  # type: ignore

from .models import ChatMessage

logger = logging.getLogger(__name__)

_ENCODING_NAME: str = "cl100k_base"
_OVERHEAD_TOKENS: int = 500


@functools.lru_cache(maxsize=8)
def _get_encoder(encoding_name: str = _ENCODING_NAME) -> Any:
    """Return the cached tiktoken encoder (thread-safe and reusable)."""
    if tiktoken is None:
        return None
    return tiktoken.get_encoding(encoding_name)


def count_tokens(text: str, encoding_name: str = _ENCODING_NAME) -> int:
    """
    Return the number of tokens in *text* using cl100k_base encoding.

    Safety:
        Uses ``disallowed_special=()`` so untrusted repository code containing
        special tokens (e.g. ``<|endoftext|>``) does not raise a ValueError.
    """
    if not text:
        return 0
    if tiktoken is None:
        return max(1, len(text) // 4)
    try:
        enc = _get_encoder(encoding_name)
        if enc is None:
            return max(1, len(text) // 4)
        return len(enc.encode(text, disallowed_special=()))
    except (ValueError, UnicodeError, TypeError, KeyError) as exc:
        logger.warning(
            "token_counting_fallback",
            extra={"error": str(exc), "text_len": len(text)},
        )
        # Sane heuristic fallback (approx. 4 characters per token) if tokenizer fails
        return max(1, len(text) // 4)


def fit_history(
    history: Sequence[ChatMessage],
    budget: int,
    formatter: Callable[[ChatMessage], str],
) -> tuple[int, list[ChatMessage]]:
    """
    Fit as many history messages as possible within *budget* tokens.

    Iterates from newest to oldest so recent turns take precedence.
    Returns (total_tokens_used, kept_messages) in chronological order.
    """
    if budget <= 0:
        return 0, []

    kept: list[ChatMessage] = []
    used = 0
    for msg in reversed(history):
        tokens = count_tokens(formatter(msg))
        if used + tokens > budget:
            break
        kept.append(msg)
        used += tokens

    kept.reverse()  # Restore original chronological order
    return used, kept


def fit_items(
    items: Sequence[Any],
    budget: int,
    formatter: Callable[[Any], str],
) -> tuple[int, list[Any]]:
    """
    Generic greedy token fitter — preserves items in priority order.

    Args:
        items:     Ordered list of items (highest priority first).
        budget:    Remaining token budget.
        formatter: Callable(item) -> str for token counting.

    Returns:
        (tokens_used, kept_items)
    """
    if budget <= 0:
        return 0, []

    kept: list[Any] = []
    used = 0
    for item in items:
        tokens = count_tokens(formatter(item))
        if used + tokens > budget:
            logger.debug(
                "context_truncation",
                extra={"dropped_item_tokens": tokens, "remaining_budget": budget - used},
            )
            break
        kept.append(item)
        used += tokens
    return used, kept

