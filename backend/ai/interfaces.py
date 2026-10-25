"""Service interfaces and protocols for the Week 2 Developer Intelligence Suite.

Owner: Dev — W2, Day 1 (AI Service Design & Interfaces)

Defines explicit Protocol classes for the four standalone developer intelligence engines:
1. Code Explanation (`CodeExplanationServiceProtocol`)
2. Bug Detection (`BugDetectionServiceProtocol`)
3. Framework-Aware Test Generation (`TestGenerationServiceProtocol`)
4. Standalone AI Code Review (`CodeReviewServiceProtocol`)

Each protocol separates the AI intelligence layer from API routing and persistence,
ensuring modularity, testability, and adherence to Week 2 architecture contracts.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.schemas.analysis import (
    BugDetectionRequest,
    BugDetectionResponse,
    BugFinding,
    CodeExplanation,
    CodeExplanationResponse,
    CodeReviewRequest,
    ExplainCodeRequest,
    ReviewReport,
    ReviewReportResponse,
    TestGenerationRequest,
    TestGenerationResponse,
    TestGenerationResult,
)


@runtime_checkable
class CodeExplanationServiceProtocol(Protocol):
    """Protocol for Dev's CodeExplanationService (Week 2, Day 2).

    Accepts validated repository source target and context, returning a structured
    CodeExplanation detailing purpose, logic flow, key symbols, inputs/outputs,
    dependencies, and assumptions/limitations.
    """

    async def explain(
        self,
        repository_id: UUID,
        payload: ExplainCodeRequest,
        **kwargs: Any,
    ) -> CodeExplanationResponse | CodeExplanation | dict[str, Any]:
        """Explain the specified file, symbol, or line range."""
        ...


@runtime_checkable
class BugDetectionServiceProtocol(Protocol):
    """Protocol for Dev & Devu's BugDetectionEngine (Week 2, Day 3).

    Performs defect analysis across known bug categories (off-by-one, null safety,
    unhandled exceptions, boundary conditions, resource leaks, race conditions, logic errors),
    producing structured findings with concrete evidence and suggested fixes.
    """

    async def detect_bugs(
        self,
        repository_id: UUID,
        payload: BugDetectionRequest,
        **kwargs: Any,
    ) -> BugDetectionResponse | list[BugFinding] | dict[str, Any]:
        """Scan target code for structural and AI-reasoned defects."""
        ...


# Alias for naming consistency with Docs/week2.md §5
BugDetectionEngineProtocol = BugDetectionServiceProtocol


@runtime_checkable
class TestGenerationServiceProtocol(Protocol):
    """Protocol for Dev & Prit's TestGenerationService (Week 2, Day 4).

    Generates framework-aware test suites (pytest, unittest, jest) with positive,
    negative, and boundary edge cases without auto-executing untrusted code.
    """

    async def generate_tests(
        self,
        repository_id: UUID,
        payload: TestGenerationRequest,
        **kwargs: Any,
    ) -> TestGenerationResponse | TestGenerationResult | dict[str, Any]:
        """Generate test code for target file or function matching repository conventions."""
        ...


@runtime_checkable
class CodeReviewServiceProtocol(Protocol):
    """Protocol for Dev's AICodeReviewEngine (Week 2, Day 5).

    Analyzes changed code (file, commit, PR, or diff) across correctness, security,
    performance, reliability, and maintainability, providing actionable findings.
    """

    async def review(
        self,
        repository_id: UUID,
        payload: CodeReviewRequest,
        **kwargs: Any,
    ) -> ReviewReportResponse | ReviewReport | dict[str, Any]:
        """Review code changes and return a structured review report."""
        ...


# Alias for naming consistency with Docs/week2.md §5
AICodeReviewEngineProtocol = CodeReviewServiceProtocol

__all__ = [
    "AICodeReviewEngineProtocol",
    "BugDetectionEngineProtocol",
    "BugDetectionServiceProtocol",
    "CodeExplanationServiceProtocol",
    "CodeReviewServiceProtocol",
    "TestGenerationServiceProtocol",
]
