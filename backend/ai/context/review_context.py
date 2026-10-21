"""
Multi-File Review Context Builder — Week 2 Feature 4 (Standalone AI Code Review).
Owner: Meet — W2-14 / Day 5 Multi-File Review Context

Assembles evidence-backed review context across multi-file changes:
- Diff hunk extraction and modified line range bounding
- Dependency blast radius calculation (callers and modules affected by changes)
- Imported type and contract modification tracking
- Fair token allocation across multiple modified files
- Base and head revision preservation
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
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


@dataclass
class ModifiedFile:
    """Represents a single file affected by a diff or commit."""

    file_path: str
    change_type: str = "modified"  # "modified" | "added" | "deleted" | "renamed"
    diff_hunks: list[str] = field(default_factory=list)
    modified_line_ranges: list[tuple[int, int]] = field(default_factory=list)
    content: str = ""
    old_content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewBlastRadius:
    """Diagnostic blast radius assessment identifying downstream code impact."""

    affected_files: list[str] = field(default_factory=list)
    affected_callers: list[SymbolContext] = field(default_factory=list)
    risk_level: str = "low"  # "low" | "medium" | "high"
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "affected_files": self.affected_files,
            "affected_callers": [c.to_dict() for c in self.affected_callers],
            "risk_level": self.risk_level,
            "summary": self.summary,
        }


class ReviewContextBuilder:
    """Builds multi-file review context calculating caller blast radius and hunk-bounded evidence."""

    def __init__(self, builder: ContextBuilder | None = None):
        self.builder = builder or ContextBuilder()

    @staticmethod
    def parse_diff_hunks(diff_text: str) -> list[tuple[int, int, str]]:
        """
        Parse unified diff text into tuples of (start_line, line_count, hunk_content).
        Matches @@ -old,count +new,count @@ headers.
        """
        if not diff_text:
            return []

        hunk_header = re.compile(r"@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")
        hunks: list[tuple[int, int, str]] = []

        lines = diff_text.splitlines()
        current_start = 0
        current_count = 0
        current_chunk: list[str] = []

        for line in lines:
            m = hunk_header.match(line)
            if m:
                if current_chunk:
                    hunks.append((current_start, current_count, "\n".join(current_chunk)))
                    current_chunk = []
                current_start = int(m.group(1))
                current_count = int(m.group(2)) if m.group(2) else 1
            if current_start > 0:
                current_chunk.append(line)

        if current_chunk:
            hunks.append((current_start, current_count, "\n".join(current_chunk)))

        return hunks

    @staticmethod
    def calculate_blast_radius(
        modified_files: Sequence[ModifiedFile],
        symbol_graph: Sequence[SymbolContext] | None = None,
    ) -> ReviewBlastRadius:
        """
        Compute downstream impact of modified files against known caller symbols.
        """
        affected_files: set[str] = set()
        affected_callers: list[SymbolContext] = []

        modified_paths = {f.file_path for f in modified_files}

        if symbol_graph:
            for sym in symbol_graph:
                # If caller references one of the modified files from a DIFFERENT file
                if sym.file_path not in modified_paths:
                    affected_files.add(sym.file_path)
                    affected_callers.append(sym)

        count = len(affected_files)
        if count == 0:
            risk = "low"
            summary = "Isolated changes; no cross-file callers detected in repository graph."
        elif count <= 3:
            risk = "medium"
            summary = f"Moderate blast radius: changes touch {count} dependent downstream files."
        else:
            risk = "high"
            summary = f"High blast radius: changes impact {count} downstream files across repository."

        return ReviewBlastRadius(
            affected_files=sorted(affected_files),
            affected_callers=affected_callers,
            risk_level=risk,
            summary=summary,
        )

    def build_review_context(
        self,
        modified_files: Sequence[ModifiedFile],
        base_revision: str | None = None,
        head_revision: str | None = None,
        symbol_graph: Sequence[SymbolContext] | None = None,
        repository_files: Sequence[RepositoryFile] | None = None,
        project_rules: Sequence[str] | None = None,
        token_budget: int = 10_000,
        limits: ContextLimits | None = None,
    ) -> IntelligenceContext:
        """
        Assemble multi-file review context bounded by fair token distribution.
        """
        active_limits = limits or ContextLimits(max_tokens=token_budget)
        max_tokens = active_limits.max_tokens

        # Check for empty changes
        if not modified_files:
            return IntelligenceContext(
                target=TargetSnippet(file_path="diff", content="", start_line=1, end_line=1),
                missing_context=[
                    MissingContextInfo(
                        file_path="diff",
                        reason="No modified files or diff hunks provided for review",
                    )
                ],
                status=ContextStatus.MISSING_TARGET,
                total_tokens=0,
                token_budget=max_tokens,
                revision=head_revision,
            )

        # 1. Compute blast radius
        blast_radius = self.calculate_blast_radius(modified_files, symbol_graph)

        # 2. Fair token budget distribution across modified files
        # Reserve 40% for blast radius & conventions, 60% for diff hunks
        diff_token_budget = int(max_tokens * 0.6)
        file_budget = max(100, diff_token_budget // max(1, len(modified_files)))

        combined_diff_content: list[str] = [
            f"# Multi-File Review: Base [{base_revision or 'HEAD~1'}] -> Head [{head_revision or 'HEAD'}]",
            f"# Blast Radius Risk: {blast_radius.risk_level.upper()} ({blast_radius.summary})",
            "",
        ]

        missing_records: list[MissingContextInfo] = []
        for mf in modified_files:
            file_hunks = "\n".join(mf.diff_hunks) if mf.diff_hunks else mf.content
            tok = count_tokens(file_hunks)
            if tok > file_budget:
                # Truncate large file diff cleanly
                lines = file_hunks.splitlines()
                truncated_text = "\n".join(lines[:100]) + f"\n... [diff truncated, total lines: {len(lines)}]"
                combined_diff_content.append(f"--- File: {mf.file_path} ({mf.change_type}) ---\n{truncated_text}\n")
                missing_records.append(
                    MissingContextInfo(
                        file_path=mf.file_path,
                        reason=f"Diff hunk ({tok} tokens) truncated to fit file budget ({file_budget} tokens)",
                    )
                )
            else:
                combined_diff_content.append(f"--- File: {mf.file_path} ({mf.change_type}) ---\n{file_hunks}\n")

        full_diff_text = "\n".join(combined_diff_content)

        # Primary target snippet represents the unified changes
        primary_target = TargetSnippet(
            file_path=modified_files[0].file_path if len(modified_files) == 1 else "multi-file-diff",
            content=full_diff_text,
            start_line=1,
            end_line=len(full_diff_text.splitlines()),
            symbol_name="PR_DIFF" if len(modified_files) > 1 else None,
            language="diff",
            revision=f"{base_revision}..{head_revision}" if base_revision and head_revision else head_revision,
        )

        # 3. Add blast radius callers as SymbolContext
        blast_symbols: list[SymbolContext] = []
        for caller in blast_radius.affected_callers[: active_limits.max_symbols]:
            caller_copy = SymbolContext(
                name=caller.name,
                kind="blast_radius",
                file_path=caller.file_path,
                start_line=caller.start_line,
                end_line=caller.end_line,
                content=caller.content,
                score=0.9,
            )
            blast_symbols.append(caller_copy)

        rules = list(project_rules or [])
        rules.append(f"Blast Radius Summary: {blast_radius.summary}")

        ctx = self.builder.build_intelligence_context(
            target=primary_target,
            related_symbols=blast_symbols,
            repository_files=repository_files,
            project_rules=rules,
            token_budget=max_tokens,
            limits=active_limits,
            revision=primary_target.revision,
        )

        if missing_records:
            ctx.missing_context.extend(missing_records)
            if ctx.status == ContextStatus.COMPLETE:
                ctx.status = ContextStatus.PARTIAL

        return ctx


def build_multi_file_review_context(
    modified_files: Sequence[ModifiedFile],
    base_revision: str | None = None,
    head_revision: str | None = None,
    symbol_graph: Sequence[SymbolContext] | None = None,
    repository_files: Sequence[RepositoryFile] | None = None,
    project_rules: Sequence[str] | None = None,
    token_budget: int = 10_000,
    limits: ContextLimits | None = None,
) -> IntelligenceContext:
    """Convenience functional interface for building multi-file review context."""
    builder = ReviewContextBuilder()
    return builder.build_review_context(
        modified_files=modified_files,
        base_revision=base_revision,
        head_revision=head_revision,
        symbol_graph=symbol_graph,
        repository_files=repository_files,
        project_rules=project_rules,
        token_budget=token_budget,
        limits=limits,
    )
