"""
LLM Subsystem — Gateway, Providers, and Domain Schemas.

Single entry point for all language model inference across the platform.
"""

from .client import LLMGateway
from .gemini_provider import GeminiProvider
from .groq_provider import GroqProvider
from .provider import LLMProvider
from .schemas import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMValidationError,
    Message,
)

__all__ = [
    "GeminiProvider",
    "GroqProvider",
    "LLMAuthenticationError",
    "LLMError",
    "LLMGateway",
    "LLMProvider",
    "LLMRateLimitError",
    "LLMRequest",
    "LLMResponse",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "LLMValidationError",
    "Message",
]
