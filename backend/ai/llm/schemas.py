"""
LLM request/response Pydantic models.
Owner: Meet — W1-12
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Message primitive
# ---------------------------------------------------------------------------

class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class LLMRequest(BaseModel):
    model: str = Field(..., description="Provider model identifier, e.g. 'gpt-4o'")
    messages: list[Message]
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(2048, ge=1)
    response_schema: type[BaseModel] | None = Field(
        default=None,
        description="If provided, the gateway will request JSON-mode output and validate against this schema.",
        exclude=True,  # don't serialise the class itself
    )

    class Config:
        arbitrary_types_allowed = True


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class LLMResponse(BaseModel):
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float

    class Config:
        frozen = True


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Base structured LLM error."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMTimeoutError(LLMError):
    def __init__(self) -> None:
        super().__init__("LLM request timed out.", retryable=True)


class LLMRateLimitError(LLMError):
    def __init__(self) -> None:
        super().__init__("LLM rate limit reached.", retryable=True)


class LLMUnavailableError(LLMError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(f"LLM provider unavailable. {detail}".strip(), retryable=True)


class LLMValidationError(LLMError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(f"LLM response failed schema validation. {detail}".strip(), retryable=False)
