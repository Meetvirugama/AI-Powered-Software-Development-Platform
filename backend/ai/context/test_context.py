"""
Test Context Builder — Week 2 Feature 3 (Framework-Aware Test Generation).
Owner: Meet — W2-13 / Day 4 Test Context Builder

Assembles repository-aware test generation context:
- Target function/class signatures and complete implementation
- Identification of mockable external services and database calls
- Existing test patterns and fixture conventions in the repository
- Framework-specific conventions (pytest, unittest, jest)
- Preservation of original source revision and token bounding
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ai.context.builder import (
    ContextBuilder,
    ContextLimits,
    ContextStatus,
    IntelligenceContext,
    MissingContextInfo,
    RepositoryFile,
    SymbolContext,
    TargetSnippet,
    count_tokens,
)

logger = logging.getLogger(__name__)


class TestContextBuilder:
    """Builds framework-aware context for generating comprehensive unit and integration tests."""

    __test__ = False

    def __init__(self, builder: ContextBuilder | None = None):
        self.builder = builder or ContextBuilder()

    @staticmethod
    def infer_candidate_test_paths(source_file_path: str, framework: str = "pytest") -> list[str]:
        """
        Compute conventional test file paths corresponding to a source file.
        e.g., 'backend/app/services/auth.py' ->
              ['backend/tests/test_auth.py', 'backend/tests/services/test_auth.py', 'tests/test_auth.py']
        """
        p = Path(source_file_path)
        stem = p.stem
        candidates: list[str] = []

        if framework in ("pytest", "unittest"):
            test_filename = f"test_{stem}.py"
            candidates.append(str(p.parent / test_filename))
            candidates.append(f"tests/{test_filename}")
            candidates.append(f"backend/tests/{test_filename}")
            if len(p.parts) > 1:
                subpath = "/".join(p.parts[1:-1])
                if subpath:
                    candidates.append(f"backend/tests/{subpath}/{test_filename}")
                    candidates.append(f"tests/{subpath}/{test_filename}")
        elif framework in ("jest", "vitest"):
            candidates.append(str(p.parent / f"{stem}.test.ts"))
            candidates.append(str(p.parent / f"{stem}.test.tsx"))
            candidates.append(str(p.parent / f"{stem}.spec.ts"))
            candidates.append(f"src/__tests__/{stem}.test.ts")

        # De-duplicate preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                deduped.append(c)
        return deduped

    @staticmethod
    def detect_mockable_calls(code: str) -> list[str]:
        """
        Detect external calls, HTTP requests, or database sessions that typically require mocking.
        """
        if not code:
            return []

        mockable_patterns = [
            r"\b(db\.(?:query|execute|commit|rollback|add|delete))\b",
            r"\b(session\.(?:query|execute|commit|rollback|add|delete))\b",
            r"\b(httpx\.(?:get|post|put|delete|patch|request))\b",
            r"\b(requests\.(?:get|post|put|delete|patch))\b",
            r"\b(boto3\.(?:client|resource))\b",
            r"\b(redis\.(?:get|set|delete|hget))\b",
            r"\b(stripe\.[a-zA-Z_]+\.[a-zA-Z_]+)\b",
            r"\b(fetch\([^)]+\))\b",
            r"\b(axios\.(?:get|post|put|delete))\b",
        ]
        found: set[str] = set()
        for pat in mockable_patterns:
            for match in re.finditer(pat, code):
                found.add(match.group(1))

        return sorted(found)

    def build_context(
        self,
        target: TargetSnippet,
        framework: str = "pytest",
        existing_test_files: Sequence[RepositoryFile] | None = None,
        sample_test_code: str | None = None,
        mockable_dependencies: Sequence[SymbolContext] | None = None,
        fixture_definitions: Sequence[str] | None = None,
        repository_files: Sequence[RepositoryFile] | None = None,
        project_rules: Sequence[str] | None = None,
        token_budget: int = 8000,
        limits: ContextLimits | None = None,
        revision: str | None = None,
    ) -> IntelligenceContext:
        """
        Assemble comprehensive test generation context.
        Prioritizes:
            1. Target code snippet (exact signature & implementation)
            2. Mockable dependencies & interfaces
            3. Project test framework conventions & fixtures
            4. Sample existing test code (conventions & assertions)
            5. Repository file inventory
        """
        active_limits = limits or ContextLimits(max_tokens=token_budget)
        combined_symbols: list[SymbolContext] = []

        # 1. Mockable dependencies
        if mockable_dependencies:
            for m in mockable_dependencies:
                combined_symbols.append(m)

        # 2. Automatically detected mockable calls in target
        detected_mocks = self.detect_mockable_calls(target.content)

        # 3. Rules & conventions
        rules = list(project_rules or [])
        rules.append(f"Configured Test Framework: {framework}")

        if detected_mocks:
            rules.append("Detected Services Requiring Mocking: " + ", ".join(detected_mocks[:8]))

        if fixture_definitions:
            for f in fixture_definitions[:5]:
                rules.append(f"Available Fixture: {f}")

        # 4. Check for existing test files
        missing_records: list[MissingContextInfo] = []
        candidate_paths = self.infer_candidate_test_paths(target.file_path, framework)
        matched_test = None
        if existing_test_files:
            target_stem = Path(target.file_path).stem.lower()
            for tf in existing_test_files:
                if target_stem in tf.path.lower():
                    matched_test = tf
                    break

        if not matched_test and not sample_test_code:
            missing_records.append(
                MissingContextInfo(
                    file_path=target.file_path,
                    symbol_name=target.symbol_name,
                    reason=f"No pre-existing test file found for '{target.file_path}'. Candidate paths evaluated: {', '.join(candidate_paths[:2])}",
                    suggested_action=f"Create new test file at '{candidate_paths[0]}'",
                )
            )

        # If sample test code was provided, include as a convention symbol
        if sample_test_code:
            combined_symbols.append(
                SymbolContext(
                    name="existing_test_pattern",
                    kind="test_pattern",
                    file_path=matched_test.path if matched_test else candidate_paths[0],
                    start_line=1,
                    end_line=len(sample_test_code.splitlines()),
                    content=sample_test_code[:1000],
                )
            )

        # Build base context
        ctx = self.builder.build_intelligence_context(
            target=target,
            related_symbols=combined_symbols,
            repository_files=repository_files,
            project_rules=rules,
            token_budget=active_limits.max_tokens,
            limits=active_limits,
            revision=revision or target.revision,
        )

        # Attach any missing context records
        if missing_records:
            ctx.missing_context.extend(missing_records)
            if ctx.status == ContextStatus.COMPLETE:
                ctx.status = ContextStatus.PARTIAL

        return ctx


def build_test_generation_context(
    target: TargetSnippet,
    framework: str = "pytest",
    existing_test_files: Sequence[RepositoryFile] | None = None,
    sample_test_code: str | None = None,
    mockable_dependencies: Sequence[SymbolContext] | None = None,
    fixture_definitions: Sequence[str] | None = None,
    repository_files: Sequence[RepositoryFile] | None = None,
    project_rules: Sequence[str] | None = None,
    token_budget: int = 8000,
    limits: ContextLimits | None = None,
    revision: str | None = None,
) -> IntelligenceContext:
    """Convenience functional interface for building test generation context."""
    builder = TestContextBuilder()
    return builder.build_context(
        target=target,
        framework=framework,
        existing_test_files=existing_test_files,
        sample_test_code=sample_test_code,
        mockable_dependencies=mockable_dependencies,
        fixture_definitions=fixture_definitions,
        repository_files=repository_files,
        project_rules=project_rules,
        token_budget=token_budget,
        limits=limits,
        revision=revision,
    )
