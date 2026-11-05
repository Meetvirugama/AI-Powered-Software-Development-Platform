"""
Related-File Discovery Service.
Reference: task.md §6.1, §6.2

Discovers and ranks related repository files for a selected file/symbol:
1. Direct dependencies & calls (weight 0.95)
2. Input/output types & schemas (weight 0.90)
3. Direct callers (weight 0.85)
4. Database models (weight 0.85)
5. Associated test files (weight 0.80)
6. Indirect dependencies (weight 0.65)
7. Semantic retrieval matches (weight 0.60)
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from ai.intelligence.models import RepositoryIntelligenceSnapshot

logger = logging.getLogger(__name__)

RelationKind = Literal[
    "imported_dependency",
    "called_dependency",
    "caller",
    "type_definition",
    "database_model",
    "associated_test",
    "indirect_dependency",
    "semantic_match",
]

RELATION_BADGE_MAP: dict[RelationKind, str] = {
    "imported_dependency": "Imported Dependency",
    "called_dependency": "Called Dependency",
    "caller": "Direct Caller",
    "type_definition": "Type / Schema",
    "database_model": "Database Model",
    "associated_test": "Associated Test",
    "indirect_dependency": "Indirect Dependency",
    "semantic_match": "Semantic Match",
}

RELATION_WEIGHTS: dict[RelationKind, float] = {
    "imported_dependency": 0.95,
    "called_dependency": 0.95,
    "type_definition": 0.90,
    "database_model": 0.85,
    "caller": 0.85,
    "associated_test": 0.80,
    "indirect_dependency": 0.65,
    "semantic_match": 0.60,
}


class DiscoveredRelatedFile(BaseModel):
    """A discovered related file with relationship type, weight, and reasoning."""

    path: str
    relation: RelationKind
    relation_label: str
    weight: float
    reason: str
    symbols: list[str] = Field(default_factory=list)
    is_preselected: bool = True


class RelatedFilesDiscoveryResponse(BaseModel):
    """Response containing discovered related files for an explanation target."""

    target_path: str
    target_symbol: str | None = None
    related_files: list[DiscoveredRelatedFile] = Field(default_factory=list)
    total_discovered: int = 0


class RelatedFileDiscoveryService:
    """Discovers related files from the persistent intelligence snapshot and database symbol edges."""

    def __init__(self, snapshot: RepositoryIntelligenceSnapshot | None = None) -> None:
        self.snapshot = snapshot

    def discover_related_files(
        self,
        target_path: str,
        target_symbol: str | None = None,
        snapshot: RepositoryIntelligenceSnapshot | None = None,
        all_repo_files: list[str] | None = None,
    ) -> list[DiscoveredRelatedFile]:
        """
        Identify related files for target_path and target_symbol using knowledge graph traversal.
        """
        snap = snapshot or self.snapshot
        discovered: dict[str, DiscoveredRelatedFile] = {}

        if not snap:
            # Fallback to heuristics based on filename naming conventions
            return self._fallback_discover(target_path, all_repo_files or [])

        # 1. Map symbols in target_path
        target_nodes = [n for n in snap.nodes if n.file == target_path]
        if target_symbol:
            specific_nodes = [n for n in target_nodes if n.name == target_symbol]
            if specific_nodes:
                target_nodes = specific_nodes

        target_node_ids = {n.id for n in target_nodes}
        target_node_names = {n.name for n in target_nodes}

        node_id_to_file = {n.id: n.file for n in snap.nodes}
        node_id_to_name = {n.id: n.name for n in snap.nodes}

        # 2. Direct dependencies: edges where source is in target_node_ids
        for edge in snap.edges:
            if edge.source in target_node_ids or edge.source in target_node_names:
                dep_file = node_id_to_file.get(edge.target)
                target_sym_name = node_id_to_name.get(edge.target, edge.target)
                if dep_file and dep_file != target_path:
                    rel_kind: RelationKind = (
                        "imported_dependency" if edge.type == "imports" else "called_dependency"
                    )
                    if "model" in dep_file.lower():
                        rel_kind = "database_model"
                    elif "schema" in dep_file.lower() or "type" in dep_file.lower():
                        rel_kind = "type_definition"

                    self._add_or_update(
                        discovered,
                        dep_file,
                        rel_kind,
                        f"{RELATION_BADGE_MAP[rel_kind]} ({edge.type} '{target_sym_name}')",
                        target_sym_name,
                        is_preselected=True,
                    )

            # Direct callers: edges where target is in target_node_ids
            if edge.target in target_node_ids or edge.target in target_node_names:
                caller_file = node_id_to_file.get(edge.source)
                caller_sym_name = node_id_to_name.get(edge.source, edge.source)
                if caller_file and caller_file != target_path:
                    self._add_or_update(
                        discovered,
                        caller_file,
                        "caller",
                        f"Direct Caller invoking target code from '{caller_sym_name}'",
                        caller_sym_name,
                        is_preselected=True,
                    )

        # 3. Associate Tests
        base_name = target_path.split("/")[-1].split(".")[0]
        for f in snap.files:
            if (
                f.is_test
                and f.path != target_path
                and (
                    base_name in f.path
                    or f.path.endswith((f"test_{base_name}.py", f"{base_name}.test.ts"))
                )
            ):
                    self._add_or_update(
                        discovered,
                        f.path,
                        "associated_test",
                        f"Associated test suite verifying '{base_name}'",
                        f.path,
                        is_preselected=False,  # Unchecked by default as shown in task.md §6
                    )

        # 4. Check for related models or schemas in the same subsystem
        module_id = next((f.module_id for f in snap.files if f.path == target_path), None)
        if module_id:
            for f in snap.files:
                if f.module_id == module_id and f.path != target_path and f.path not in discovered:
                    if "model" in f.path.lower():
                        self._add_or_update(
                            discovered,
                            f.path,
                            "database_model",
                            f"Database model in module '{module_id}'",
                            f.path,
                            is_preselected=True,
                        )
                    elif "schema" in f.path.lower():
                        self._add_or_update(
                            discovered,
                            f.path,
                            "type_definition",
                            f"Type schema in module '{module_id}'",
                            f.path,
                            is_preselected=True,
                        )

        # Sort discovered files by weight descending
        results = sorted(discovered.values(), key=lambda d: d.weight, reverse=True)
        return results

    def _add_or_update(
        self,
        store: dict[str, DiscoveredRelatedFile],
        file_path: str,
        relation: RelationKind,
        reason: str,
        symbol_name: str,
        is_preselected: bool = True,
    ) -> None:
        weight = RELATION_WEIGHTS.get(relation, 0.7)
        if file_path in store:
            existing = store[file_path]
            if symbol_name not in existing.symbols:
                existing.symbols.append(symbol_name)
            if weight > existing.weight:
                existing.weight = weight
                existing.relation = relation
                existing.relation_label = RELATION_BADGE_MAP[relation]
                existing.reason = reason
        else:
            store[file_path] = DiscoveredRelatedFile(
                path=file_path,
                relation=relation,
                relation_label=RELATION_BADGE_MAP[relation],
                weight=weight,
                reason=reason,
                symbols=[symbol_name] if symbol_name else [],
                is_preselected=is_preselected,
            )

    def _fallback_discover(
        self,
        target_path: str,
        all_repo_files: list[str],
    ) -> list[DiscoveredRelatedFile]:
        """Simple path-based heuristic discovery when snapshot is unavailable."""
        discovered: list[DiscoveredRelatedFile] = []
        base = target_path.split("/")[-1].split(".")[0]
        dir_prefix = "/".join(target_path.split("/")[:-1])

        for path in all_repo_files:
            if path == target_path:
                continue
            p_lower = path.lower()
            if f"test_{base}" in p_lower or f"{base}.test" in p_lower:
                discovered.append(
                    DiscoveredRelatedFile(
                        path=path,
                        relation="associated_test",
                        relation_label="Associated Test",
                        weight=0.80,
                        reason=f"Test file matching '{base}'",
                        is_preselected=False,
                    )
                )
            elif dir_prefix and path.startswith(dir_prefix):
                if "model" in p_lower:
                    discovered.append(
                        DiscoveredRelatedFile(
                            path=path,
                            relation="database_model",
                            relation_label="Database Model",
                            weight=0.85,
                            reason="Data model in same directory",
                            is_preselected=True,
                        )
                    )
                elif "schema" in p_lower or "type" in p_lower:
                    discovered.append(
                        DiscoveredRelatedFile(
                            path=path,
                            relation="type_definition",
                            relation_label="Type / Schema",
                            weight=0.90,
                            reason="Type definition in same directory",
                            is_preselected=True,
                        )
                    )

        return sorted(discovered, key=lambda d: d.weight, reverse=True)

