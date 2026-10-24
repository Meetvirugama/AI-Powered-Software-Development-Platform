"""Identify repository files affected by changes to other files."""

from collections import deque
from typing import Mapping, Sequence

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
