"""Intelligence context assembly for Explain, Bug Detection, Test Generation, and Review.
Owner: Meet — W1-12 / W2 Intelligence Suite
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from .models import (
    ContextLimits,
    ContextStatus,
    IntelligenceContext,
    MissingContextInfo,
    RepositoryFile,
    SymbolContext,
    TargetSnippet,
)
from .token_budget import count_tokens

logger = logging.getLogger(__name__)


def build_intelligence_context(
    target: TargetSnippet,
    related_symbols: Sequence[SymbolContext] | None = None,
    relevant_chunks: Sequence[Any] | None = None,
    repository_files: Sequence[RepositoryFile] | None = None,
    project_rules: Sequence[str] | None = None,
    token_budget: int = 10_000,
    limits: ContextLimits | None = None,
    revision: str | None = None,
) -> IntelligenceContext:
    """
    Build an enriched, token-bounded context for developer intelligence features:
    Code Explanation, Bug Detection, Test Generation, and Code Review.

    Prioritizes:
        1. Target code snippet (exact lines & content)
        2. Callers & enclosing symbols
        3. Retrieved RAG chunks & types
        4. Repository inventory & conventions
    """
    active_limits = limits or ContextLimits(max_tokens=token_budget)
    max_tokens = active_limits.max_tokens

    # Check for missing or empty target
    if not target or not getattr(target, "content", "").strip():
        target_path = getattr(target, "file_path", "unknown") if target else "unknown"
        return IntelligenceContext(
            target=target or TargetSnippet(file_path=target_path, content="", start_line=1, end_line=1),
            related_symbols=[],
            relevant_chunks=[],
            repository_files=[],
            project_rules=[],
            missing_context=[
                MissingContextInfo(
                    file_path=target_path,
                    reason="Target code snippet is missing or empty",
                    suggested_action="Provide a valid target file path and line range",
                )
            ],
            status=ContextStatus.MISSING_TARGET,
            total_tokens=0,
            token_budget=max_tokens,
            revision=revision,
        )

    missing_records: list[MissingContextInfo] = []
    status = ContextStatus.COMPLETE

    safe_symbols = list(related_symbols or [])[: active_limits.max_symbols]
    if related_symbols and len(related_symbols) > active_limits.max_symbols:
        dropped_cnt = len(related_symbols) - active_limits.max_symbols
        missing_records.append(
            MissingContextInfo(
                file_path=target.file_path,
                reason=f"{dropped_cnt} related symbols truncated due to symbol count ceiling ({active_limits.max_symbols})",
            )
        )

    safe_chunks = list(relevant_chunks or [])[: active_limits.max_chunks]
    if relevant_chunks and len(relevant_chunks) > active_limits.max_chunks:
        dropped_cnt = len(relevant_chunks) - active_limits.max_chunks
        missing_records.append(
            MissingContextInfo(
                file_path=target.file_path,
                reason=f"{dropped_cnt} code chunks truncated due to chunk count ceiling ({active_limits.max_chunks})",
            )
        )

    safe_files = list(repository_files or [])[: active_limits.max_files]
    safe_rules = list(project_rules or [])[: active_limits.max_rules]

    # Step 1: Measure target code tokens
    target_tokens = count_tokens(target.content)
    if target_tokens > max_tokens:
        status = ContextStatus.OVERSIZED
        missing_records.append(
            MissingContextInfo(
                file_path=target.file_path,
                symbol_name=target.symbol_name,
                reason=f"Target snippet ({target_tokens} tokens) exceeds context budget ({max_tokens} tokens)",
                suggested_action="Narrow the selected line range or symbol scope",
            )
        )
        return IntelligenceContext(
            target=target,
            related_symbols=[],
            relevant_chunks=[],
            repository_files=safe_files,
            project_rules=safe_rules,
            missing_context=missing_records,
            status=status,
            total_tokens=target_tokens,
            token_budget=max_tokens,
            revision=revision,
        )

    remaining = max_tokens - target_tokens

    # Step 2: Fit related symbols & callers within remaining budget
    fitted_symbols: list[SymbolContext] = []
    for sym in safe_symbols:
        tok = count_tokens(sym.content or sym.name)
        if tok <= remaining:
            fitted_symbols.append(sym)
            remaining -= tok
        else:
            missing_records.append(
                MissingContextInfo(
                    file_path=sym.file_path,
                    symbol_name=sym.name,
                    reason=f"Related symbol {sym.kind} '{sym.name}' omitted due to token budget constraint",
                )
            )

    # Step 3: Fit relevant chunks
    fitted_chunks: list[Any] = []
    for chk in safe_chunks:
        tok = count_tokens(getattr(chk, "content", ""))
        if tok <= remaining:
            fitted_chunks.append(chk)
            remaining -= tok
        else:
            missing_records.append(
                MissingContextInfo(
                    file_path=getattr(chk, "file_path", target.file_path),
                    reason="Code chunk omitted due to token budget constraint",
                )
            )

    if missing_records and status == ContextStatus.COMPLETE:
        status = ContextStatus.PARTIAL

    total = max_tokens - remaining
    return IntelligenceContext(
        target=target,
        related_symbols=fitted_symbols,
        relevant_chunks=fitted_chunks,
        repository_files=safe_files,
        project_rules=safe_rules,
        missing_context=missing_records,
        status=status,
        total_tokens=total,
        token_budget=max_tokens,
        revision=revision,
    )

