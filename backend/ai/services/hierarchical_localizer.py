"""Agentless-Style 3-Stage Hierarchical Fault & Edit Localizer (Issue 3 — P-17).

Reference:
- Xia et al. (2024), "Agentless: Demystifying LLM-based Software Engineering Agents" (arXiv:2407.01489)
- Issue 3: Task intake and LLM planning — Hierarchical localisation before/during planning:
  Stage 1: Rank candidate files (path hints, Week 2 findings, hybrid retrieval, symbol graph,
           PageRank importance F05-C3, and Git co-change coupling)
  Stage 2: Localize classes and functions (`CodeSymbol` / AST symbol extraction)
  Stage 3: Pinpoint exact 1-indexed inclusive line ranges (`start_line..end_line`) and edit regions

The resulting `LocalizationTarget` items are persisted in `StructuredPlan` and `PlanStep` for
human review (ADR-010) and fed directly into `EditSynthesizer` during autonomous execution.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
import logging
import re
from typing import Any

from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.models.analysis_finding import AnalysisFinding
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.schemas.plan import LocalizationTarget

logger = logging.getLogger(__name__)

_STOPWORDS: frozenset[str] = frozenset(
    {
        "this",
        "that",
        "with",
        "from",
        "need",
        "want",
        "only",
        "task",
        "file",
        "files",
        "code",
        "test",
        "tests",
        "make",
        "change",
        "please",
        "should",
        "must",
        "done",
        "into",
        "have",
        "been",
        "user",
        "when",
        "where",
        "what",
        "which",
        "while",
        "update",
        "implement",
        "fix",
        "add",
        "issue",
        "feature",
    }
)

_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
_FILE_HINT_RE = re.compile(r"\b([A-Za-z0-9_./\-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|c|cpp|h|hpp|json|ya?ml))\b")


def _extract_query_tokens(text: str) -> list[str]:
    """Extract informative identifier and keyword tokens (including snake_case/camelCase splits)."""
    if not text:
        return []
    raw_words = _IDENTIFIER_RE.findall(text)
    tokens: list[str] = []
    seen: set[str] = set()
    for word in raw_words:
        lower = word.lower()
        if lower not in _STOPWORDS and len(lower) >= 3 and lower not in seen:
            tokens.append(lower)
            seen.add(lower)
        # Also split camelCase / snake_case subtokens
        sub_parts = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", word).lower().split("_")
        for sp in sub_parts:
            if len(sp) >= 3 and sp not in _STOPWORDS and sp not in seen:
                tokens.append(sp)
                seen.add(sp)
    return tokens


class HierarchicalLocalizer:
    """Executes 3-stage Agentless-style hierarchical localization (Files -> Symbols -> Line Ranges)."""

    def __init__(
        self,
        *,
        max_candidate_files: int = 5,
        max_symbols_per_file: int = 3,
        max_total_targets: int = 8,
    ) -> None:
        self.max_candidate_files = max(1, max_candidate_files)
        self.max_symbols_per_file = max(1, max_symbols_per_file)
        self.max_total_targets = max(1, max_total_targets)

    def localize(
        self,
        task: Any,
        *,
        db: Any = None,
        repo_files: Sequence[str] | None = None,
        forbidden_files: Iterable[str] | None = None,
        manifest: Any = None,
        snapshot: Any = None,
    ) -> list[LocalizationTarget]:
        """Run all 3 stages (File Ranking -> Symbol Localization -> Line-Range Pinpointing)."""
        forbidden_lower = {str(f).strip().replace("\\", "/").lower() for f in (forbidden_files or []) if f}
        for cst in getattr(task, "constraints", None) or []:
            if isinstance(cst, dict):
                for fp in cst.get("forbidden_files", []) or []:
                    forbidden_lower.add(str(fp).strip().replace("\\", "/").lower())

        # Build query corpus from task title, description, requirements
        corpus_parts: list[str] = [
            str(getattr(task, "title", "") or ""),
            str(getattr(task, "description", "") or ""),
        ]
        explicit_req_files: list[str] = []
        for req in getattr(task, "requirements", None) or []:
            if isinstance(req, dict):
                corpus_parts.append(str(req.get("description", "") or ""))
                for tf in req.get("target_files", []) or []:
                    try:
                        norm = validate_repo_relative_path(str(tf))
                        if norm.lower() not in forbidden_lower and norm not in explicit_req_files:
                            explicit_req_files.append(norm)
                    except UnsafePathError:
                        continue
            elif hasattr(req, "description"):
                corpus_parts.append(str(getattr(req, "description", "") or ""))

        full_text = "\n".join(corpus_parts)
        query_tokens = _extract_query_tokens(full_text)
        explicit_path_hints = [
            m.group(1).strip().lstrip("./")
            for m in _FILE_HINT_RE.finditer(full_text)
        ]

        # Load DB records if available
        db_file_map: dict[str, RepositoryFile] = {}
        db_symbols_by_file: dict[str, list[CodeSymbol]] = defaultdict(list)
        db_chunks_by_file: dict[str, list[CodeChunk]] = defaultdict(list)
        origin_finding: AnalysisFinding | None = None
        repo_id = getattr(task, "repository_id", None)

        if db is not None and hasattr(db, "query") and getattr(db, "_is_mock_db", None) is not True and repo_id is not None:
            try:
                f_rows: list[RepositoryFile] = (
                    db.query(RepositoryFile)
                    .filter(RepositoryFile.repository_id == repo_id)
                    .limit(200)
                    .all()
                )
                id_to_path: dict[Any, str] = {}
                for fr in f_rows:
                    try:
                        norm_p = validate_repo_relative_path(fr.path)
                        if norm_p.lower() not in forbidden_lower:
                            db_file_map[norm_p] = fr
                            id_to_path[fr.id] = norm_p
                    except UnsafePathError:
                        continue

                s_rows: list[CodeSymbol] = (
                    db.query(CodeSymbol)
                    .filter(CodeSymbol.repository_id == repo_id)
                    .limit(400)
                    .all()
                )
                for sr in s_rows:
                    p = id_to_path.get(sr.file_id) or str(getattr(sr, "file_path", "") or "")
                    if p and p.lower() not in forbidden_lower:
                        db_symbols_by_file[p].append(sr)

                if getattr(task, "origin_finding_id", None):
                    origin_finding = db.get(AnalysisFinding, task.origin_finding_id)
            except Exception as exc:
                logger.debug("hierarchical_localizer_db_query_skipped: %s", exc)

        # Load snapshot if not provided
        if snapshot is None and repo_id is not None:
            try:
                from ai.intelligence.snapshot_manager import RepositoryIntelligenceSnapshotManager

                snapshot = RepositoryIntelligenceSnapshotManager().load_latest_snapshot(repo_id)
            except Exception:
                snapshot = None

        all_candidate_paths: list[str] = list(
            dict.fromkeys(
                [
                    *explicit_req_files,
                    *list(db_file_map.keys()),
                    *[
                        p
                        for p in (repo_files or [])
                        if p.lower() not in forbidden_lower
                    ],
                    *[
                        p
                        for p in (getattr(manifest, "target_files", []) if manifest else [])
                        if p.lower() not in forbidden_lower
                    ],
                    *[
                        p
                        for p in (getattr(manifest, "retrieved_files", []) if manifest else [])
                        if p.lower() not in forbidden_lower
                    ],
                ]
            )
        )

        # Stage 1: Rank candidate files
        ranked_files = self.rank_candidate_files(
            candidate_paths=all_candidate_paths,
            explicit_req_files=explicit_req_files,
            explicit_path_hints=explicit_path_hints,
            query_tokens=query_tokens,
            symbols_by_file=db_symbols_by_file,
            origin_finding=origin_finding,
            manifest=manifest,
            snapshot=snapshot,
            forbidden_lower=forbidden_lower,
        )

        if not ranked_files:
            return []

        # Stage 2 & Stage 3: Symbol Localization & Exact Line-Range Pinpointing
        targets: list[LocalizationTarget] = []
        for f_path, file_score, file_reason, file_imp in ranked_files[: self.max_candidate_files]:
            file_syms = list(db_symbols_by_file.get(f_path, []))
            if not file_syms and snapshot is not None:
                # Fallback to snapshot GraphNodes for this file
                file_syms = [
                    n for n in getattr(snapshot, "nodes", []) if getattr(n, "file", "") == f_path
                ]

            localized_syms = self.localize_symbols_in_file(
                file_path=f_path,
                symbols=file_syms,
                query_tokens=query_tokens,
                full_text=full_text,
                origin_finding=origin_finding,
            )

            # Fetch code chunks for snippet preview if DB is available
            file_rec = db_file_map.get(f_path)
            if file_rec is not None and db is not None and f_path not in db_chunks_by_file:
                try:
                    db_chunks_by_file[f_path] = (
                        db.query(CodeChunk)
                        .filter(
                            CodeChunk.repository_id == repo_id,
                            CodeChunk.file_id == file_rec.id,
                        )
                        .order_by(CodeChunk.start_line)
                        .limit(10)
                        .all()
                    )
                except Exception:
                    pass

            if localized_syms:
                for sym, sym_score, sym_reason in localized_syms[: self.max_symbols_per_file]:
                    s_line, e_line, preview = self.pinpoint_line_range(
                        file_path=f_path,
                        symbol=sym,
                        origin_finding=origin_finding,
                        chunks=db_chunks_by_file.get(f_path, []),
                        file_record=file_rec,
                    )
                    combined_conf = round(min(1.0, max(0.25, 0.55 * file_score + 0.45 * sym_score)), 4)
                    sym_imp = float(getattr(sym, "importance_score", 0.0) or file_imp or 0.0)
                    targets.append(
                        LocalizationTarget(
                            file_path=f_path,
                            symbol_name=str(getattr(sym, "name", "") or "") or None,
                            symbol_kind=str(getattr(sym, "kind", getattr(sym, "type", "symbol")) or "symbol"),
                            start_line=s_line,
                            end_line=e_line,
                            confidence=combined_conf,
                            localization_stage="line_range" if (s_line and e_line) else "symbol",
                            rationale=f"{file_reason}; {sym_reason}",
                            importance_score=round(sym_imp, 4),
                            snippet_preview=preview,
                        )
                    )
                    if len(targets) >= self.max_total_targets:
                        break
            else:
                s_line, e_line, preview = self.pinpoint_line_range(
                    file_path=f_path,
                    symbol=None,
                    origin_finding=origin_finding,
                    chunks=db_chunks_by_file.get(f_path, []),
                    file_record=file_rec,
                )
                targets.append(
                    LocalizationTarget(
                        file_path=f_path,
                        symbol_name=None,
                        symbol_kind="module",
                        start_line=s_line,
                        end_line=e_line,
                        confidence=round(min(1.0, max(0.2, file_score)), 4),
                        localization_stage="line_range" if (s_line and e_line) else "file",
                        rationale=file_reason,
                        importance_score=round(file_imp, 4),
                        snippet_preview=preview,
                    )
                )

            if len(targets) >= self.max_total_targets:
                break

        targets.sort(key=lambda t: (t.confidence, t.importance_score), reverse=True)
        return targets[: self.max_total_targets]

    # ------------------------------------------------------------------
    # Stage 1: Candidate File Ranking
    # ------------------------------------------------------------------

    def rank_candidate_files(
        self,
        *,
        candidate_paths: Sequence[str],
        explicit_req_files: Sequence[str],
        explicit_path_hints: Sequence[str],
        query_tokens: Sequence[str],
        symbols_by_file: dict[str, list[Any]],
        origin_finding: Any = None,
        manifest: Any = None,
        snapshot: Any = None,
        forbidden_lower: set[str] | None = None,
    ) -> list[tuple[str, float, str, float]]:
        """Rank candidate repository files using multi-signal scoring."""
        forbid = forbidden_lower or set()
        req_set = set(explicit_req_files)
        manifest_targets = set(getattr(manifest, "target_files", []) if manifest else [])
        manifest_retrieved = set(getattr(manifest, "retrieved_files", []) if manifest else [])

        finding_path: str | None = None
        if origin_finding is not None and getattr(origin_finding, "file_path", None):
            try:
                finding_path = validate_repo_relative_path(str(origin_finding.file_path))
            except UnsafePathError:
                finding_path = None

        # PageRank & Co-Change lookup from snapshot
        file_importance: dict[str, float] = {}
        co_change_partners: dict[str, list[tuple[str, float]]] = defaultdict(list)
        if snapshot is not None:
            for fi in getattr(snapshot, "files", []) or []:
                file_importance[fi.path] = float(getattr(fi, "importance_score", 0.0) or 0.0)
            for n in getattr(snapshot, "nodes", []) or []:
                if getattr(n, "file", None):
                    file_importance[n.file] = max(
                        file_importance.get(n.file, 0.0),
                        float(getattr(n, "importance_score", 0.0) or 0.0),
                    )
            for cc in getattr(snapshot, "co_change_edges", []) or []:
                co_change_partners[cc.file_a].append((cc.file_b, float(cc.jaccard_similarity)))
                co_change_partners[cc.file_b].append((cc.file_a, float(cc.jaccard_similarity)))

        seed_files = set(req_set) | ({finding_path} if finding_path else set())

        scored_files: list[tuple[str, float, str, float]] = []
        for raw_path in candidate_paths:
            try:
                path = validate_repo_relative_path(raw_path)
            except UnsafePathError:
                continue
            if path.lower() in forbid:
                continue

            score = 0.0
            reasons: list[str] = []
            p_lower = path.lower()
            base_name = p_lower.split("/")[-1]

            # 1. Explicit requirement or finding file
            if finding_path and path == finding_path:
                score += 0.95
                reasons.append("Matched origin finding target file")
            if path in req_set:
                score += 0.90
                reasons.append("Explicitly specified in task requirements")

            # 2. Explicit path hint in task description
            for hint in explicit_path_hints:
                h_lower = hint.lower()
                if p_lower == h_lower or p_lower.endswith(f"/{h_lower}") or base_name == h_lower:
                    score += 0.80
                    reasons.append(f"Mentioned in task description ('{hint}')")
                    break

            # 3. Hybrid retrieval / TaskContextBuilder match
            if path in manifest_targets:
                score += 0.45
                reasons.append("Ranked in task context target files")
            elif path in manifest_retrieved:
                score += 0.25
                reasons.append("Retrieved by hybrid semantic/lexical search")

            # 4. Lexical token overlap on file path & AST symbol names
            path_hits = sum(1 for tok in query_tokens if tok in p_lower)
            sym_list = symbols_by_file.get(path, [])
            sym_names_lower = [str(getattr(s, "name", "")).lower() for s in sym_list]
            sym_hits = sum(
                1
                for tok in query_tokens
                if any(tok == sn or tok in sn for sn in sym_names_lower)
            )
            if path_hits > 0 or sym_hits > 0:
                lex_boost = min(0.55, 0.12 * path_hits + 0.15 * sym_hits)
                score += lex_boost
                reasons.append(f"Lexical/AST symbol overlap (path={path_hits}, symbols={sym_hits})")

            # 5. Co-change coupling with seed files
            for seed_f in seed_files:
                for partner, jaccard in co_change_partners.get(seed_f, []):
                    if partner == path:
                        cc_boost = round(0.35 * jaccard, 4)
                        score += cc_boost
                        reasons.append(f"Co-changed in Git history with '{seed_f}' (Jaccard={jaccard:.2f})")

            # 6. PageRank importance secondary signal
            imp = file_importance.get(path, 0.0)
            if not imp and sym_list:
                imp = max((float(getattr(s, "importance_score", 0.0) or 0.0) for s in sym_list), default=0.0)
            if imp > 0.0:
                score += 0.10 * imp

            # Slight baseline for non-test source files when no query tokens matched yet
            if score == 0.0 and "test" not in p_lower and not p_lower.endswith(".md"):
                score = 0.15
                reasons.append("Primary repository source candidate")

            if score > 0.0:
                norm_score = min(1.0, score)
                scored_files.append(
                    (
                        path,
                        norm_score,
                        "; ".join(reasons) if reasons else "Candidate repository file",
                        imp,
                    )
                )

        scored_files.sort(key=lambda item: (item[1], item[3]), reverse=True)
        return scored_files

    # ------------------------------------------------------------------
    # Stage 2: Class / Function Symbol Localization
    # ------------------------------------------------------------------

    def localize_symbols_in_file(
        self,
        *,
        file_path: str,
        symbols: Sequence[Any],
        query_tokens: Sequence[str],
        full_text: str,
        origin_finding: Any = None,
    ) -> list[tuple[Any, float, str]]:
        """Rank symbols within a candidate file by relevance to the task."""
        if not symbols:
            return []

        full_lower = (full_text or "").lower()
        finding_line: int | None = None
        finding_file_norm: str | None = None
        if origin_finding is not None and getattr(origin_finding, "file_path", None):
            try:
                finding_file_norm = validate_repo_relative_path(str(origin_finding.file_path))
            except UnsafePathError:
                finding_file_norm = None
        if (
            origin_finding is not None
            and finding_file_norm == file_path
            and getattr(origin_finding, "start_line", None) is not None
        ):
            finding_line = int(origin_finding.start_line)

        scored_syms: list[tuple[Any, float, str]] = []
        for sym in symbols:
            s_name = str(getattr(sym, "name", "") or "")
            if not s_name:
                continue
            s_lower = s_name.lower()
            s_sig = str(getattr(sym, "signature", "") or "").lower()
            s_start = int(getattr(sym, "start_line", 1) or 1)
            s_end = int(getattr(sym, "end_line", s_start) or s_start)
            s_imp = float(getattr(sym, "importance_score", 0.0) or 0.0)

            score = 0.0
            reasons: list[str] = []

            # 1. Exact symbol mention in task text
            if len(s_lower) >= 3 and re.search(rf"\b{re.escape(s_lower)}\b", full_lower):
                score += 0.75
                reasons.append(f"Symbol '{s_name}' explicitly referenced in task")

            # 2. Finding line containment
            if finding_line is not None and s_start <= finding_line <= s_end:
                score += 0.85
                reasons.append(f"Encloses origin finding line L{finding_line}")

            # 3. Query token overlap with symbol name or signature
            tok_hits = sum(1 for tok in query_tokens if tok in s_lower or tok in s_sig)
            if tok_hits > 0:
                score += min(0.50, 0.18 * tok_hits)
                reasons.append(f"Matched {tok_hits} task keyword(s)")

            # 4. PageRank importance tie-breaker / primary symbol fallback
            if s_imp > 0.0:
                score += 0.15 * s_imp

            if score == 0.0:
                # Provide a modest baseline score so primary symbols in explicitly targeted files are still localized
                score = 0.25 + 0.15 * s_imp
                reasons.append(f"Top-level {getattr(sym, 'kind', 'symbol')} in target file")

            scored_syms.append(
                (
                    sym,
                    min(1.0, score),
                    "; ".join(reasons),
                )
            )

        scored_syms.sort(
            key=lambda item: (
                item[1],
                float(getattr(item[0], "importance_score", 0.0) or 0.0),
            ),
            reverse=True,
        )
        return scored_syms

    # ------------------------------------------------------------------
    # Stage 3: Line-Range & Edit-Region Pinpointing
    # ------------------------------------------------------------------

    @staticmethod
    def pinpoint_line_range(
        *,
        file_path: str,
        symbol: Any | None,
        origin_finding: Any = None,
        chunks: Sequence[Any] | None = None,
        file_record: Any = None,
    ) -> tuple[int | None, int | None, str | None]:
        """Pinpoint 1-indexed inclusive (start_line, end_line, snippet_preview) for a target symbol or file."""
        start_line: int | None = None
        end_line: int | None = None

        if symbol is not None:
            s_start = getattr(symbol, "start_line", None)
            s_end = getattr(symbol, "end_line", None)
            if isinstance(s_start, int) and s_start >= 1:
                start_line = s_start
                end_line = s_end if (isinstance(s_end, int) and s_end >= s_start) else s_start

        if (
            origin_finding is not None
            and getattr(origin_finding, "file_path", None) == file_path
            and getattr(origin_finding, "start_line", None) is not None
        ):
            f_start = int(origin_finding.start_line)
            f_end = int(getattr(origin_finding, "end_line", None) or f_start)
            if start_line is None:
                start_line = max(1, f_start - 5)
                end_line = f_end + 5

        if start_line is None and file_record is not None:
            line_cnt = int(getattr(file_record, "line_count", 0) or 0)
            if line_cnt > 0:
                start_line = 1
                end_line = min(line_cnt, 80)

        if start_line is None:
            start_line = 1
            end_line = 50

        preview: str | None = None
        if chunks:
            try:
                from indexer.chunker import reconstruct_file_from_chunks

                overlapping = [
                    c
                    for c in chunks
                    if getattr(c, "end_line", 0) >= start_line
                    and getattr(c, "start_line", 0) <= (end_line or start_line)
                ]
                if overlapping:
                    raw_preview = reconstruct_file_from_chunks(
                        overlapping,
                        start_line=start_line,
                        end_line=min(end_line or start_line, start_line + 30),
                    )
                    if raw_preview:
                        preview = raw_preview[:600]
            except Exception:
                preview = None

        return start_line, end_line, preview


__all__ = ["HierarchicalLocalizer"]
