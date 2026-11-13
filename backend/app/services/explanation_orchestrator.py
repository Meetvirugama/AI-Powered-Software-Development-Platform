"""End-to-end orchestration for Week 2 Day 2 Code Explanation (`POST /repositories/{id}/explain`).

Owner: Yug — W2, Day 2 (Explanation Endpoint & Service Integration) & Issue 2 (Explain at Depth + Redaction Surfacing)

Implements the 9-step explanation pipeline required by `Docs/week2.md` §6:
1. Authenticate user (enforced at route boundary)
2. Verify repository access (enforced at route boundary)
3. Validate target file, symbol, and 1-indexed inclusive line range (resolving AST symbols via CodeSymbol)
4. Fetch the intended source content and revision from indexed repository chunks (detecting `[REDACTED]` tokens)
5. Build enriched `IntelligenceContext` (target snippet, related symbols/callers/callees with optional 1-hop "Explain at depth" expansion on F07-C3, repo files, rules)
6. Invoke configured `explanation_service` (or LLMGateway-backed explanation engine)
7. Validate structured `CodeExplanation` output and ground source citations against `repository_files`
8. Persist completed or failed analysis run metadata for history retrieval (`/analysis-runs`)
9. Return validated `CodeExplanationResponse`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
from typing import Any
from uuid import UUID

_DEFAULT_TIKTOKEN_CACHE = Path(__file__).resolve().parents[3] / ".venv" / "data-gym-cache"
if _DEFAULT_TIKTOKEN_CACHE.exists():
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(_DEFAULT_TIKTOKEN_CACHE))

from sqlalchemy.orm import Session

from ai.context.builder import (
    ContextBuilder,
    IntelligenceContext,
    RepositoryFile as ContextRepoFile,
    SymbolContext,
    TargetSnippet,
)
from app.core.errors import APIError, ErrorCode
from app.core.input_security import UnsafePathError, require_safe_repo_path, validate_repo_relative_path
from app.core.secret_redaction import redact, redact_obj
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.memory_entry import MemoryEntry
from app.models.repository import Repository
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.schemas.analysis import (
    AnalysisSourceReference,
    AnalysisTarget,
    CodeExplanation,
    ExplainCodeRequest,
)

logger = logging.getLogger(__name__)

MAX_ANALYZABLE_FILE_BYTES = 1_048_576  # 1 MB ceiling
MAX_IN_MEMORY_HISTORY_RUNS = 500       # Bounded FIFO capacity for _analysis_run_history
_REDACTED_MARKER_RE = re.compile(r"\[REDACTED(?:_[A-Z0-9_]+)?\]")


def detect_redacted_source_metadata(text: str) -> tuple[bool, int, str | None]:
    """Inspect reconstructed source code for `[REDACTED]` security placeholders (Issue 2 — C.3)."""
    if not text:
        return False, 0, None
    matches = _REDACTED_MARKER_RE.findall(text)
    count = len(matches)
    if count <= 0:
        return False, 0, None
    plural = "s" if count != 1 else ""
    notice = (
        f"Source code contains {count} redacted secret/configuration value{plural} "
        f"(`[REDACTED]`) withheld by security policy before AI analysis."
    )
    return True, count, notice


def is_explain_at_depth_enabled(payload: ExplainCodeRequest) -> bool:
    """Return True when 1-hop call-graph expansion ('Explain at depth', Issue 2 — C.1) is requested."""
    if getattr(payload, "explain_at_depth", False):
        return True
    if getattr(payload, "depth_mode", "standard") == "deep":
        return True
    ctx_opts = getattr(payload, "context", None)
    if ctx_opts and getattr(ctx_opts, "explain_at_depth", False):
        return True
    if getattr(payload, "explanation_level", "detailed") == "deep_technical":
        return True
    return False


@dataclass
class ResolvedExplanationTarget:
    """Validated target metadata, resolved source snippet, and assembled IntelligenceContext."""

    target: AnalysisTarget
    revision: str
    file_record: RepositoryFile | None
    resolved_symbol: CodeSymbol | None
    code_content: str
    intelligence_context: IntelligenceContext
    missing_context: list[str] = field(default_factory=list)
    indexed_paths: dict[str, int] = field(default_factory=dict)
    repo_files: list[RepositoryFile] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    execution_flow: list[str] = field(default_factory=list)
    has_redacted_content: bool = False
    redacted_occurrences: int = 0
    redaction_notice: str | None = None
    call_graph_depth_expanded: bool = False
    expanded_callers: list[str] = field(default_factory=list)
    expanded_callees: list[str] = field(default_factory=list)


def resolve_target_and_build_context(
    repository_id: UUID,
    repo: Repository | Any,
    payload: ExplainCodeRequest,
    db: Session | Any,
) -> ResolvedExplanationTarget:
    """Steps 3, 4 & 5: Validate target, resolve symbol/range, fetch source, and build IntelligenceContext."""
    safe_path = require_safe_repo_path(payload.target.path)
    target = payload.target.model_copy(update={"path": safe_path})
    revision = target.revision or getattr(repo, "default_branch", None) or "main"
    missing_context: list[str] = []
    deep_mode = is_explain_at_depth_enabled(payload)

    if getattr(db, "_is_mock_db", None) is True or not hasattr(db, "query"):
        # Unit-test mode with mock DB session (`object()`)
        snippet = TargetSnippet(
            file_path=safe_path,
            content="",
            start_line=target.start_line or 1,
            end_line=target.end_line or (target.start_line or 1),
            symbol_name=target.symbol,
            language="text",
        )
        ctx = ContextBuilder().build_intelligence_context(
            target=snippet,
            token_budget=payload.options.max_context_tokens,
        )
        return ResolvedExplanationTarget(
            target=target,
            revision=revision,
            file_record=None,
            resolved_symbol=None,
            code_content="",
            intelligence_context=ctx,
            missing_context=missing_context,
            indexed_paths={},
            call_graph_depth_expanded=deep_mode,
        )

    try:
        all_repo_files: list[RepositoryFile] = (
            db.query(RepositoryFile)
            .filter(RepositoryFile.repository_id == repository_id)
            .order_by(RepositoryFile.path)
            .all()
        )
    except Exception as exc:
        logger.error(
            "resolve_target_db_error",
            extra={"repository_id": str(repository_id), "path": safe_path, "error": str(exc)},
        )
        raise APIError(
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            "Database service is temporarily unavailable during target resolution.",
            retryable=True,
        ) from exc

    if not all_repo_files:
        sync_status = getattr(repo, "sync_status", None)
        if sync_status in ("NOT_SYNCED", "SYNCING"):
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"Repository indexing is in progress or not yet synced (status: {sync_status}). Please wait for indexing to complete.",
            )
        raise APIError(
            404,
            ErrorCode.FILE_NOT_FOUND,
            f"Target file '{safe_path}' was not found in the indexed repository.",
        )

    indexed_paths = {f.path: (f.line_count or 0) for f in all_repo_files}
    file_record = next((f for f in all_repo_files if f.path == safe_path), None)
    if file_record is None:
        raise APIError(
            404,
            ErrorCode.FILE_NOT_FOUND,
            f"Target file '{safe_path}' was not found in the indexed repository.",
        )

    if (file_record.size_bytes or 0) > MAX_ANALYZABLE_FILE_BYTES:
        raise APIError(
            413,
            ErrorCode.PAYLOAD_TOO_LARGE,
            "Target file exceeds the maximum analyzable size limit (1 MB).",
        )

    # Fetch all symbols for this file
    try:
        file_symbols: list[CodeSymbol] = (
            db.query(CodeSymbol)
            .filter(
                CodeSymbol.repository_id == repository_id,
                CodeSymbol.file_id == file_record.id,
            )
            .order_by(CodeSymbol.start_line)
            .all()
        )
    except Exception as exc:
        logger.error(
            "resolve_symbols_db_error",
            extra={"repository_id": str(repository_id), "path": safe_path, "error": str(exc)},
        )
        raise APIError(
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            "Database service is temporarily unavailable while loading file symbols.",
            retryable=True,
        ) from exc

    # Step 3b: Symbol Resolution (if symbol is specified)
    resolved_symbol: CodeSymbol | None = None
    if target.symbol:
        matching_symbols = [s for s in file_symbols if s.name == target.symbol]
        if target.start_line is not None and len(matching_symbols) > 1:
            matching_symbols = [
                s
                for s in matching_symbols
                if s.start_line <= target.start_line <= s.end_line
            ] or matching_symbols

        if matching_symbols:
            resolved_symbol = matching_symbols[0]
            if target.start_line is None:
                target.start_line = resolved_symbol.start_line
            if target.end_line is None:
                target.end_line = resolved_symbol.end_line
        elif file_symbols and target.type == "symbol":
            raise APIError(
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
                f"Symbol '{target.symbol}' was not found in '{safe_path}'.",
            )
        else:
            missing_context.append(
                f"Symbol '{target.symbol}' could not be resolved from the AST index; using file/line range context."
            )

    # Validate line range against file_record.line_count
    line_count = file_record.line_count or 0
    if line_count > 0:
        if target.start_line is not None and target.start_line > line_count:
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                f"start_line ({target.start_line}) exceeds file line count ({line_count}).",
            )
        if target.end_line is not None and target.end_line > line_count:
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                f"end_line ({target.end_line}) exceeds file line count ({line_count}).",
            )

    # Step 4: Reconstruct source content for the target file / line range
    try:
        file_chunks: list[CodeChunk] = (
            db.query(CodeChunk)
            .filter(
                CodeChunk.repository_id == repository_id,
                CodeChunk.file_id == file_record.id,
            )
            .order_by(CodeChunk.start_line)
            .all()
        )
    except Exception as exc:
        logger.error(
            "resolve_chunks_db_error",
            extra={"repository_id": str(repository_id), "path": safe_path, "error": str(exc)},
        )
        raise APIError(
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            "Database service is temporarily unavailable while loading file chunks.",
            retryable=True,
        ) from exc

    eff_start = target.start_line or 1
    eff_end = target.end_line or (line_count if line_count > 0 else max((c.end_line for c in file_chunks), default=1))

    selected_chunks = [
        c
        for c in file_chunks
        if c.end_line >= eff_start and c.start_line <= eff_end
    ]
    if not selected_chunks and file_chunks:
        selected_chunks = file_chunks

    from indexer.chunker import reconstruct_file_from_chunks

    code_content = reconstruct_file_from_chunks(
        selected_chunks,
        start_line=eff_start,
        end_line=eff_end,
    )
    if not code_content:
        missing_context.append(f"No indexed code chunks found for '{safe_path}'.")

    has_redacted, redacted_count, redaction_notice = detect_redacted_source_metadata(
        redact(code_content) if code_content else ""
    )

    # Step 5: Assemble related symbols, 1-hop callers/callees (building on F07-C3), and project rules
    related_symbol_contexts: list[SymbolContext] = []
    expanded_callers: list[str] = []
    expanded_callees: list[str] = []

    if payload.options.include_context:
        in_range_symbols: list[CodeSymbol] = []
        for sym in file_symbols:
            if sym.end_line >= eff_start and sym.start_line <= eff_end:
                in_range_symbols.append(sym)
                if resolved_symbol and sym.id == resolved_symbol.id:
                    continue
                related_symbol_contexts.append(
                    SymbolContext(
                        name=sym.name,
                        kind=sym.kind,
                        file_path=safe_path,
                        start_line=sym.start_line,
                        end_line=sym.end_line,
                        content=sym.signature or "",
                        importance_score=float(getattr(sym, "importance_score", 0.0) or 0.0),
                    )
                )

        # Seed symbols for call-graph traversal: resolved_symbol or all symbols in selected range
        seed_symbols: list[CodeSymbol] = (
            [resolved_symbol]
            if resolved_symbol is not None
            else (in_range_symbols[:8] if deep_mode else [])
        )
        seed_ids = [s.id for s in seed_symbols if getattr(s, "id", None) is not None]

        if seed_ids:
            try:
                edge_limit = 30 if deep_mode else 15
                edges: list[SymbolEdge] = (
                    db.query(SymbolEdge)
                    .filter(
                        SymbolEdge.repository_id == repository_id,
                        SymbolEdge.source_symbol_id.in_(seed_ids)
                        | SymbolEdge.target_symbol_id.in_(seed_ids),
                    )
                    .limit(edge_limit)
                    .all()
                )
                seed_id_set = set(seed_ids)
                caller_ids: set[Any] = set()
                callee_ids: set[Any] = set()
                unresolved_callee_names: list[str] = []

                for e in edges:
                    if e.target_symbol_id in seed_id_set and e.source_symbol_id not in seed_id_set and e.source_symbol_id is not None:
                        caller_ids.add(e.source_symbol_id)
                    if e.source_symbol_id in seed_id_set:
                        if e.target_symbol_id is not None and e.target_symbol_id not in seed_id_set:
                            callee_ids.add(e.target_symbol_id)
                        elif getattr(e, "target_name", None):
                            t_name = str(e.target_name).strip()
                            if t_name and t_name not in unresolved_callee_names:
                                unresolved_callee_names.append(t_name)

                neighbor_ids = caller_ids | callee_ids
                neighbor_syms: list[CodeSymbol] = []
                if neighbor_ids:
                    neighbor_syms = (
                        db.query(CodeSymbol)
                        .filter(
                            CodeSymbol.repository_id == repository_id,
                            CodeSymbol.id.in_(neighbor_ids),
                        )
                        .all()
                    )

                # In deep mode, also resolve unresolved callee names by symbol name within the repository
                if deep_mode and unresolved_callee_names:
                    named_callees: list[CodeSymbol] = (
                        db.query(CodeSymbol)
                        .filter(
                            CodeSymbol.repository_id == repository_id,
                            CodeSymbol.name.in_(unresolved_callee_names[:10]),
                        )
                        .limit(10)
                        .all()
                    )
                    existing_nids = {ns.id for ns in neighbor_syms}
                    for nc in named_callees:
                        if nc.id not in seed_id_set and nc.id not in existing_nids:
                            callee_ids.add(nc.id)
                            neighbor_syms.append(nc)
                            existing_nids.add(nc.id)

                file_id_to_path = {f.id: f.path for f in all_repo_files}
                # Sort neighbors by importance_score descending
                neighbor_syms.sort(
                    key=lambda s: float(getattr(s, "importance_score", 0.0) or 0.0),
                    reverse=True,
                )

                for nsym in neighbor_syms:
                    is_caller = nsym.id in caller_ids
                    is_callee = nsym.id in callee_ids
                    if is_caller and not getattr(payload.context, "include_callers", True):
                        continue
                    if is_callee and not getattr(payload.context, "include_callees", True):
                        continue

                    n_path = file_id_to_path.get(nsym.file_id, safe_path)
                    role_kind = "caller" if is_caller else ("callee" if is_callee else nsym.kind)
                    if is_caller and nsym.name not in expanded_callers:
                        expanded_callers.append(nsym.name)
                    if is_callee and nsym.name not in expanded_callees:
                        expanded_callees.append(nsym.name)

                    snippet_content = nsym.signature or ""
                    if deep_mode:
                        # Follow call graph 1 level (F07-C3): reconstruct 1-hop caller/callee source body
                        try:
                            n_chunks: list[CodeChunk] = (
                                db.query(CodeChunk)
                                .filter(
                                    CodeChunk.repository_id == repository_id,
                                    CodeChunk.file_id == nsym.file_id,
                                    CodeChunk.end_line >= nsym.start_line,
                                    CodeChunk.start_line <= nsym.end_line,
                                )
                                .order_by(CodeChunk.start_line)
                                .limit(3)
                                .all()
                            )
                            if n_chunks:
                                body_text = reconstruct_file_from_chunks(
                                    n_chunks,
                                    start_line=nsym.start_line,
                                    end_line=min(nsym.end_line, nsym.start_line + 60),
                                )
                                if body_text:
                                    snippet_content = body_text[:1500]
                                    c_red, c_cnt, _ = detect_redacted_source_metadata(snippet_content)
                                    if c_red:
                                        has_redacted = True
                                        redacted_count += c_cnt
                        except Exception:
                            pass

                    related_symbol_contexts.append(
                        SymbolContext(
                            name=nsym.name,
                            kind=role_kind,
                            file_path=n_path,
                            start_line=nsym.start_line,
                            end_line=nsym.end_line,
                            content=snippet_content,
                            importance_score=float(getattr(nsym, "importance_score", 0.0) or 0.0),
                        )
                    )
            except Exception:
                missing_context.append("Caller/callee symbol graph edges could not be queried.")
    else:
        missing_context.append("Repository context enrichment was disabled by request options (include_context=False).")

    # User-selected related files (task.md §6, §6.3)
    user_selected_files: list[str] = []
    context_opts = getattr(payload, "context", None)
    if context_opts and getattr(context_opts, "selected_files", None):
        user_selected_files = list(context_opts.selected_files)
    elif getattr(payload.options, "selected_files", None):
        user_selected_files = list(getattr(payload.options, "selected_files"))

    for sel_path in user_selected_files:
        try:
            clean_sel = validate_repo_relative_path(sel_path)
            sel_file = next((f for f in all_repo_files if f.path == clean_sel), None)
            if sel_file:
                sel_chunks: list[CodeChunk] = (
                    db.query(CodeChunk)
                    .filter(CodeChunk.repository_id == repository_id, CodeChunk.file_id == sel_file.id)
                    .order_by(CodeChunk.start_line)
                    .limit(5)
                    .all()
                )
                sel_code = reconstruct_file_from_chunks(sel_chunks, start_line=1, end_line=min(200, sel_file.line_count or 100))
                if sel_code:
                    s_red, s_cnt, _ = detect_redacted_source_metadata(sel_code)
                    if s_red:
                        has_redacted = True
                        redacted_count += s_cnt
                    related_symbol_contexts.append(
                        SymbolContext(
                            name=clean_sel.split("/")[-1],
                            kind="user_selected_file",
                            file_path=clean_sel,
                            start_line=1,
                            end_line=min(200, sel_file.line_count or 100),
                            content=sel_code[:2500],
                        )
                    )
        except Exception as sel_exc:
            logger.debug("Failed adding user-selected file %s: %s", sel_path, sel_exc)

    if has_redacted and not redaction_notice:
        plural = "s" if redacted_count != 1 else ""
        redaction_notice = (
            f"Source code contains {redacted_count} redacted secret/configuration value{plural} "
            f"(`[REDACTED]`) withheld by security policy before AI analysis."
        )
    elif has_redacted and redacted_count > 0:
        plural = "s" if redacted_count != 1 else ""
        redaction_notice = (
            f"Source code contains {redacted_count} redacted secret/configuration value{plural} "
            f"(`[REDACTED]`) withheld by security policy before AI analysis."
        )

    # Discover related files & execution flow from persistent Repository Intelligence Snapshot (task.md §3, §6.1, §8.B)
    execution_flow: list[str] = []
    resolved_related_files: list[str] = list(user_selected_files)

    try:
        from ai.intelligence.related_files import RelatedFileDiscoveryService
        from ai.intelligence.snapshot_manager import RepositoryIntelligenceSnapshotManager

        snap_mgr = RepositoryIntelligenceSnapshotManager()
        snapshot = snap_mgr.load_latest_snapshot(repository_id)
        if snapshot:
            discovery_svc = RelatedFileDiscoveryService(snapshot=snapshot)
            discovered = discovery_svc.discover_related_files(
                target_path=safe_path,
                target_symbol=target.symbol,
                snapshot=snapshot,
            )
            for d in discovered:
                if d.path not in resolved_related_files:
                    resolved_related_files.append(d.path)

            target_name = target.symbol or safe_path.split("/")[-1]
            callers = expanded_callers or [d.symbols[0] for d in discovered if d.relation == "caller" and d.symbols]
            dependencies = expanded_callees or [d.symbols[0] for d in discovered if d.relation in ("imported_dependency", "called_dependency") and d.symbols]
            db_models = [d.symbols[0] for d in discovered if d.relation == "database_model" and d.symbols]

            if callers:
                execution_flow.append(f"Inbound trigger: Called by {', '.join(callers[:3])}")
            execution_flow.append(f"Execution: Core logic handled in {target_name} ({safe_path})")
            if dependencies:
                execution_flow.append(f"Downstream logic: Invokes {', '.join(dependencies[:3])}")
            if db_models:
                execution_flow.append(f"Persistence layer: Interacts with data model {', '.join(db_models[:2])}")
        elif expanded_callers or expanded_callees:
            target_name = target.symbol or safe_path.split("/")[-1]
            if expanded_callers:
                execution_flow.append(f"Inbound trigger: Called by {', '.join(expanded_callers[:3])}")
            execution_flow.append(f"Execution: Core logic handled in {target_name} ({safe_path})")
            if expanded_callees:
                execution_flow.append(f"Downstream logic: Invokes {', '.join(expanded_callees[:3])}")
    except Exception as flow_exc:
        logger.debug("Execution flow derivation skipped: %s", flow_exc)

    # Project rules from MemoryEntry
    project_rules: list[str] = []
    if payload.options.include_context:
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

    target_snippet = TargetSnippet(
        file_path=safe_path,
        content=code_content,
        start_line=eff_start,
        end_line=eff_end,
        symbol_name=target.symbol or (resolved_symbol.name if resolved_symbol else None),
        language=file_record.language or "text",
    )

    effective_budget = payload.options.max_context_tokens
    if deep_mode and effective_budget == 4_000:
        effective_budget = 6_500

    intelligence_ctx = ContextBuilder().build_intelligence_context(
        target=target_snippet,
        related_symbols=related_symbol_contexts,
        relevant_chunks=selected_chunks if payload.options.include_context else [],
        repository_files=context_repo_files if payload.options.include_context else [],
        project_rules=project_rules,
        token_budget=effective_budget,
    )

    return ResolvedExplanationTarget(
        target=target,
        revision=revision,
        file_record=file_record,
        resolved_symbol=resolved_symbol,
        code_content=code_content,
        intelligence_context=intelligence_ctx,
        missing_context=missing_context,
        indexed_paths=indexed_paths,
        repo_files=all_repo_files,
        related_files=resolved_related_files,
        execution_flow=execution_flow,
        has_redacted_content=has_redacted,
        redacted_occurrences=redacted_count,
        redaction_notice=redaction_notice,
        call_graph_depth_expanded=deep_mode,
        expanded_callers=expanded_callers,
        expanded_callees=expanded_callees,
    )


def calculate_grounding_confidence(
    *,
    target_found: bool,
    source_references_valid: bool,
    related_symbols_verified: bool,
    critical_context_missing: bool,
    ungrounded_ratio: float = 0.0,
    initial_confidence: str = "high",
) -> str:
    """Calculates multi-signal deterministic grounding confidence (task.md §5 Problem 3 & §6.B)."""
    if not target_found or not source_references_valid or ungrounded_ratio > 0.5:
        return "low"
    if critical_context_missing:
        return "low"
    if ungrounded_ratio > 0.0:
        return "medium" if initial_confidence == "high" else "low"
    if not related_symbols_verified:
        return "medium"
    return initial_confidence if initial_confidence in ("high", "medium", "low") else "high"


def ground_explanation_sources(
    explanation: CodeExplanation,
    *,
    repository_id: UUID,
    resolved: ResolvedExplanationTarget,
) -> CodeExplanation:
    """Step 7b: Remove hallucinated or unsafe citations, attach redaction & depth metadata, and calibrate confidence."""
    merged_missing = list(dict.fromkeys([*explanation.missing_context, *resolved.missing_context]))

    raw_sources = list(explanation.sources)
    grounded_sources: list[AnalysisSourceReference] = []
    ungrounded_count = 0

    for src in raw_sources:
        try:
            clean_path = validate_repo_relative_path(src.file_path)
        except UnsafePathError:
            ungrounded_count += 1
            continue

        s_line = src.start_line
        e_line = src.end_line
        if s_line is not None and e_line is not None and s_line > e_line:
            s_line, e_line = min(s_line, e_line), max(s_line, e_line)

        if resolved.indexed_paths:
            if clean_path not in resolved.indexed_paths:
                ungrounded_count += 1
                continue
            max_lines = resolved.indexed_paths[clean_path]
            if max_lines > 0:
                if s_line is not None and s_line > max_lines:
                    ungrounded_count += 1
                    continue
                if e_line is not None and e_line > max_lines:
                    ungrounded_count += 1
                    continue

        grounded_sources.append(
            src.model_copy(
                update={
                    "repository_id": str(repository_id),
                    "file_path": clean_path,
                    "start_line": s_line,
                    "end_line": e_line,
                    "revision": resolved.revision or src.revision,
                }
            )
        )

    # Multi-signal confidence calibration (task.md §6.B)
    ungrounded_ratio = ungrounded_count / len(raw_sources) if raw_sources else 0.0
    target_found = (
        resolved.file_record is not None
        or (
            resolved.target is not None
            and (not resolved.indexed_paths or resolved.target.path in resolved.indexed_paths)
        )
    )
    source_references_valid = len(grounded_sources) > 0 or not raw_sources
    critical_context_missing = any(
        "unavailable" in m.lower() or "incomplete" in m.lower() or "missing" in m.lower()
        for m in merged_missing
    )
    related_symbols_verified = bool(
        resolved.resolved_symbol
        or resolved.related_files
        or not resolved.indexed_paths
        or len(grounded_sources) > 0
    )

    confidence = calculate_grounding_confidence(
        target_found=target_found,
        source_references_valid=source_references_valid,
        related_symbols_verified=related_symbols_verified,
        critical_context_missing=critical_context_missing,
        ungrounded_ratio=ungrounded_ratio,
        initial_confidence=explanation.confidence,
    )

    # Guarantee that when a real target file was resolved, its grounded citation is attached
    if not grounded_sources and resolved.file_record is not None:
        grounded_sources.append(
            AnalysisSourceReference(
                repository_id=str(repository_id),
                file_path=resolved.target.path,
                start_line=resolved.target.start_line or 1,
                end_line=resolved.target.end_line or (resolved.file_record.line_count or 1),
                revision=resolved.revision,
                symbol_name=resolved.target.symbol,
            )
        )

    # Surface redaction metadata (Issue 2 — C.3)
    has_redacted = bool(explanation.has_redacted_content or resolved.has_redacted_content)
    redacted_occurrences = max(explanation.redacted_occurrences, resolved.redacted_occurrences)
    redaction_notice = explanation.redaction_notice or resolved.redaction_notice

    return explanation.model_copy(
        update={
            "sources": grounded_sources,
            "confidence": confidence,
            "missing_context": merged_missing,
            "related_files": explanation.related_files or list(resolved.related_files),
            "execution_flow": explanation.execution_flow or list(resolved.execution_flow),
            "has_redacted_content": has_redacted,
            "redacted_occurrences": redacted_occurrences,
            "redaction_notice": redaction_notice,
            "call_graph_depth_expanded": bool(
                explanation.call_graph_depth_expanded or resolved.call_graph_depth_expanded
            ),
            "expanded_callers": explanation.expanded_callers or list(resolved.expanded_callers),
            "expanded_callees": explanation.expanded_callees or list(resolved.expanded_callees),
        }
    )


def record_analysis_run(
    app_state: Any,
    db: Session | Any,
    *,
    run_id: str,
    repository_id: UUID,
    user_id: UUID,
    feature_type: str,
    status: str,
    target: AnalysisTarget,
    revision: str | None,
    result_payload: dict[str, Any] | None = None,
    findings: list[dict[str, Any]] | None = None,
    error_message: str | None = None,
    findings_count: int = 0,
    test_output: str | None = None,
    **extra_kwargs: Any,
) -> None:
    """Step 8: Persist analysis run (COMPLETED or FAILED) to Om's repository or in-memory history store."""
    result_payload = redact_obj(result_payload) if result_payload is not None else None
    findings = redact_obj(findings) if findings else findings
    error_message = redact(error_message) if error_message else error_message
    now = datetime.now(timezone.utc)

    resolved_test_output = test_output
    if resolved_test_output is None and result_payload:
        resolved_test_output = (
            result_payload.get("test_content")
            or result_payload.get("complete_test_code")
            or result_payload.get("test_output")
            or (
                result_payload.get("result", {}).get("test_content")
                if isinstance(result_payload.get("result"), dict)
                else None
            )
        )

    target_path = getattr(target, "path", None) if target is not None else None
    target_symbol = getattr(target, "symbol", None) if target is not None else None
    if not target_symbol and target is not None:
        pr_num = getattr(target, "pr_number", None)
        commit_sha = getattr(target, "commit_sha", None)
        if pr_num is not None:
            target_symbol = f"PR #{pr_num}"
        elif commit_sha:
            target_symbol = f"Commit {commit_sha[:8]}"

    start_line = getattr(target, "start_line", None) if target is not None else None
    end_line = getattr(target, "end_line", None) if target is not None else None
    resolved_rev = revision
    if not resolved_rev and target is not None:
        resolved_rev = (
            getattr(target, "head_revision", None)
            or getattr(target, "commit_sha", None)
            or (f"pr/{target.pr_number}" if getattr(target, "pr_number", None) is not None else None)
            or getattr(target, "base_revision", None)
            or getattr(target, "revision", None)
        )

    record = {
        "id": str(run_id),
        "repository_id": str(repository_id),
        "user_id": str(user_id),
        "feature_type": feature_type,
        "status": status,
        "target_path": target_path,
        "target_symbol": target_symbol,
        "start_line": start_line,
        "end_line": end_line,
        "source_revision": resolved_rev,
        "findings_count": findings_count,
        "result_payload": result_payload,
        "test_output": resolved_test_output,
        "findings": findings or [],
        "error_message": error_message,
        "created_at": now,
        "completed_at": now if status in ("COMPLETED", "FAILED", "CANCELLED") else None,
    }

    persisted_direct = False
    if db is not None:
        try:
            from app.repositories.analysis_run_repository import AnalysisRunRepository

            AnalysisRunRepository(db).create_run(**record)
            persisted_direct = True
        except Exception as exc:
            if hasattr(db, "rollback"):
                try:
                    db.rollback()
                except Exception:
                    pass
            logger.warning("analysis_run_repository_create_run_failed", extra={"error": str(exc)})

    if not persisted_direct:
        run_service = getattr(app_state, "analysis_run_service", None)
        if run_service is not None and hasattr(run_service, "record_run"):
            try:
                run_service.record_run(record)
            except Exception:
                pass

    history_store: dict[str, dict[str, Any]] | None = getattr(
        app_state, "_analysis_run_history", None
    )
    if history_store is None:
        history_store = {}
        try:
            setattr(app_state, "_analysis_run_history", history_store)
        except Exception:
            return
    history_store[str(run_id)] = record
    while len(history_store) > MAX_IN_MEMORY_HISTORY_RUNS:
        oldest_key = next(iter(history_store))
        history_store.pop(oldest_key, None)


def enforce_gateway_provider_policy(gateway: Any) -> None:
    """Enforce Docs/week2.md §4.5: Only Gemini and Groq are allowed; disallow other providers (e.g. openai)."""
    if gateway is None:
        return
    provider = getattr(gateway, "provider", None)
    provider_name = getattr(provider, "provider_name", None) or getattr(provider, "name", None)
    if isinstance(provider_name, str):
        normalized = provider_name.strip().lower()
        if normalized not in ("gemini", "groq", "mock", "test"):
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                f"Provider '{provider_name}' is not permitted by policy. Only Gemini and Groq are allowed.",
            )


from ai.services.explanation_service import CodeExplanationService

# Maintain backward compatibility
LLMCodeExplanationService = CodeExplanationService
