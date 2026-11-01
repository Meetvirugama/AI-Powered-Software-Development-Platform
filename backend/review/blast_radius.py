"""Identify repository files affected by changes to other files."""

from collections import deque
from typing import Any, Mapping, Sequence

try:
    from scanner.import_tracker import FileImportMap
except ImportError:
    from backend.scanner.import_tracker import FileImportMap


class BlastRadiusEngine:
    """Find files that directly or indirectly depend on changed files."""

    def compute(
        self,
        changed_files: Sequence[str],
        import_maps: Mapping[str, FileImportMap],
    ) -> dict[str, object]:
        """Return changed files and their transitive dependent files."""
        normalized_maps = {
            path.replace("\\", "/"): import_map
            for path, import_map in import_maps.items()
        }

        dependents: dict[str, set[str]] = {}
        for path, import_map in normalized_maps.items():
            for dependency in import_map.local_dependencies:
                dependency = dependency.replace("\\", "/")
                dependents.setdefault(dependency, set()).add(path)

        changed = {
            path.replace("\\", "/") for path in changed_files
        }
        affected: set[str] = set()
        queue = deque(changed)

        while queue:
            current = queue.popleft()
            for dependent in sorted(dependents.get(current, set())):
                if dependent not in changed and dependent not in affected:
                    affected.add(dependent)
                    queue.append(dependent)

        return {
            "changed_files": sorted(changed),
            "affected_files": sorted(affected),
            "total_affected": len(affected),
        }

    def compute_symbols(
        self,
        direct_symbols: Sequence[Any],
        symbol_edges: Sequence[Any],
        all_symbols_by_id: Mapping[Any, Any],
        file_paths: Mapping[Any, str],
        max_depth: int = 3,
    ) -> tuple[list[Any], list[Any], list[str]]:
        """Compute symbol-level blast radius using SymbolBlastRadiusEngine."""
        try:
            from scanner.symbol_blast_radius import SymbolBlastRadiusEngine
        except ImportError:
            from backend.scanner.symbol_blast_radius import SymbolBlastRadiusEngine

        engine = SymbolBlastRadiusEngine(max_depth=max_depth)
        return engine.compute_symbol_blast_radius(
            direct_symbols=direct_symbols,
            symbol_edges=symbol_edges,
            all_symbols_by_id=all_symbols_by_id,
            file_paths=file_paths,
            max_depth=max_depth,
        )

