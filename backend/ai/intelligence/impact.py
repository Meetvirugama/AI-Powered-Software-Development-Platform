"""
Dependency Impact Analyzer.
Reference: task.md §5 (Incremental repository updates & dependency-aware updates)

Responsibilities:
- Determine the blast radius when files or symbols are modified.
- Traverse the persistent knowledge graph (callers, importers, inheritors).
- Identify which files need re-embedding (only directly modified files).
- Identify which modules/files need summary invalidation or refreshed explanation context.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Sequence

from pydantic import BaseModel, Field

from ai.intelligence.models import RepositoryIntelligenceSnapshot

logger = logging.getLogger(__name__)


class ImpactAnalysisReport(BaseModel):
    """Report detailing the dependency blast radius of a set of changed files."""

    changed_files: list[str] = Field(default_factory=list)
    reembed_files: list[str] = Field(default_factory=list, description="Files whose content changed; require vector re-embedding.")
    affected_files: list[str] = Field(default_factory=list, description="Downstream dependents whose behavior or explanations may be affected.")
    affected_modules: list[str] = Field(default_factory=list, description="Modules impacted by the changes.")
    affected_symbols: list[str] = Field(default_factory=list, description="Specific symbol nodes affected.")
    invalidation_needed: bool = False


class DependencyImpactAnalyzer:
    """Analyzes knowledge graph dependencies to compute incremental update impact."""

    def __init__(self, snapshot: RepositoryIntelligenceSnapshot | None = None) -> None:
        self.snapshot = snapshot

    def analyze_impact(
        self,
        changed_file_paths: Sequence[str],
        snapshot: RepositoryIntelligenceSnapshot | None = None,
    ) -> ImpactAnalysisReport:
        """
        Compute affected files, symbols, and modules given a list of modified file paths.
        Adheres to task.md §5:
        "If database.py changes, reparse database.py, update its graph relationships,
         identify modules and files that depend on it... but don't re-embed user_service.py
         if its source code has not changed."
        """
        snap = snapshot or self.snapshot
        changed_set = set(changed_file_paths)
        if not snap:
            return ImpactAnalysisReport(
                changed_files=list(changed_file_paths),
                reembed_files=list(changed_file_paths),
                affected_files=list(changed_file_paths),
                invalidation_needed=bool(changed_file_paths),
            )

        # Map file paths to node IDs
        file_to_nodes: dict[str, set[str]] = {}
        node_id_to_file: dict[str, str] = {}
        node_id_to_name: dict[str, str] = {}

        for n in snap.nodes:
            file_to_nodes.setdefault(n.file, set()).add(n.id)
            node_id_to_file[n.id] = n.file
            node_id_to_name[n.id] = n.name

        # Changed nodes
        changed_node_ids: set[str] = set()
        for f in changed_set:
            changed_node_ids.update(file_to_nodes.get(f, set()))

        # Build reverse adjacency map (target -> sources, i.e. who depends on target)
        dependents_map: dict[str, set[str]] = {}
        for edge in snap.edges:
            dependents_map.setdefault(edge.target, set()).add(edge.source)

        # BFS traverse callers and importers up to depth 2
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

        # Determine affected modules
        affected_modules: set[str] = set()
        for f in affected_files:
            for mod in snap.modules:
                if f in mod.files or f.startswith(mod.path):
                    affected_modules.add(mod.id)

        return ImpactAnalysisReport(
            changed_files=sorted(changed_set),
            reembed_files=sorted(changed_set),  # Only directly changed files need re-embedding
            affected_files=sorted(affected_files),
            affected_modules=sorted(affected_modules),
            affected_symbols=sorted(affected_symbols),
            invalidation_needed=bool(affected_files),
        )

