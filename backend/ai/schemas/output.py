"""
AI output contract schemas — Pydantic models for every LLM input/output.
Owner: Dev — W1, Day 1

Every LLM response in the system must conform to one of these schemas.
No free-form strings anywhere in the codebase.

team_rules.md:
    Repository content is always DATA, never SYSTEM instructions.
    These schemas enforce what the LLM is allowed to return.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Source citation — points to a specific file + line range in the repository
# ---------------------------------------------------------------------------

class SourceReference(BaseModel):
    """
    A citation pointing to a specific location in the repository.

    Used inside RepositoryAnswer.sources so the user can trace every
    claim back to the exact file and lines it came from.
    """

    file: str = Field(
        ...,
        description="Repository-relative file path, e.g. 'src/auth/service.ts'",
        examples=["src/auth/service.ts"],
    )
    start_line: int = Field(..., ge=1, description="First line of the cited range (1-indexed).")
    end_line: int = Field(..., ge=1, description="Last line of the cited range (inclusive).")
    symbol: str | None = Field(
        default=None,
        description="Name of the symbol (class/function) at this location, if known.",
        examples=["AuthService", "authenticate"],
    )

    def line_range(self) -> str:
        """Human-readable line range, e.g. '20–48'."""
        return f"{self.start_line}–{self.end_line}"


# ---------------------------------------------------------------------------
# Repository answer — the final structured response for a chat question
# ---------------------------------------------------------------------------

class RepositoryAnswer(BaseModel):
    """
    Structured answer to a repository-scoped question.

    The answer field must reference only information found in the
    provided code context — never hallucinated content.
    Sources must be validated by GroundingValidator before returning to the user.
    """

    answer: str = Field(
        ...,
        description="Natural-language answer referencing only provided repository context.",
    )
    sources: list[SourceReference] = Field(
        default_factory=list,
        description="File + line citations that support the answer. Empty if no sources found.",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ...,
        description=(
            "high   — all sources grounded and answer is specific.\n"
            "medium — some sources grounded or answer is general.\n"
            "low    — no sources grounded or answer is uncertain."
        ),
    )


# ---------------------------------------------------------------------------
# Error response — standard structured error returned to API callers
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """
    Standardised error envelope used by all API endpoints.

    Error codes are constants defined in app/core/errors.py.
    The retryable flag tells the frontend whether to show a retry button.
    """

    code: str = Field(
        ...,
        description="Machine-readable error code, e.g. 'RETRIEVAL_EMPTY', 'LLM_TIMEOUT'.",
        examples=["RETRIEVAL_EMPTY", "LLM_TIMEOUT", "REPOSITORY_NOT_FOUND"],
    )
    message: str = Field(
        ...,
        description="Human-readable description of what went wrong.",
    )
    retryable: bool = Field(
        ...,
        description="True if the caller should retry the request after a short delay.",
    )
