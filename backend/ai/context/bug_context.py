"""
Bug Context Extractor — Week 2 Feature 2 (Dedicated Bug Detection).
Owner: Meet — W2-12 / Day 3 Dependency-Aware Bug Context

Assembles dependency-aware context for the BugDetectionEngine:
- Suspect code snippet isolation
- Enclosing error-handling blocks (try/except, guards, null checks)
- Caller call-sites to verify actual argument assumptions
- Detection and notice of unindexed external library dependencies
- Token-bounded priority fitting and explicit missing-context tracking
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
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


class BugContextExtractor:
    """Extracts dependency-aware bug context including error guards, call sites, and caller constraints."""

    def __init__(self, builder: ContextBuilder | None = None):
        self.builder = builder or ContextBuilder()

    @staticmethod
    def extract_error_handling_blocks(
        source_code: str,
        target_start_line: int,
        target_end_line: int,
        language: str = "python",
    ) -> list[str]:
        """
        Locate enclosing or nearby error handling blocks (try/except, try/catch, guards, None checks).
        Prevents false-positive bug reports by providing defensive code context.
        """
        if not source_code:
            return []

        lines = source_code.splitlines()
        guard_blocks: list[str] = []
        lang = (language or "").lower()

        # Check surrounding window of +/- 30 lines
        window_start = max(0, target_start_line - 30)
        window_end = min(len(lines), target_end_line + 30)
        window_lines = lines[window_start:window_end]
        window_text = "\n".join(window_lines)

        if lang in ("python", "py"):
            patterns = [
                r"(?:try:\s*\n(?:[ ]{4,}.*\n)+[ ]*except[^\n]*:)",
                r"(?:if\s+[\w\.]+\s+is\s+None[^\n]*:)",
                r"(?:if\s+not\s+[\w\.]+[^\n]*:)",
                r"(?:raise\s+[\w\.]+\([^\n]*\))",
            ]
        else:
            patterns = [
                r"(?:try\s*\{[^}]*\}\s*catch[^{]*\{[^}]*\})",
                r"(?:if\s*\(![\w\.]+\)[^\n]*)",
                r"(?:if\s*\([\w\.]+\s*===?\s*(?:null|undefined)\)[^\n]*)",
            ]

        for pat in patterns:
            for match in re.finditer(pat, window_text):
                block = match.group(0).strip()
                if block and block not in guard_blocks:
                    guard_blocks.append(block)

        return guard_blocks

    @staticmethod
    def extract_external_calls(code: str) -> list[str]:
        """Identify external library or unindexed function calls."""
        if not code:
            return []
        call_pattern = re.compile(r"\b([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)\(")
        calls: set[str] = set()
        for match in call_pattern.finditer(code):
            chain = match.group(1)
            parts = chain.split(".")
            if len(parts) > 1:
                calls.add(parts[0])
        # Filter out common standard library / built-in names
        common_builtins = {
            "self",
            "cls",
            "logger",
            "logging",
            "os",
            "sys",
            "re",
            "json",
            "math",
            "str",
            "int",
            "dict",
            "list",
            "set",
        }
        return [c for c in sorted(calls) if c not in common_builtins]

    def extract_context(
        self,
        target: TargetSnippet,
        source_code: str | None = None,
        caller_sites: Sequence[SymbolContext] | None = None,
        related_types: Sequence[SymbolContext] | None = None,
        repository_files: Sequence[RepositoryFile] | None = None,
        project_rules: Sequence[str] | None = None,
        token_budget: int = 8000,
        limits: ContextLimits | None = None,
        revision: str | None = None,
    ) -> IntelligenceContext:
        """
        Assemble bug context prioritizing:
            1. Target suspect code
            2. Enclosing error handling blocks / guards
            3. Caller sites and argument types
            4. Related type definitions
            5. Unverified external dependencies notice
        """
        active_limits = limits or ContextLimits(max_tokens=token_budget)
        combined_symbols: list[SymbolContext] = []

        # 1. Caller sites
        if caller_sites:
            for c in caller_sites:
                combined_symbols.append(c)

        # 2. Related types
        if related_types:
            for t in related_types:
                combined_symbols.append(t)

        # 3. Defensive error handling context
        inferred_rules = list(project_rules or [])
        if source_code:
            guards = self.extract_error_handling_blocks(
                source_code,
                target.start_line,
                target.end_line,
                target.language,
            )
            if guards:
                inferred_rules.append("Defensive Guard Context: " + "; ".join(guards[:3]))

        # 4. External calls notice
        external_modules = self.extract_external_calls(target.content)

        # Build base context
        ctx = self.builder.build_intelligence_context(
            target=target,
            related_symbols=combined_symbols,
            repository_files=repository_files,
            project_rules=inferred_rules,
            token_budget=active_limits.max_tokens,
            limits=active_limits,
            revision=revision,
        )

        # 5. Explicit missing context for unindexed / external dependencies
        if external_modules:
            for mod in external_modules:
                ctx.missing_context.append(
                    MissingContextInfo(
                        file_path=target.file_path,
                        symbol_name=mod,
                        reason=f"External or unindexed dependency '{mod}' referenced; runtime behavior cannot be statically verified",
                        suggested_action="Consult external package specification or supply interface mock",
                    )
                )

        if not caller_sites and target.symbol_name:
            ctx.missing_context.append(
                MissingContextInfo(
                    file_path=target.file_path,
                    symbol_name=target.symbol_name,
                    reason=f"Zero caller sites resolved for '{target.symbol_name}'. Analyze with caution against unverified runtime inputs",
                )
            )

        if ctx.missing_context and ctx.status == ContextStatus.COMPLETE:
            ctx.status = ContextStatus.PARTIAL

        return ctx


def extract_bug_context(
    target: TargetSnippet,
    source_code: str | None = None,
    caller_sites: Sequence[SymbolContext] | None = None,
    related_types: Sequence[SymbolContext] | None = None,
    repository_files: Sequence[RepositoryFile] | None = None,
    project_rules: Sequence[str] | None = None,
    token_budget: int = 8000,
    limits: ContextLimits | None = None,
    revision: str | None = None,
) -> IntelligenceContext:
    """Convenience functional interface for extracting bug detection context."""
    extractor = BugContextExtractor()
    return extractor.extract_context(
        target=target,
        source_code=source_code,
        caller_sites=caller_sites,
        related_types=related_types,
        repository_files=repository_files,
        project_rules=project_rules,
        token_budget=token_budget,
        limits=limits,
        revision=revision,
    )
