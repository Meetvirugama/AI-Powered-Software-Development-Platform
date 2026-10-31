"""Symbol-Level Blast Radius & Dependency Impact Analysis Engine.

Owner: Prit Zania — Week 3 Day 2 Deliverable (Docs/week3.md §6 F32, F33 & Docs/daily_tasks.md line 614)
Reference: Docs/week3.md §6 (F32 Task Planner and Human Approval, F33 Isolated Workspace)

Responsibilities:
1. Map 1-indexed diff line ranges to precise AST symbols (classes, functions, methods).
2. Traverse the repository symbol dependency graph (calls, imports, extends, implements) with cycle protection.
3. Compute directly modified symbols, transitive callers/dependents, and complete affected files set.
4. Calculate quantitative and categorical Risk Assessment (low, medium, high, critical) with deterministic explanations.
5. Provide standard blast radius output consumed by TaskTestPlanner and Meet's TaskPlanner.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping, Sequence
from uuid import UUID

from app.schemas.planner_context import (
    AffectedSymbol,
    FileDiffRange,
    LineRange,
    RiskAssessment,
    RiskLevel,
    SymbolImpactType,
    TaskDiffRanges,
)
from scanner.symbols import Symbol, SymbolEdge


class SymbolBlastRadiusEngine:
    """Computes exact symbol-level blast radius and dependency call graph impact."""

    def __init__(self, max_depth: int = 3, max_symbols_budget: int = 500) -> None:
        """Initialize blast radius engine with traversal bounds.

        Args:
            max_depth: Maximum hops to traverse along dependency call/import edges (default 3).
            max_symbols_budget: Safety ceiling preventing runaway traversal on gigantic graphs.
        """
        self.max_depth = max(1, min(max_depth, 10))
        self.max_symbols_budget = max(10, max_symbols_budget)

    # -----------------------------------------------------------------------
    # 1. Diff Range to AST Symbol Resolution
    # -----------------------------------------------------------------------

    def map_diff_ranges_to_symbols(
        self,
        diff_inputs: Sequence[FileDiffRange] | Mapping[str, Sequence[LineRange | tuple[int, int]]],
        symbols_by_file: Mapping[str, Sequence[Symbol]],
    ) -> list[Symbol]:
        """Resolve inclusive 1-indexed diff line ranges to matching AST symbols.

        A symbol matches a diff range if their line intervals intersect:
        symbol.start_line <= range.end_line AND symbol.end_line >= range.start_line.

        Args:
            diff_inputs: Sequence of FileDiffRange objects or dict mapping file_path to ranges.
            symbols_by_file: Dict mapping normalized repo-relative file paths to Symbol lists.

        Returns:
            Deduplicated list of directly modified AST Symbol objects.
        """
        normalized_ranges: dict[str, list[tuple[int, int]]] = {}

        if isinstance(diff_inputs, Mapping):
            for path, r_list in diff_inputs.items():
                norm_p = path.replace("\\", "/").lstrip("/")
                for r in r_list:
                    if isinstance(r, (tuple, list)) and len(r) == 2:
                        normalized_ranges.setdefault(norm_p, []).append((int(r[0]), int(r[1])))
                    elif hasattr(r, "start_line") and hasattr(r, "end_line"):
                        normalized_ranges.setdefault(norm_p, []).append((int(r.start_line), int(r.end_line)))
        else:
            for item in diff_inputs:
                norm_p = item.file_path.replace("\\", "/").lstrip("/")
                for r in item.diff_ranges:
                    normalized_ranges.setdefault(norm_p, []).append((r.start_line, r.end_line))

        matched_symbols: list[Symbol] = []
        seen_ids: set[UUID] = set()

        for file_path, ranges in normalized_ranges.items():
            file_syms = symbols_by_file.get(file_path, [])
            if not file_syms:
                # Try matching without leading slashes or suffixes
                for key, syms in symbols_by_file.items():
                    if key.replace("\\", "/").lstrip("/") == file_path:
                        file_syms = syms
                        break

            for sym in file_syms:
                if sym.id in seen_ids:
                    continue
                for start, end in ranges:
                    # Interval intersection check: [sym.start_line, sym.end_line] overlaps [start, end]
                    if sym.start_line <= end and sym.end_line >= start:
                        matched_symbols.append(sym)
                        seen_ids.add(sym.id)
                        break

        # Sort symbols deterministically by file_id, start_line
        return sorted(matched_symbols, key=lambda s: (str(s.file_id), s.start_line))

    # -----------------------------------------------------------------------
    # 2. Dependency Graph Traversal & Blast Radius Computation
    # -----------------------------------------------------------------------

    def compute_symbol_blast_radius(
        self,
        direct_symbols: Sequence[Symbol],
        symbol_edges: Sequence[SymbolEdge],
        all_symbols_by_id: Mapping[UUID, Symbol],
        file_paths: Mapping[UUID, str],
        max_depth: int | None = None,
    ) -> tuple[list[AffectedSymbol], list[AffectedSymbol], list[str]]:
        """Traverse incoming dependency edges to identify all affected symbols and files.

        Explores callers, subclasses, and importers up to max_depth.
        Guarantees cycle-free traversal using visited tracking sets.

        Args:
            direct_symbols: Directly modified symbols identified from requirements or diffs.
            symbol_edges: SymbolEdge graph (calls, imports, extends, implements).
            all_symbols_by_id: Lookup map of all symbols in the repository.
            file_paths: Lookup map of file_id -> normalized repo-relative path.
            max_depth: Optional depth override.

        Returns:
            Tuple of (directly_modified_symbols, transitively_affected_symbols, all_affected_files).
        """
        depth_limit = max_depth if max_depth is not None else self.max_depth
        norm_file_paths = {fid: p.replace("\\", "/").lstrip("/") for fid, p in file_paths.items()}

        # Build reverse index: target_id -> list of (source_id, edge_type)
        # i.e., "who depends on / calls target_id?"
        incoming_edges: dict[UUID, list[tuple[UUID, str]]] = {}
        caller_counts: dict[UUID, int] = {}

        for edge in symbol_edges:
            incoming_edges.setdefault(edge.target_id, []).append((edge.source_id, edge.edge_type))
            caller_counts[edge.target_id] = caller_counts.get(edge.target_id, 0) + 1

        directly_modified: list[AffectedSymbol] = []
        transitively_affected: list[AffectedSymbol] = []
        visited: set[UUID] = set()
        affected_files_set: set[str] = set()

        # Seed directly modified symbols (depth = 0)
        queue: deque[tuple[Symbol, int, SymbolImpactType]] = deque()

        for sym in direct_symbols:
            visited.add(sym.id)
            f_path = norm_file_paths.get(sym.file_id, "unknown")
            affected_files_set.add(f_path)
            c_count = caller_counts.get(sym.id, 0)

            aff = AffectedSymbol(
                symbol_id=sym.id,
                name=sym.name,
                kind=sym.kind,
                file_path=f_path,
                start_line=sym.start_line,
                end_line=sym.end_line,
                is_direct_target=True,
                depth=0,
                impact_type="modified",
                signature=sym.signature,
                callers_count=c_count,
            )
            directly_modified.append(aff)
            queue.append((sym, 0, "modified"))

        # BFS along incoming edges
        while queue and (len(directly_modified) + len(transitively_affected)) < self.max_symbols_budget:
            curr_sym, depth, _ = queue.popleft()

            if depth >= depth_limit:
                continue

            dependents = incoming_edges.get(curr_sym.id, [])
            for dep_id, edge_type in dependents:
                if dep_id in visited:
                    continue

                dep_sym = all_symbols_by_id.get(dep_id)
                if dep_sym is None:
                    continue

                visited.add(dep_id)
                dep_path = norm_file_paths.get(dep_sym.file_id, "unknown")
                affected_files_set.add(dep_path)

                # Classify impact type
                impact_type: SymbolImpactType = "caller"
                if edge_type == "extends":
                    impact_type = "subclass"
                elif edge_type == "imports":
                    impact_type = "importer"
                elif edge_type != "calls":
                    impact_type = "indirect"

                c_count = caller_counts.get(dep_sym.id, 0)
                aff_trans = AffectedSymbol(
                    symbol_id=dep_sym.id,
                    name=dep_sym.name,
                    kind=dep_sym.kind,
                    file_path=dep_path,
                    start_line=dep_sym.start_line,
                    end_line=dep_sym.end_line,
                    is_direct_target=False,
                    depth=depth + 1,
                    impact_type=impact_type,
                    signature=dep_sym.signature,
                    callers_count=c_count,
                )
                transitively_affected.append(aff_trans)
                queue.append((dep_sym, depth + 1, impact_type))

        all_affected_files = sorted(f for f in affected_files_set if f != "unknown")
        return directly_modified, transitively_affected, all_affected_files

    # -----------------------------------------------------------------------
    # 3. Risk Assessment Engine
    # -----------------------------------------------------------------------

    def evaluate_risk(
        self,
        directly_modified: Sequence[AffectedSymbol],
        transitively_affected: Sequence[AffectedSymbol],
        affected_files: Sequence[str],
        symbol_edges: Sequence[SymbolEdge],
    ) -> RiskAssessment:
        """Calculate quantitative and categorical risk scores based on graph impact.

        Evaluation Criteria:
        - Critical: Direct target extended by >= 3 subclasses OR total affected callers >= 10 OR > 5 files.
        - High: Total affected callers >= 5 OR affected files >= 3 OR base class modified.
        - Medium: Affected callers between 2 and 4 OR affected files == 2.
        - Low: 0-1 callers, isolated changes confined to a single file.
        """
        reasons: list[str] = []
        direct_count = len(directly_modified)
        transitive_count = len(transitively_affected)
        file_count = len(affected_files)

        total_callers = sum(s.callers_count for s in directly_modified)
        subclass_impacts = [s for s in transitively_affected if s.impact_type == "subclass"]

        # Base score components
        file_penalty = min(0.35, file_count * 0.08)
        caller_penalty = min(0.40, total_callers * 0.04)
        subclass_penalty = min(0.25, len(subclass_impacts) * 0.10)

        raw_score = file_penalty + caller_penalty + subclass_penalty

        # Check for critical triggers
        if len(subclass_impacts) >= 3 or total_callers >= 10 or file_count >= 6:
            risk_level = RiskLevel.CRITICAL
            score = max(0.80, min(1.0, raw_score + 0.25))
            if len(subclass_impacts) >= 3:
                reasons.append(f"Target changes impact {len(subclass_impacts)} downstream subclass implementations.")
            if total_callers >= 10:
                reasons.append(f"High fan-in: Directly modified symbols have {total_callers} active caller sites.")
            if file_count >= 6:
                reasons.append(f"Broad blast radius: Changes affect {file_count} distinct repository files.")

        # Check for high triggers
        elif total_callers >= 5 or file_count >= 3 or len(subclass_impacts) >= 1:
            risk_level = RiskLevel.HIGH
            score = max(0.55, min(0.79, raw_score + 0.15))
            if total_callers >= 5:
                reasons.append(f"Significant caller exposure: {total_callers} dependent caller functions affected.")
            if file_count >= 3:
                reasons.append(f"Multi-module impact: Spans {file_count} repository files.")
            if len(subclass_impacts) >= 1:
                reasons.append(f"Alters inheritance hierarchy for {len(subclass_impacts)} subclass(es).")

        # Check for medium triggers
        elif total_callers >= 2 or file_count == 2 or transitive_count >= 2:
            risk_level = RiskLevel.MEDIUM
            score = max(0.30, min(0.54, raw_score + 0.10))
            if total_callers >= 2:
                reasons.append(f"Moderate caller exposure: {total_callers} callers affected.")
            if file_count == 2:
                reasons.append("Changes cross one internal module boundary.")
            if transitive_count >= 2:
                reasons.append(f"{transitive_count} transitive symbols in dependency chain.")

        # Low risk
        else:
            risk_level = RiskLevel.LOW
            score = max(0.05, min(0.29, raw_score))
            reasons.append("Isolated changes confined to local function or single module.")
            if total_callers <= 1:
                reasons.append("Minimal external caller footprint (<= 1 caller).")

        requires_human = risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

        summary = (
            f"Blast radius rated {risk_level.value.upper()} (score: {score:.2f}): "
            f"{direct_count} modified symbol(s), {transitive_count} transitively affected symbol(s) "
            f"across {file_count} file(s)."
        )

        return RiskAssessment(
            risk_level=risk_level,
            score=round(score, 2),
            summary=summary,
            reasons=reasons,
            requires_human_review=requires_human,
        )

    # -----------------------------------------------------------------------
    # 4. End-to-End Analysis Pipeline
    # -----------------------------------------------------------------------

    def analyze_task_diff_ranges(
        self,
        task_diff: TaskDiffRanges | Sequence[FileDiffRange],
        symbols_by_file: Mapping[str, Sequence[Symbol]],
        symbol_edges: Sequence[SymbolEdge],
        all_symbols_by_id: Mapping[UUID, Symbol],
        file_paths: Mapping[UUID, str],
        max_depth: int | None = None,
    ) -> tuple[list[AffectedSymbol], list[AffectedSymbol], list[str], RiskAssessment]:
        """Compute complete blast radius from TaskDiffRanges input.

        Returns:
            Tuple of (directly_modified, transitively_affected, all_affected_files, risk_assessment).
        """
        diff_list = task_diff.files if isinstance(task_diff, TaskDiffRanges) else task_diff
        direct_symbols = self.map_diff_ranges_to_symbols(diff_list, symbols_by_file)

        direct, transitive, affected_files = self.compute_symbol_blast_radius(
            direct_symbols=direct_symbols,
            symbol_edges=symbol_edges,
            all_symbols_by_id=all_symbols_by_id,
            file_paths=file_paths,
            max_depth=max_depth,
        )

        # Include direct diff files even if no symbols resolved (e.g., config or 0-byte additions)
        for item in diff_list:
            norm_p = item.file_path.replace("\\", "/").lstrip("/")
            if norm_p not in affected_files:
                affected_files.append(norm_p)
        affected_files.sort()

        risk = self.evaluate_risk(direct, transitive, affected_files, symbol_edges)
        return direct, transitive, affected_files, risk
