"""
Explanation Context Enricher — Week 2 Feature 1 (Code Explanation).
Owner: Meet — W2-11 / Day 2 Context Enrichment

Provides enriched, bounded context for the CodeExplanationService:
- Target function/class snippet preservation
- Relevant imported types and dependencies
- Caller and enclosing symbol resolution
- Repository inventory and conventions
- Explicit missing context representation
- Untrusted delimiter wrapping
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


class ExplanationContextEnricher:
    """Enriches target code snippets with AST symbol relationships, callers, imports, and repository overview."""

    def __init__(self, builder: ContextBuilder | None = None):
        self.builder = builder or ContextBuilder()

    @staticmethod
    def extract_imports(source_code: str, language: str = "python") -> list[str]:
        """
        Extract import statements from file source code.
        Supports Python and TypeScript/JavaScript conventions.
        """
        if not source_code:
            return []

        imports: list[str] = []
        lang = (language or "").lower()

        if lang in ("python", "py"):
            py_pattern = re.compile(r"^(?:from\s+[\w\.]+\s+import\s+[^#\n]+|import\s+[^#\n]+)", re.MULTILINE)
            for match in py_pattern.finditer(source_code):
                stmt = match.group(0).strip()
                if stmt and stmt not in imports:
                    imports.append(stmt)
        elif lang in ("typescript", "javascript", "ts", "tsx", "js", "jsx"):
            js_pattern = re.compile(
                r"^(?:import\s+(?:(?:[\w*\s{},]*)\s+from\s+)?['\"][^'\"]+['\"]|const\s+[\w{}\s,]+\s*=\s*require\([^)]+\));?",
                re.MULTILINE,
            )
            for match in js_pattern.finditer(source_code):
                stmt = match.group(0).strip()
                if stmt and stmt not in imports:
                    imports.append(stmt)

        return imports

    @staticmethod
    def generate_source_references(ctx: IntelligenceContext) -> list[str]:
        """Produce exact, inspectable source reference strings (file:line-line)."""
        refs: list[str] = [f"{ctx.target.file_path}:{ctx.target.start_line}-{ctx.target.end_line}"]
        for sym in ctx.related_symbols:
            refs.append(f"{sym.file_path}:{sym.start_line}-{sym.end_line} ({sym.kind}:{sym.name})")
        return refs

    def enrich_context(
        self,
        target: TargetSnippet,
        source_code: str | None = None,
        callers: Sequence[SymbolContext] | None = None,
        imported_types: Sequence[SymbolContext] | None = None,
        related_symbols: Sequence[SymbolContext] | None = None,
        relevant_chunks: Sequence[Any] | None = None,
        repository_files: Sequence[RepositoryFile] | None = None,
        project_rules: Sequence[str] | None = None,
        token_budget: int = 8000,
        limits: ContextLimits | None = None,
        revision: str | None = None,
    ) -> IntelligenceContext:
        """
        Enrich a target snippet into a comprehensive IntelligenceContext for Code Explanation.
        Prioritizes:
            1. Target snippet code
            2. Callers & enclosing scopes
            3. Imported types & dependencies
            4. Relevant RAG code chunks
            5. Repository file inventory & rules
        """
        active_limits = limits or ContextLimits(max_tokens=token_budget)
        combined_symbols: list[SymbolContext] = []

        # Enclosing / Callers
        if callers:
            for c in callers:
                combined_symbols.append(c)

        # Imported types / symbols
        if imported_types:
            for it in imported_types:
                combined_symbols.append(it)

        # Any additional related symbols
        if related_symbols:
            for s in related_symbols:
                if not any(existing.name == s.name and existing.file_path == s.file_path for existing in combined_symbols):
                    combined_symbols.append(s)

        # Extract textual imports from target file if available
        inferred_rules = list(project_rules or [])
        if source_code:
            imports = self.extract_imports(source_code, target.language)
            if imports:
                imports_summary = "Target File Imports: " + "; ".join(imports[:10])
                if len(imports) > 10:
                    imports_summary += f" (+{len(imports) - 10} more)"
                inferred_rules.append(imports_summary)

        # Build base intelligence context
        ctx = self.builder.build_intelligence_context(
            target=target,
            related_symbols=combined_symbols,
            relevant_chunks=relevant_chunks,
            repository_files=repository_files,
            project_rules=inferred_rules,
            token_budget=active_limits.max_tokens,
            limits=active_limits,
            revision=revision,
        )

        # Handle incomplete caller or type retrieval explicitly
        if not callers and target.symbol_name:
            ctx.missing_context.append(
                MissingContextInfo(
                    file_path=target.file_path,
                    symbol_name=target.symbol_name,
                    reason=f"No callers found in symbol graph for '{target.symbol_name}' (leaf function or unindexed caller sites)",
                    suggested_action="Verify if function is an entry point, API route, or top-level handler",
                )
            )
            if ctx.status == ContextStatus.COMPLETE:
                ctx.status = ContextStatus.PARTIAL

        return ctx


def enrich_explanation_context(
    target: TargetSnippet,
    source_code: str | None = None,
    callers: Sequence[SymbolContext] | None = None,
    imported_types: Sequence[SymbolContext] | None = None,
    related_symbols: Sequence[SymbolContext] | None = None,
    relevant_chunks: Sequence[Any] | None = None,
    repository_files: Sequence[RepositoryFile] | None = None,
    project_rules: Sequence[str] | None = None,
    token_budget: int = 8000,
    limits: ContextLimits | None = None,
    revision: str | None = None,
) -> IntelligenceContext:
    """Convenience functional interface for enriching code explanation context."""
    enricher = ExplanationContextEnricher()
    return enricher.enrich_context(
        target=target,
        source_code=source_code,
        callers=callers,
        imported_types=imported_types,
        related_symbols=related_symbols,
        relevant_chunks=relevant_chunks,
        repository_files=repository_files,
        project_rules=project_rules,
        token_budget=token_budget,
        limits=limits,
        revision=revision,
    )
