"""
Abstract LLM provider interface.
Owner: Meet — W1-12

Every LLM provider (OpenAI, Anthropic, etc.) must implement this interface.
The LLMGateway (client.py) wraps a provider and adds logging, retry, and
structured-output handling on top.

IMPORTANT (team_rules.md):
    The LLM Gateway is the ONLY place in the codebase that calls an LLM API.
    No other module imports the LLM SDK directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .schemas import LLMRequest, LLMResponse


class LLMProvider(ABC):
    """
    Abstract base for an LLM provider.

    Implementations must NOT perform retry or logging — those live in LLMGateway.
    Each implementation wraps exactly one provider SDK.
    """

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Send a chat completion request to the underlying provider.

        Args:
            request: Fully constructed LLMRequest.

        Returns:
            LLMResponse with content, token counts, and latency.

        Raises:
            LLMTimeoutError: Request exceeded the timeout.
            LLMRateLimitError: Provider returned 429.
            LLMUnavailableError: Provider returned 5xx or network failure.
            LLMValidationError: Response failed schema validation.
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name, e.g. 'openai'."""
        ...
