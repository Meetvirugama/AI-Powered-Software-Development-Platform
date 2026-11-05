"""LLM error class hierarchy.

Canonical implementation resides in ``ai.llm.schemas``.
This module re-exports all structured error types for backwards compatibility.
"""

from __future__ import annotations

from ai.llm.schemas import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMValidationError,
)

__all__ = [
    "LLMAuthenticationError",
    "LLMError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "LLMValidationError",
]
