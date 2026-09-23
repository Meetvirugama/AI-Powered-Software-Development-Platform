"""
LLM error class hierarchy.
Owner: Dev — W1, Day 1

These are the ONLY exception types that should escape the LLM Gateway.
All callers catch these specific types — never bare exceptions.

team_rules.md:
    The LLM Gateway is the ONLY place in the codebase that calls an LLM API.
    It raises only these structured error types.
"""

from __future__ import annotations


class LLMError(Exception):
    """
    Base class for all structured LLM errors.

    Attributes:
        retryable: True if the operation can be retried automatically.
                   The frontend uses this to decide whether to show a retry button.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMTimeoutError(LLMError):
    """
    Raised when the LLM provider does not respond within the configured timeout.

    Retryable: yes — transient network condition.
    """

    def __init__(self) -> None:
        super().__init__(
            "LLM request timed out. The provider did not respond within the timeout window.",
            retryable=True,
        )


class LLMValidationError(LLMError):
    """
    Raised when the LLM response fails structured-output schema validation.

    Retryable: no — the model returned a different shape; retrying is unlikely to help
    without prompt changes. The OutputValidator repair loop handles retries internally.

    Args:
        detail: Short description of what part of the schema failed.
    """

    def __init__(self, detail: str = "") -> None:
        msg = "LLM response failed schema validation."
        if detail:
            msg += f" {detail}"
        super().__init__(msg, retryable=False)


class LLMUnavailableError(LLMError):
    """
    Raised when the LLM provider is unreachable (5xx errors, network failure, etc.)
    after all retry attempts are exhausted.

    Retryable: yes — service may recover after a delay.

    Args:
        detail: HTTP status or error description for debugging.
    """

    def __init__(self, detail: str = "") -> None:
        msg = "LLM provider is currently unavailable."
        if detail:
            msg += f" Detail: {detail}"
        super().__init__(msg, retryable=True)


class LLMRateLimitError(LLMError):
    """
    Raised when the LLM provider rate-limits the request (HTTP 429)
    after all retry attempts are exhausted.

    Retryable: yes — after a cooling-off period.
    """

    def __init__(self) -> None:
        super().__init__(
            "LLM rate limit exceeded. All retry attempts exhausted.",
            retryable=True,
        )
