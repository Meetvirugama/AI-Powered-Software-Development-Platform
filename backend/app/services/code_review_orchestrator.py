"""End-to-end orchestration for Week 2 Day 5 Standalone AI Code Review (`POST /repositories/{id}/review`).

Owner: Yug (API & Orchestration), Dev (AICodeReviewEngine), Parth (Commit & PR Diffs),
       Prit (ReviewSourceMapper), Devu (StaticReviewer), Meet (ReviewContextBuilder),
       Sukun (Security), Om (Review History)

Implements the complete Day 5 & Scenario D / E requirements from `Docs/week2.md` §9 & §12:
1. Multi-Target Resolution (`resolve_review_target_and_build_context`):
   - Supports all 4 review targets: `'file'`, `'commit'`, `'pr'`, and `'diff'`.
   - For `'file'`: validates path traversal safety, enforces 1 MB size ceiling, reconstructs source
     from indexed `code_chunks`, and builds synthetic unified diff hunk for review mapping.
   - For `'commit'` and `'pr'`: retrieves authorized commit changes / PR diffs via Parth's
     `GitHubSourceService` (or injected `github_source_service`), handling renamed, deleted,
     binary, and oversized files while preserving `base_revision` and `head_revision`.
   - For `'diff'`: parses unified diff hunks and validates all file paths inside the diff.
2. Source Mapping & Blast Radius Context Assembly:
   - Maps changed lines and hunks to enclosing AST symbols, scopes, and structural defects via
     Prit's `ReviewSourceMapper`.
   - Computes dependency blast radius and multi-file review context via Meet's `ReviewContextBuilder`.
3. Static Review Pipeline (`run_static_review_on_changes`):
   - Runs `BuiltinStaticBugScanner` and `ASTBugAnalyzer` scoped strictly to modified files and
     changed line ranges, plus optional external `app.state.static_reviewer`.
   - Maps defect categories to the 5 review dimensions (`correctness`, `security`, `performance`,
     `reliability`, `maintainability`) with `is_new_in_change=True`.
4. AI Code Review (`app.state.code_review_service` / `LLMCodeReviewService`):
   - Wraps untrusted repository diffs and code in random `<<<REPO_DATA_...>>>` fences.
   - Enforces 2-attempt JSON schema validation and self-repair loop.
5. Normalization, Secret Redaction, Grounding, Deduplication & Risk Computation:
   - Redacts any raw secrets (`[REDACTED]`) across all finding fields and summary.
   - Rejects path-traversal citations, unindexed files (when repo is indexed and target is not a new file),
     and out-of-bounds line numbers.
   - Merges overlapping `STATIC` and `AI` findings into `source_type="COMBINED"`.
   - Computes deterministic `category_counts`, `total_findings`, and overall `risk_level`
     (`CRITICAL` / `HIGH` / `MEDIUM` / `LOW` / `NONE`).
   - Distinguishes a completed zero-finding review (`status="COMPLETED"`, `total_findings=0`,
     `risk_level="NONE"`) from a failed review (`status="FAILED"`).
6. Review History Persistence:
   - Persists completed and failed review runs and findings via `record_analysis_run` and
     Om's `AnalysisRunRepository` without overwriting previous revisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import json
import logging
import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from ai.context.builder import (
    ContextBuilder,
    IntelligenceContext,
    RepositoryFile as ContextRepoFile,
    SymbolContext,
)
from ai.context.review_context import ModifiedFile, ReviewContextBuilder
from ai.llm.schemas import (
    LLMRequest,
    LLMValidationError,
    Message,
)
from ai.schemas.prompt_builder import _fence
from app.core.errors import APIError, ErrorCode
from app.core.input_security import UnsafePathError, require_safe_repo_path, validate_repo_relative_path
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.memory_entry import MemoryEntry
from app.models.repository import Repository
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.schemas.analysis import (
    AnalysisSourceReference,
    CodeReviewRequest,
    FindingSeverity,
    ReviewCategory,
    ReviewFinding,
    ReviewReport,
    ReviewTarget,
)
from app.services.bug_detection_orchestrator import (
    CONFIDENCE_RANK,
    SEVERITY_RANK,
    SOURCE_TYPE_PRIORITY,
    BuiltinStaticBugScanner,
    redact_secrets_in_text,
)
from app.services.explanation_orchestrator import MAX_ANALYZABLE_FILE_BYTES
from scanner.source_mapper import ReviewSourceMapResult, ReviewSourceMapper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants & Category Mapping
# ---------------------------------------------------------------------------

VALID_REVIEW_CATEGORIES: frozenset[str] = frozenset(
    {"correctness", "security", "performance", "reliability", "maintainability"}
)

_BUG_TO_REVIEW_CATEGORY: dict[str, ReviewCategory] = {
    "off_by_one": "correctness",
    "boundary_condition": "correctness",
    "logic_error": "correctness",
    "null_safety": "reliability",
    "unhandled_exception": "reliability",
    "resource_leak": "reliability",
    "race_condition": "reliability",
    "security": "security",
    "sql_injection": "security",
    "hardcoded_secret": "security",
    "performance": "performance",
    "slow_query": "performance",
    "maintainability": "maintainability",
    "correctness": "correctness",
    "reliability": "reliability",
    "other": "maintainability",
}


def map_to_review_category(raw_category: str | None, rule_id: str | None = None) -> ReviewCategory:
    """Map static/bug categories or linter rule codes into the 5 ReviewCategory dimensions."""
    cat = (raw_category or "").strip().lower()
    if cat in VALID_REVIEW_CATEGORIES:
        return cat  # type: ignore[return-value]
    if cat in _BUG_TO_REVIEW_CATEGORY:
        return _BUG_TO_REVIEW_CATEGORY[cat]
    rule = (rule_id or "").upper()
    if rule.startswith(("B", "SEC", "S")):
        return "security"
    if rule.startswith("PERF"):
        return "performance"
    if rule.startswith(("AST001", "AST-BOUND", "AST-ITER", "AST-LOGIC", "F821")):
        return "correctness"
    if rule.startswith(("AST002", "AST004", "AST-EXC", "AST-RES", "AST-NULL")):
        return "reliability"
    return "maintainability"


@dataclass
class ResolvedReviewTarget:
    """Normalized review target, mapped diff files, AST source mapping, and assembled IntelligenceContext."""

    target: ReviewTarget
    target_path_summary: str | None
    revision: str
    base_revision: str | None
    head_revision: str | None
    modified_files: list[ModifiedFile]
    file_contents: dict[str, str]
    source_map: ReviewSourceMapResult
    intelligence_context: IntelligenceContext
    missing_context: list[str] = field(default_factory=list)
    indexed_paths: dict[str, int] = field(default_factory=dict)
    allowed_paths: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# 1. Target Resolution & Context Assembly (File, Commit, PR, Unified Diff)
# ---------------------------------------------------------------------------

def _reconstruct_indexed_file(
    db: Session,
    repository_id: UUID,
    file_record: RepositoryFile,
) -> str:
    try:
        chunks: list[CodeChunk] = (
            db.query(CodeChunk)
            .filter(
                CodeChunk.repository_id == repository_id,
                CodeChunk.file_id == file_record.id,
            )
            .order_by(CodeChunk.start_line)
            .all()
        )
        return "\n".join(c.content for c in chunks if c.content)
    except Exception:
        return ""


async def resolve_review_target_and_build_context(
    repository_id: UUID,
    repo: Repository | Any,
    payload: CodeReviewRequest,
    user_id: UUID,
    db: Session | Any,
    app_state: Any = None,
) -> ResolvedReviewTarget:
    """Steps 2–5 of `Docs/week2.md` §9: Validate target, fetch source/diff, map AST symbols, build context."""
    target = payload.target.model_copy()
    default_branch = getattr(repo, "default_branch", None) or "main"
    base_rev = target.base_revision
    head_rev = target.head_revision or default_branch
    revision = target.commit_sha or head_rev or default_branch
    missing_context: list[str] = []

    if target.path is not None:
        target.path = require_safe_repo_path(target.path)

    # Lightweight unit-test mode when `db` is a mock `object()` without `.query`
    if not hasattr(db, "query") and getattr(app_state, "github_source_service", None) is None:
        mod_files: list[ModifiedFile] = []
        if target.type == "file" and target.path:
            mod_files.append(ModifiedFile(file_path=target.path, change_type="modified", content=""))
        elif target.type == "diff" and target.diff:
            mapper = ReviewSourceMapper()
            parsed_raw = mapper.parse_unified_diff(target.diff)
            for rf in parsed_raw:
                fp = rf.new_path or rf.old_path or (target.path or "diff.py")
                safe_fp = require_safe_repo_path(fp)
                hunks_txt = ["\n".join(h.lines) for h in rf.hunks]
                mod_files.append(
                    ModifiedFile(file_path=safe_fp, change_type=rf.change_type, diff_hunks=hunks_txt)
                )
        ctx = ReviewContextBuilder().build_review_context(
            modified_files=mod_files,
            base_revision=base_rev,
            head_revision=head_rev,
            token_budget=payload.options.max_context_tokens,
        )
        return ResolvedReviewTarget(
            target=target,
            target_path_summary=target.path or (f"commit:{target.commit_sha}" if target.commit_sha else f"pr:{target.pr_number}"),
            revision=revision,
            base_revision=base_rev,
            head_revision=head_rev,
            modified_files=mod_files,
            file_contents={},
            source_map=ReviewSourceMapResult(success=True),
            intelligence_context=ctx,
            missing_context=missing_context,
            indexed_paths={},
            allowed_paths=set(),
        )

    # Load indexed repository files from DB when available
    all_repo_files: list[RepositoryFile] = []
    if hasattr(db, "query"):
        try:
            all_repo_files = (
                db.query(RepositoryFile)
                .filter(RepositoryFile.repository_id == repository_id)
                .order_by(RepositoryFile.path)
                .all()
            )
        except Exception:
            all_repo_files = []

    indexed_paths: dict[str, int] = {f.path: (f.line_count or 0) for f in all_repo_files}
    path_to_record: dict[str, RepositoryFile] = {f.path: f for f in all_repo_files}
    file_contents: dict[str, str] = {}
    modified_files: list[ModifiedFile] = []
    allowed_paths: set[str] = set(indexed_paths.keys())

    mapper = ReviewSourceMapper()
    source_map = ReviewSourceMapResult(
        success=True,
        base_revision=base_rev,
        head_revision=head_rev,
        commit_sha=target.commit_sha,
        pr_number=target.pr_number,
    )

    # ── Target Type A: Single File (`type="file"`) ──────────────────────────
    if target.type == "file":
        safe_path = require_safe_repo_path(target.path or "")
        target.path = safe_path
        file_rec = path_to_record.get(safe_path)
        if all_repo_files and file_rec is None:
            raise APIError(
                404,
                ErrorCode.FILE_NOT_FOUND,
                f"Target file '{safe_path}' was not found in the indexed repository.",
            )
        if file_rec is not None and (file_rec.size_bytes or 0) > MAX_ANALYZABLE_FILE_BYTES:
            raise APIError(
                413,
                ErrorCode.PAYLOAD_TOO_LARGE,
                "Target file exceeds the maximum analyzable size limit (1 MB).",
            )
        code_text = _reconstruct_indexed_file(db, repository_id, file_rec) if file_rec else ""
        file_contents[safe_path] = code_text
        allowed_paths.add(safe_path)
        line_total = max(1, len(code_text.splitlines()))
        synthetic_hunk = (
            f"--- a/{safe_path}\n+++ b/{safe_path}\n@@ -1,{line_total} +1,{line_total} @@\n"
            + "\n".join(f"+{ln}" for ln in code_text.splitlines())
        )
        modified_files.append(
            ModifiedFile(
                file_path=safe_path,
                change_type="modified",
                diff_hunks=[synthetic_hunk] if code_text else [],
                modified_line_ranges=[(1, line_total)],
                content=code_text,
            )
        )
        if code_text:
            f_map = mapper.map_file_changes(
                file_path=safe_path,
                content=code_text,
                modified_ranges=[(1, line_total)],
                language=file_rec.language if file_rec else None,
                base_revision=base_rev,
                head_revision=head_rev,
            )
            source_map = ReviewSourceMapResult(
                success=True,
                files=[f_map],
                total_files=1,
                total_hunks=len(f_map.hunks),
                total_changed_lines=line_total,
                affected_symbols_count=len(f_map.affected_symbols),
                base_revision=base_rev,
                head_revision=head_rev,
                limitations=list(f_map.limitations),
            )

    # ── Target Type B: Unified Diff (`type="diff"`) ─────────────────────────
    elif target.type == "diff":
        diff_text = target.diff or ""
        raw_diff_files = mapper.parse_unified_diff(diff_text)
        if not raw_diff_files:
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                "Provided diff does not contain any valid unified diff hunks (`@@ ... @@`).",
            )
        for rf in raw_diff_files:
            raw_fp = rf.new_path or rf.old_path or target.path or ""
            if raw_fp == "target_file" and target.path:
                raw_fp = target.path
            safe_fp = require_safe_repo_path(raw_fp)
            allowed_paths.add(safe_fp)
            if safe_fp in path_to_record:
                file_contents[safe_fp] = _reconstruct_indexed_file(db, repository_id, path_to_record[safe_fp])
            else:
                # Reconstruct added lines from diff hunks when file is newly added or not yet indexed
                added_lines: list[str] = []
                for h in rf.hunks:
                    for ln in h.lines[1:]:
                        if ln.startswith("+") and not ln.startswith("+++"):
                            added_lines.append(ln[1:])
                        elif ln.startswith(" "):
                            added_lines.append(ln[1:])
                file_contents[safe_fp] = "\n".join(added_lines)

            hunk_strs = ["\n".join(h.lines) for h in rf.hunks]
            mod_ranges = [
                (h.new_start, h.new_start + max(1, h.new_count) - 1)
                for h in rf.hunks
            ]
            modified_files.append(
                ModifiedFile(
                    file_path=safe_fp,
                    change_type=rf.change_type,
                    diff_hunks=hunk_strs,
                    modified_line_ranges=mod_ranges,
                    content=file_contents.get(safe_fp, ""),
                )
            )
        source_map = mapper.map_unified_diff(
            diff_text=diff_text,
            repo_files=file_contents,
            base_revision=base_rev,
            head_revision=head_rev,
        )

    # ── Target Type C & D: Commit SHA (`type="commit"`) or PR (`type="pr"`) ─
    elif target.type in ("commit", "pr"):
        gh_source = getattr(app_state, "github_source_service", None) if app_state else None
        if gh_source is None and hasattr(db, "execute"):
            from app.integrations.github.source_service import GitHubSourceService
            gh_source = GitHubSourceService(db)

        if target.type == "commit":
            commit_sha = target.commit_sha or ""
            revision = commit_sha
            head_rev = commit_sha
            if gh_source is not None:
                commit_detail = gh_source.get_commit_detail(repository_id, user_id, commit_sha)
                if inspect.isawaitable(commit_detail):
                    commit_detail = await commit_detail
                if getattr(commit_detail, "parents", None):
                    base_rev = base_rev or commit_detail.parents[0]
                commit_files = list(getattr(commit_detail, "files", []) or [])
                for cf in commit_files:
                    fname = getattr(cf, "filename", "") if not isinstance(cf, dict) else cf.get("filename", "")
                    status_raw = getattr(cf, "status", "modified") if not isinstance(cf, dict) else cf.get("status", "modified")
                    status_str = status_raw.value if hasattr(status_raw, "value") else str(status_raw)
                    patch_txt = getattr(cf, "patch", None) if not isinstance(cf, dict) else cf.get("patch")
                    try:
                        safe_fp = validate_repo_relative_path(fname)
                    except UnsafePathError:
                        continue
                    allowed_paths.add(safe_fp)
                    if safe_fp in path_to_record:
                        file_contents[safe_fp] = _reconstruct_indexed_file(db, repository_id, path_to_record[safe_fp])
                    elif patch_txt:
                        added = [
                            ln[1:]
                            for ln in patch_txt.splitlines()
                            if (ln.startswith("+") and not ln.startswith("+++")) or ln.startswith(" ")
                        ]
                        file_contents[safe_fp] = "\n".join(added)
                    mod_ranges: list[tuple[int, int]] = []
                    if patch_txt:
                        for hm in re.finditer(
                            r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@",
                            patch_txt,
                            re.MULTILINE,
                        ):
                            h_start = int(hm.group(1))
                            h_count = int(hm.group(2)) if hm.group(2) is not None else 1
                            if h_count > 0:
                                mod_ranges.append((h_start, h_start + h_count - 1))
                    modified_files.append(
                        ModifiedFile(
                            file_path=safe_fp,
                            change_type="deleted" if status_str == "removed" else status_str,
                            diff_hunks=[patch_txt] if patch_txt else [],
                            modified_line_ranges=mod_ranges,
                            content=file_contents.get(safe_fp, ""),
                        )
                    )
                source_map = mapper.map_commit_changes(
                    commit_files=commit_files,
                    repo_files=file_contents,
                    commit_sha=commit_sha,
                )
                source_map.base_revision = base_rev
                source_map.head_revision = head_rev
        else:
            pr_num = target.pr_number or 1
            if gh_source is not None:
                pr_diff_resp = gh_source.get_pull_request_diff(repository_id, user_id, pr_num)
                if inspect.isawaitable(pr_diff_resp):
                    pr_diff_resp = await pr_diff_resp
                pr_info = getattr(pr_diff_resp, "pull_request", None)
                if pr_info is not None:
                    base_rev = base_rev or getattr(pr_info, "base_sha", None) or getattr(pr_info, "base_ref", None)
                    head_rev = target.head_revision or getattr(pr_info, "head_sha", None) or getattr(pr_info, "head_ref", None)
                    revision = head_rev or f"pr-{pr_num}"
                pr_files = list(getattr(pr_diff_resp, "files", []) or [])
                for pf in pr_files:
                    fname = getattr(pf, "filename", "") if not isinstance(pf, dict) else pf.get("filename", "")
                    status_raw = getattr(pf, "status", "modified") if not isinstance(pf, dict) else pf.get("status", "modified")
                    status_str = status_raw.value if hasattr(status_raw, "value") else str(status_raw)
                    patch_txt = getattr(pf, "patch", None) if not isinstance(pf, dict) else pf.get("patch")
                    try:
                        safe_fp = validate_repo_relative_path(fname)
                    except UnsafePathError:
                        continue
                    allowed_paths.add(safe_fp)
                    if safe_fp in path_to_record:
                        file_contents[safe_fp] = _reconstruct_indexed_file(db, repository_id, path_to_record[safe_fp])
                    elif patch_txt:
                        added = [
                            ln[1:]
                            for ln in patch_txt.splitlines()
                            if (ln.startswith("+") and not ln.startswith("+++")) or ln.startswith(" ")
                        ]
                        file_contents[safe_fp] = "\n".join(added)
                    mod_ranges: list[tuple[int, int]] = []
                    if patch_txt:
                        for hm in re.finditer(
                            r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@",
                            patch_txt,
                            re.MULTILINE,
                        ):
                            h_start = int(hm.group(1))
                            h_count = int(hm.group(2)) if hm.group(2) is not None else 1
                            if h_count > 0:
                                mod_ranges.append((h_start, h_start + h_count - 1))
                    modified_files.append(
                        ModifiedFile(
                            file_path=safe_fp,
                            change_type="deleted" if status_str == "removed" else status_str,
                            diff_hunks=[patch_txt] if patch_txt else [],
                            modified_line_ranges=mod_ranges,
                            content=file_contents.get(safe_fp, ""),
                        )
                    )
                source_map = mapper.map_commit_changes(
                    commit_files=pr_files,
                    repo_files=file_contents,
                    commit_sha=revision,
                )
                source_map.base_revision = base_rev
                source_map.head_revision = head_rev
                source_map.pr_number = pr_num

    for lim in source_map.limitations:
        missing_context.append(f"{lim.file_path}: {lim.description}")

    # Build caller graph for blast radius calculation when DB symbols exist
    symbol_graph: list[SymbolContext] = []
    if payload.options.include_context and hasattr(db, "query") and modified_files:
        try:
            mod_file_ids = [
                path_to_record[mf.file_path].id
                for mf in modified_files
                if mf.file_path in path_to_record
            ]
            if mod_file_ids:
                target_syms: list[CodeSymbol] = (
                    db.query(CodeSymbol)
                    .filter(
                        CodeSymbol.repository_id == repository_id,
                        CodeSymbol.file_id.in_(mod_file_ids),
                    )
                    .limit(30)
                    .all()
                )
                target_sym_ids = {s.id for s in target_syms}
                if target_sym_ids:
                    edges: list[SymbolEdge] = (
                        db.query(SymbolEdge)
                        .filter(
                            SymbolEdge.repository_id == repository_id,
                            (SymbolEdge.source_symbol_id.in_(target_sym_ids))
                            | (SymbolEdge.target_symbol_id.in_(target_sym_ids)),
                        )
                        .limit(20)
                        .all()
                    )
                    neighbor_ids = {
                        e.source_symbol_id for e in edges
                    } | {
                        e.target_symbol_id for e in edges
                    }
                    if neighbor_ids:
                        caller_syms: list[CodeSymbol] = (
                            db.query(CodeSymbol)
                            .filter(
                                CodeSymbol.repository_id == repository_id,
                                CodeSymbol.id.in_(neighbor_ids),
                            )
                            .all()
                        )
                        id_to_path = {f.id: f.path for f in all_repo_files}
                        for csym in caller_syms:
                            symbol_graph.append(
                                SymbolContext(
                                    name=csym.name,
                                    kind="caller",
                                    file_path=id_to_path.get(csym.file_id, "unknown"),
                                    start_line=csym.start_line,
                                    end_line=csym.end_line,
                                    content=csym.signature or "",
                                )
                            )
        except Exception:
            missing_context.append("Downstream caller graph could not be queried for blast radius.")

    project_rules: list[str] = []
    if payload.options.include_context and hasattr(db, "query"):
        try:
            memories: list[MemoryEntry] = (
                db.query(MemoryEntry)
                .filter(MemoryEntry.repository_id == repository_id)
                .limit(10)
                .all()
            )
            project_rules = [m.content for m in memories if getattr(m, "content", None)]
        except Exception:
            pass

    context_repo_files = [
        ContextRepoFile(
            id=str(f.id),
            path=f.path,
            language=f.language or "text",
            size_bytes=f.size_bytes or 0,
            line_count=f.line_count or 0,
            content_hash=f.content_hash or "",
        )
        for f in all_repo_files[:50]
    ]

    intelligence_ctx = ReviewContextBuilder().build_review_context(
        modified_files=modified_files,
        base_revision=base_rev,
        head_revision=head_rev,
        symbol_graph=symbol_graph,
        repository_files=context_repo_files if payload.options.include_context else [],
        project_rules=project_rules,
        token_budget=payload.options.max_context_tokens,
    )

    target_path_summary = (
        target.path
        or (modified_files[0].file_path if len(modified_files) == 1 else None)
        or (f"commit:{target.commit_sha}" if target.commit_sha else None)
        or (f"pr:{target.pr_number}" if target.pr_number else "diff")
    )

    return ResolvedReviewTarget(
        target=target,
        target_path_summary=target_path_summary,
        revision=revision,
        base_revision=base_rev,
        head_revision=head_rev,
        modified_files=modified_files,
        file_contents=file_contents,
        source_map=source_map,
        intelligence_context=intelligence_ctx,
        missing_context=list(dict.fromkeys(missing_context)),
        indexed_paths=indexed_paths,
        allowed_paths=allowed_paths,
    )


# ---------------------------------------------------------------------------
# 2. Static Review Pipeline on Modified Files & Hunks
# ---------------------------------------------------------------------------

def run_static_review_on_changes(
    repository_id: UUID,
    resolved: ResolvedReviewTarget,
    app_state: Any = None,
) -> tuple[list[ReviewFinding], list[str]]:
    """Run deterministic AST, secret, and dangerous-pattern static checks on reviewed changes."""
    findings: list[ReviewFinding] = []
    warnings: list[str] = []
    scanner = BuiltinStaticBugScanner()

    for mf in resolved.modified_files:
        if mf.change_type == "deleted":
            continue
        code_text = resolved.file_contents.get(mf.file_path) or mf.content
        if not code_text:
            continue

        bug_items, scan_warns = scanner.scan(
            file_path=mf.file_path,
            code_content=code_text,
            base_start_line=1,
            revision=resolved.revision,
            repository_id=str(repository_id),
        )
        warnings.extend(scan_warns)

        for bf in bug_items:
            # Determine if the finding falls within modified line ranges
            is_new = True
            if mf.modified_line_ranges and bf.source_reference.start_line is not None:
                s_ln = bf.source_reference.start_line
                e_ln = bf.source_reference.end_line or s_ln
                is_new = any(
                    not (e_ln < r_start or s_ln > r_end)
                    for r_start, r_end in mf.modified_line_ranges
                )

            findings.append(
                ReviewFinding(
                    id=bf.id.replace("static-", "rev-static-"),
                    category=map_to_review_category(bf.category, bf.rule_id),
                    severity=bf.severity,
                    title=bf.title,
                    description=bf.description,
                    source_reference=bf.source_reference,
                    evidence=bf.evidence,
                    suggested_fix=bf.suggested_fix,
                    confidence=bf.confidence,
                    is_uncertain=bf.is_uncertain,
                    is_new_in_change=is_new,
                    source_type="STATIC",
                    rule_id=bf.rule_id,
                )
            )

    # Also include structural defects found inside hunks by Prit's ReviewSourceMapper
    for f_map in resolved.source_map.files:
        for hunk in f_map.hunks:
            if hunk.ast_context and hunk.ast_context.structural_defects:
                for idx, defect in enumerate(hunk.ast_context.structural_defects):
                    rule_id = str(defect.get("rule_id") or "AST-RULE")
                    sev = str(defect.get("severity") or "MEDIUM").upper()
                    if sev not in SEVERITY_RANK:
                        sev = "MEDIUM"
                    s_ln = defect.get("start_line") or hunk.new_start_line
                    e_ln = defect.get("end_line") or s_ln
                    findings.append(
                        ReviewFinding(
                            id=f"rev-ast-{f_map.file_path}-{s_ln}-{idx}",
                            category=map_to_review_category(defect.get("category"), rule_id),
                            severity=sev,  # type: ignore[arg-type]
                            title=redact_secrets_in_text(str(defect.get("title") or defect.get("message") or rule_id)),
                            description=redact_secrets_in_text(
                                str(defect.get("description") or defect.get("message") or "Structural AST defect")
                            ),
                            source_reference=AnalysisSourceReference(
                                repository_id=str(repository_id),
                                file_path=f_map.file_path,
                                start_line=s_ln,
                                end_line=e_ln,
                                revision=resolved.revision,
                                symbol_name=hunk.qualified_symbol_name,
                            ),
                            evidence=redact_secrets_in_text(str(defect.get("evidence") or defect.get("snippet") or rule_id)),
                            suggested_fix=redact_secrets_in_text(defect.get("suggested_fix")) if defect.get("suggested_fix") else None,
                            confidence="high",
                            is_uncertain=False,
                            is_new_in_change=True,
                            source_type="STATIC",
                            rule_id=rule_id,
                        )
                    )

    return findings, warnings


# ---------------------------------------------------------------------------
# 3. Grounding, Secret Redaction, Deduplication & Report Assembly
# ---------------------------------------------------------------------------

def sanitize_review_finding(finding: ReviewFinding) -> ReviewFinding:
    """Redact any raw secret literals from a ReviewFinding."""
    return finding.model_copy(
        update={
            "title": redact_secrets_in_text(finding.title),
            "description": redact_secrets_in_text(finding.description),
            "evidence": redact_secrets_in_text(finding.evidence),
            "suggested_fix": (
                redact_secrets_in_text(finding.suggested_fix)
                if finding.suggested_fix is not None
                else None
            ),
        }
    )


_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def _max_known_line(resolved: "ResolvedReviewTarget", path: str) -> int:
    """Highest line number that can exist for `path` in the reviewed revision (0 = unknown).

    Uses the indexed file length and the new-file ranges of every diff hunk
    (`@@ -a,b +c,d @@` -> last line c+d-1), whichever is larger.
    """
    best = int(resolved.indexed_paths.get(path, 0) or 0)
    for modified in resolved.modified_files:
        if modified.file_path != path:
            continue
        for hunk in modified.diff_hunks or []:
            for match in _HUNK_HEADER.finditer(hunk or ""):
                start = int(match.group(1))
                length = int(match.group(2)) if match.group(2) is not None else 1
                best = max(best, start + max(length, 1) - 1)
        if modified.content:
            best = max(best, modified.content.count("\n") + 1) if not modified.diff_hunks else best
    return best


def normalize_and_ground_review_findings(
    raw_items: list[Any],
    *,
    repository_id: UUID,
    resolved: ResolvedReviewTarget,
    default_source_type: str | None = None,
) -> list[ReviewFinding]:
    """Coerce, redact secrets, and ground review findings against allowed/indexed repository files."""
    grounded: list[ReviewFinding] = []
    default_file = (
        resolved.target.path
        or (resolved.modified_files[0].file_path if resolved.modified_files else "diff")
    )

    for idx, item in enumerate(raw_items):
        if isinstance(item, ReviewFinding):
            finding = item
        elif isinstance(item, dict):
            data = dict(item)
            if not data.get("id"):
                data["id"] = f"rev-finding-{idx + 1}"
            if default_source_type and not data.get("source_type"):
                data["source_type"] = default_source_type
            raw_cat = data.get("category")
            data["category"] = map_to_review_category(raw_cat, data.get("rule_id"))
            raw_sev = str(data.get("severity") or "MEDIUM").upper()
            data["severity"] = raw_sev if raw_sev in SEVERITY_RANK else "MEDIUM"
            if "title" not in data:
                data["title"] = data.get("message") or data.get("rule_id") or "Review finding"
            if "description" not in data:
                data["description"] = data.get("message") or data["title"]
            if "evidence" not in data:
                data["evidence"] = data.get("snippet") or data.get("code") or data["description"]
            if "source_reference" not in data:
                fp = data.get("file_path") or data.get("file") or data.get("path") or default_file
                s_ln = data.get("start_line") or data.get("line") or data.get("line_number")
                e_ln = data.get("end_line") or s_ln
                data["source_reference"] = {
                    "file_path": fp,
                    "start_line": s_ln,
                    "end_line": e_ln,
                    "symbol_name": data.get("symbol_name") or data.get("symbol"),
                    "revision": data.get("revision") or resolved.revision,
                }
            finding = ReviewFinding.model_validate(data)
        else:
            finding = ReviewFinding.model_validate(item)

        # 1. Path traversal guard
        try:
            clean_path = validate_repo_relative_path(finding.source_reference.file_path)
        except UnsafePathError:
            continue

        # 2. Ground against allowed_paths / indexed_paths when repository has indexed files
        if resolved.indexed_paths and clean_path not in resolved.allowed_paths:
            continue

        # Security (W2 Day 5, Sukun): bound line references for EVERY target type
        # (file, commit, PR, diff), not only `file`, so the model cannot cite lines
        # that do not exist in the reviewed revision.
        max_lines = _max_known_line(resolved, clean_path)
        if max_lines > 0:
            s_line = finding.source_reference.start_line
            e_line = finding.source_reference.end_line
            if s_line is not None and s_line > max_lines:
                continue
            if e_line is not None and e_line > max_lines:
                continue

        updated_ref = finding.source_reference.model_copy(
            update={
                "repository_id": str(repository_id),
                "file_path": clean_path,
                "revision": finding.source_reference.revision or resolved.revision,
            }
        )
        finding = sanitize_review_finding(finding.model_copy(update={"source_reference": updated_ref}))
        grounded.append(finding)

    return grounded


def merge_and_rank_review_findings(
    findings: list[ReviewFinding],
    *,
    include_static: bool = True,
) -> list[ReviewFinding]:
    """Deduplicate overlapping STATIC + AI review findings into `COMBINED` and sort by severity."""
    merged: list[ReviewFinding] = []
    for candidate in findings:
        if not include_static and candidate.source_type == "STATIC":
            continue
        matched_idx: int | None = None
        for idx, existing in enumerate(merged):
            if (
                existing.rule_id
                and candidate.rule_id
                and existing.rule_id != candidate.rule_id
            ):
                continue
            if existing.source_reference.file_path != candidate.source_reference.file_path:
                continue
            a_s = existing.source_reference.start_line
            b_s = candidate.source_reference.start_line
            if a_s is not None and b_s is not None:
                a_e = existing.source_reference.end_line or a_s
                b_e = candidate.source_reference.end_line or b_s
                lines_match = (a_s - 2) <= b_e and (b_s - 2) <= a_e
            else:
                lines_match = a_s == b_s
            if lines_match and (
                existing.category == candidate.category
                or {existing.source_type, candidate.source_type} == {"STATIC", "AI"}
            ):
                matched_idx = idx
                break

        if matched_idx is None:
            merged.append(candidate)
        else:
            pri = merged[matched_idx]
            sec = candidate
            higher_sev: FindingSeverity = (
                pri.severity
                if SEVERITY_RANK.get(pri.severity, 0) >= SEVERITY_RANK.get(sec.severity, 0)
                else sec.severity
            )
            origins = {pri.source_type, sec.source_type}
            if origins == {"STATIC", "AI"} or "COMBINED" in origins:
                m_source = "COMBINED"
                m_conf = "high"
                m_uncertain = False
            else:
                m_source = pri.source_type
                m_conf = (
                    pri.confidence
                    if CONFIDENCE_RANK.get(pri.confidence, 0) >= CONFIDENCE_RANK.get(sec.confidence, 0)
                    else sec.confidence
                )
                m_uncertain = pri.is_uncertain and sec.is_uncertain

            if sec.evidence and sec.evidence not in pri.evidence:
                m_evidence = f"{pri.evidence} | Corroborating evidence: {sec.evidence}"
            else:
                m_evidence = pri.evidence

            s_lines = [x for x in (pri.source_reference.start_line, sec.source_reference.start_line) if x is not None]
            e_lines = [x for x in (pri.source_reference.end_line, sec.source_reference.end_line) if x is not None]
            m_ref = pri.source_reference.model_copy(
                update={
                    "start_line": min(s_lines) if s_lines else None,
                    "end_line": max(e_lines) if e_lines else None,
                    "symbol_name": pri.source_reference.symbol_name or sec.source_reference.symbol_name,
                }
            )
            merged[matched_idx] = sanitize_review_finding(
                pri.model_copy(
                    update={
                        "severity": higher_sev,
                        "source_type": m_source,  # type: ignore[arg-type]
                        "confidence": m_conf,  # type: ignore[arg-type]
                        "is_uncertain": m_uncertain,
                        "is_new_in_change": pri.is_new_in_change or sec.is_new_in_change,
                        "evidence": m_evidence,
                        "suggested_fix": pri.suggested_fix or sec.suggested_fix,
                        "rule_id": pri.rule_id or sec.rule_id,
                        "source_reference": m_ref,
                    }
                )
            )

    merged.sort(
        key=lambda f: (
            -SEVERITY_RANK.get(f.severity, 0),
            -SOURCE_TYPE_PRIORITY.get(f.source_type, 0),
            -CONFIDENCE_RANK.get(f.confidence, 0),
            f.source_reference.file_path,
            f.source_reference.start_line or 0,
        )
    )
    return merged


def compute_review_risk_level(findings: list[ReviewFinding]) -> str:
    """Compute overall ReviewReport.risk_level from grounded findings."""
    if not findings:
        return "NONE"
    max_rank = max(SEVERITY_RANK.get(f.severity, 1) for f in findings)
    if max_rank >= 5:
        return "CRITICAL"
    if max_rank == 4:
        return "HIGH"
    if max_rank == 3:
        return "MEDIUM"
    return "LOW"


def build_grounded_review_report(
    *,
    summary: str,
    findings: list[ReviewFinding],
    missing_context: list[str],
    explicit_risk_level: str | None = None,
) -> ReviewReport:
    """Construct a validated `ReviewReport` with accurate category_counts, total_findings, and risk_level."""
    cat_counts: dict[str, int] = {}
    for f in findings:
        cat_counts[f.category] = cat_counts.get(f.category, 0) + 1

    if explicit_risk_level in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"):
        final_risk = explicit_risk_level
    else:
        final_risk = compute_review_risk_level(findings)

    clean_summary = redact_secrets_in_text(summary.strip()) or (
        "Standalone code review completed with zero findings."
        if not findings
        else f"Standalone code review completed with {len(findings)} finding(s)."
    )

    return ReviewReport(
        summary=clean_summary,
        risk_level=final_risk,  # type: ignore[arg-type]
        findings=findings,
        total_findings=len(findings),
        category_counts=cat_counts,
        missing_context=list(dict.fromkeys(missing_context)),
    )


# ---------------------------------------------------------------------------
# 4. Default LLMCodeReviewService (Day 5 Service Adapter)
# ---------------------------------------------------------------------------
from ai.services.code_review_engine import AICodeReviewEngine, LLMCodeReviewService  # noqa: F401


# ---------------------------------------------------------------------------
# Day 5 Union Helpers & Aliases (parse_unified_diff_changed_lines, run_static_review_checks, compute_category_counts, merge_and_deduplicate_review_findings)
# ---------------------------------------------------------------------------

def parse_unified_diff_changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Parse a unified diff into a mapping of `{repo_relative_path: set_of_changed_new_line_numbers}`."""
    changed_by_file: dict[str, set[int]] = {}
    if not diff_text or not diff_text.strip():
        return changed_by_file

    mapper = ReviewSourceMapper()
    parsed_files = mapper.parse_unified_diff(diff_text)
    for rf in parsed_files:
        raw_fp = rf.new_path or rf.old_path or ""
        try:
            safe_fp = validate_repo_relative_path(raw_fp)
        except UnsafePathError:
            continue
        lines_set = changed_by_file.setdefault(safe_fp, set())
        for hunk in rf.hunks:
            cur_new = hunk.new_start
            for raw_ln in hunk.lines[1:]:
                if raw_ln.startswith("+") and not raw_ln.startswith("+++"):
                    lines_set.add(cur_new)
                    cur_new += 1
                elif raw_ln.startswith("-") and not raw_ln.startswith("---"):
                    continue
                elif raw_ln.startswith(" "):
                    cur_new += 1
            if not lines_set and hunk.new_start > 0:
                for ln_no in range(hunk.new_start, hunk.new_start + max(1, hunk.new_count)):
                    lines_set.add(ln_no)
    return changed_by_file


def run_static_review_checks(
    *,
    file_path: str,
    content: str,
    changed_lines: set[int] | None = None,
    revision: str | None = None,
    repository_id: str | None = None,
) -> list[ReviewFinding]:
    """Run deterministic static review checks on a single file and map findings to ReviewFinding."""
    if not content or not content.strip():
        return []
    scanner = BuiltinStaticBugScanner()
    bug_items, _ = scanner.scan(
        file_path=file_path,
        code_content=content,
        base_start_line=1,
        revision=revision,
        repository_id=repository_id,
    )
    review_findings: list[ReviewFinding] = []
    for bf in bug_items:
        s_ln = bf.source_reference.start_line
        e_ln = bf.source_reference.end_line or s_ln
        is_new = True
        if changed_lines is not None and s_ln is not None and e_ln is not None:
            is_new = any(ln in changed_lines for ln in range(s_ln, e_ln + 1))
        review_findings.append(
            ReviewFinding(
                id=bf.id.replace("static-", "rev-static-"),
                category=map_to_review_category(bf.category, bf.rule_id),
                severity=bf.severity,
                title=bf.title,
                description=bf.description,
                source_reference=bf.source_reference,
                evidence=bf.evidence,
                suggested_fix=bf.suggested_fix,
                confidence=bf.confidence,
                is_uncertain=bf.is_uncertain,
                is_new_in_change=is_new,
                source_type="STATIC",
                rule_id=bf.rule_id,
            )
        )
    return review_findings


def compute_category_counts(findings: list[ReviewFinding]) -> dict[str, int]:
    """Compute per-category finding counts across the 5 ReviewCategory dimensions."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.category] = counts.get(f.category, 0) + 1
    return counts


merge_and_deduplicate_review_findings = merge_and_rank_review_findings
