"""
Abstract LLM Provider Interface.

Defines the contract for all underlying LLM provider SDK adapters (Gemini, Groq,
etc.). Concrete providers encapsulate network transport, provider-specific
parameter mapping, and transient retries. High-level routing, telemetry, and structured
output validation are governed by LLMGateway.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Self

from .schemas import LLMRequest, LLMResponse, LLMToolRequest, LLMToolResponse

if TYPE_CHECKING:
    from pydantic import BaseModel


class LLMProvider(ABC):
    """
    Abstract base class for all LLM inference adapters.

    Guarantees:
    - Encapsulates exact provider SDK or HTTP wire protocol.
    - Emits strongly-typed ``LLMResponse`` instances.
    - Translates vendor-specific errors into standardized ``LLMError`` subclasses.
    """

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Execute chat completion for the given structured request.

        Args:
            request: Fully constructed and validated LLMRequest.

        Returns:
            LLMResponse containing generated text, model metadata, and usage tokens.

        Raises:
            LLMTimeoutError: If the provider call exceeds the configured deadline.
            LLMRateLimitError: If provider rate limits are exhausted.
            LLMUnavailableError: If provider returns 5xx errors or connection drops.
            LLMAuthenticationError: If API credentials are rejected.
            LLMValidationError: If structured schema output fails validation.
        """
        ...

    async def generate_with_tools(self, request: LLMToolRequest) -> LLMToolResponse:
        """
        Execute chat completion with tool calling support.

        Args:
            request: Fully constructed LLMToolRequest containing tool definitions and conversation turns.

        Returns:
            LLMToolResponse containing generated content or tool calls with usage metadata.

        Raises:
            LLMTimeoutError: If the provider call exceeds the configured deadline.
            LLMRateLimitError: If provider rate limits are exhausted.
            LLMUnavailableError: If provider returns 5xx errors or connection drops.
            LLMAuthenticationError: If API credentials are rejected.
            LLMValidationError: If the model returns malformed tool arguments or structure.
            NotImplementedError: If the provider does not support function/tool calling.
        """
        raise NotImplementedError(f"Provider {self.provider_name} does not implement generate_with_tools.")

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Canonical identifier for the provider (e.g. 'gemini', 'groq')."""
        ...

    @property
    def default_model(self) -> str:
        """Recommended or default model name for this provider."""
        return "default"

    def _validate_structured_output(self, content: str, schema: type[BaseModel]) -> None:
        """Validate response JSON content against expected schema."""
        from .schemas import validate_structured_payload

        validate_structured_payload(content, schema, provider=self.provider_name)

    async def aclose(self) -> None:
        """Release underlying HTTP client sessions and connection pools."""

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()


__all__ = ["LLMProvider"]
