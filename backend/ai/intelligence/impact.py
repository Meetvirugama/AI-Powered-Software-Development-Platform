"""
Dependency Impact Analyzer.
Reference: task.md §5 & Issue 1 (PageRank F05-C3 + Co-Change Coupling)

Responsibilities:
- Determine the blast radius when files or symbols are modified.
- Traverse the persistent knowledge graph (callers, importers, inheritors).
- Identify historically co-changed files from Git history coupling.
- Rank affected files by PageRank importance (`high_importance_affected_files`) and compute a composite `impact_risk_score`.
- Identify which files need re-embedding (only directly modified files).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
import logging

from pydantic import BaseModel, Field

from ai.intelligence.models import RepositoryIntelligenceSnapshot

logger = logging.getLogger(__name__)


class ImpactAnalysisReport(BaseModel):
    """Report detailing the dependency blast radius of a set of changed files."""

    changed_files: list[str] = Field(default_factory=list)
    reembed_files: list[str] = Field(
        default_factory=list,
        description="Files whose content changed; require vector re-embedding.",
    )
    affected_files: list[str] = Field(
        default_factory=list,
        description="Downstream dependents whose behavior or explanations may be affected.",
    )
    co_change_coupled_files: list[str] = Field(
        default_factory=list,
        description="Files frequently modified together with changed_files in Git history.",
    )
    high_importance_affected_files: list[str] = Field(
        default_factory=list,
        description="Affected files ordered by descending PageRank importance score.",
    )
    affected_modules: list[str] = Field(
        default_factory=list,
        description="Modules impacted by the changes.",
    )
    affected_symbols: list[str] = Field(
        default_factory=list,
        description="Specific symbol nodes affected.",
    )
    impact_risk_score: float = Field(
        default=0.0,
        description="Normalized blast-radius risk score in [0.0, 1.0] weighted by PageRank importance.",
    )
    invalidation_needed: bool = False


class DependencyImpactAnalyzer:
    """Analyzes knowledge graph dependencies, PageRank importance, and Git co-change coupling to compute update impact."""

    def __init__(self, snapshot: RepositoryIntelligenceSnapshot | None = None) -> None:
        self.snapshot = snapshot

    def analyze_impact(
        self,
        changed_file_paths: Sequence[str],
        snapshot: RepositoryIntelligenceSnapshot | None = None,
        *,
        include_co_change_in_affected: bool = False,
    ) -> ImpactAnalysisReport:
        """
        Compute affected files, symbols, co-change coupled files, PageRank-prioritized files,
        and modules given a list of modified file paths.
        """
        snap = snapshot or self.snapshot
        changed_set = {str(p).replace("\\", "/") for p in changed_file_paths if p}
        if not snap:
            return ImpactAnalysisReport(
                changed_files=sorted(changed_set),
                reembed_files=sorted(changed_set),
                affected_files=sorted(changed_set),
                high_importance_affected_files=sorted(changed_set),
                impact_risk_score=0.2 if changed_set else 0.0,
                invalidation_needed=bool(changed_set),
            )

        # Map file paths to node IDs and PageRank importance
        file_to_nodes: dict[str, set[str]] = {}
        node_id_to_file: dict[str, str] = {}
        node_id_to_name: dict[str, str] = {}
        name_to_node_ids: dict[str, list[str]] = {}
        file_importance: dict[str, float] = {
            f.path: float(getattr(f, "importance_score", 0.0) or 0.0)
            for f in snap.files
        }

        for n in snap.nodes:
            file_to_nodes.setdefault(n.file, set()).add(n.id)
            node_id_to_file[n.id] = n.file
            node_id_to_name[n.id] = n.name
            if n.name:
                name_to_node_ids.setdefault(n.name, []).append(n.id)
            if n.file:
                file_importance[n.file] = max(
                    file_importance.get(n.file, 0.0),
                    float(getattr(n, "importance_score", 0.0) or 0.0),
                )

        # Changed nodes
        changed_node_ids: set[str] = set()
        for f in changed_set:
            changed_node_ids.update(file_to_nodes.get(f, set()))

        # Build reverse adjacency map (target -> sources, i.e. who depends on target) in O(|V| + |E|)
        dependents_map: dict[str, set[str]] = {}
        for edge in snap.edges:
            dependents_map.setdefault(edge.target, set()).add(edge.source)
            for nid in name_to_node_ids.get(edge.target, ()):
                dependents_map.setdefault(nid, set()).add(edge.source)

        # BFS traverse callers and importers
        visited_nodes: set[str] = set()
        queue = deque(changed_node_ids)
        affected_symbols: set[str] = set()
        affected_files: set[str] = set(changed_set)

        while queue:
            curr = queue.popleft()
            if curr in visited_nodes:
                continue
            visited_nodes.add(curr)
            if curr in node_id_to_name:
                affected_symbols.add(node_id_to_name[curr])
            if curr in node_id_to_file:
                affected_files.add(node_id_to_file[curr])

            for dep_id in dependents_map.get(curr, set()):
                if dep_id not in visited_nodes:
                    queue.append(dep_id)

        # Discover historically co-changed files from snapshot.co_change_edges
        co_changed_files: set[str] = set()
        for cc in getattr(snap, "co_change_edges", []) or []:
            if cc.file_a in changed_set and cc.file_b not in changed_set:
                co_changed_files.add(cc.file_b)
            elif cc.file_b in changed_set and cc.file_a not in changed_set:
                co_changed_files.add(cc.file_a)

        if include_co_change_in_affected:
            affected_files.update(co_changed_files)

        # Determine affected modules
        affected_modules: set[str] = set()
        for f in affected_files:
            for mod in snap.modules:
                if f in mod.files or f.startswith(mod.path):
                    affected_modules.add(mod.id)

        # Order affected files by descending PageRank importance (then alphabetically for stability)
        high_importance_affected = [
            f
            for f in sorted(
                affected_files,
                key=lambda fp: (-file_importance.get(fp, 0.0), fp),
            )
        ]

        # Compute composite impact risk score in [0.0, 1.0]
        if not affected_files:
            risk_score = 0.0
        else:
            max_imp = max((file_importance.get(fp, 0.0) for fp in affected_files), default=0.0)
            total_repo_files = max(1, len(snap.files) or len(affected_files))
            breadth_ratio = min(1.0, len(affected_files) / total_repo_files)
            entry_hit = any(ep.path in affected_files for ep in snap.entry_points)
            raw_risk = 0.50 * max_imp + 0.35 * breadth_ratio + (0.15 if entry_hit else 0.0)
            risk_score = round(min(1.0, max(0.05, raw_risk)), 4)

        return ImpactAnalysisReport(
            changed_files=sorted(changed_set),
            reembed_files=sorted(changed_set),
            affected_files=sorted(affected_files),
            co_change_coupled_files=sorted(co_changed_files),
            high_importance_affected_files=high_importance_affected,
            affected_modules=sorted(affected_modules),
            affected_symbols=sorted(affected_symbols),
            impact_risk_score=risk_score,
            invalidation_needed=bool(affected_files),
        )
