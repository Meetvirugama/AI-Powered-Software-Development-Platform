"""
Repository Intelligence Builder.
Reference: task.md §3, §4, §10

Synthesizes deterministic AST symbols, import maps, calls, modules, and entry points into
a unified, validated RepositoryIntelligenceSnapshot.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from ai.intelligence.models import (
    EntryPointMetadata,
    FileIntelligenceMetadata,
    GraphEdge,
    GraphNode,
    ModuleMetadata,
    OverviewMetadata,
    RepositoryIntelligenceSnapshot,
)

logger = logging.getLogger(__name__)


class RepositoryIntelligenceBuilder:
    """Builds a complete, deterministic, and validated RepositoryIntelligenceSnapshot."""

    def __init__(
        self,
        repository_id: str | UUID,
        commit_sha: str = "HEAD",
    ) -> None:
        self.repository_id = str(repository_id)
        self.commit_sha = commit_sha or "HEAD"

    def build_snapshot(
        self,
        files: Sequence[Any],
        symbols: Sequence[Any],
        edges: Sequence[Any],
        file_contents: dict[str, str] | None = None,
        overview_override: dict[str, Any] | None = None,
    ) -> RepositoryIntelligenceSnapshot:
        """Construct the complete intelligence snapshot from database records and parsed AST data."""
        contents = file_contents or {}
        now_iso = datetime.now(UTC).isoformat()

        # 1. Process files
        file_id_to_record: dict[str, Any] = {}
        file_id_to_path: dict[str, str] = {}
        file_path_to_id: dict[str, str] = {}
        file_intels: list[FileIntelligenceMetadata] = []
        languages_count: dict[str, int] = defaultdict(int)

        for f in files:
            f_id = str(getattr(f, "id", ""))
            f_path = str(getattr(f, "path", ""))
            f_lang = str(getattr(f, "language", "") or "text").lower()
            file_id_to_record[f_id] = f
            file_id_to_path[f_id] = f_path
            file_path_to_id[f_path] = f_id

            if f_lang and f_lang != "text":
                languages_count[f_lang] += 1

            is_test = bool(
                "test" in f_path.lower()
                or f_path.startswith("tests/")
                or f_path.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts"))
            )

            file_intels.append(
                FileIntelligenceMetadata(
                    id=f_id,
                    path=f_path,
                    language=f_lang,
                    content_hash=str(getattr(f, "content_hash", "")),
                    line_count=int(getattr(f, "line_count", 0) or 0),
                    size_bytes=int(getattr(f, "size_bytes", 0) or 0),
                    summary=self._generate_file_summary(f_path, f_lang, is_test),
                    symbols=[],
                    module_id=self._determine_module_id(f_path),
                    is_test=is_test,
                )
            )

        file_intel_map = {fi.path: fi for fi in file_intels}

        # 2. Process Symbols & Graph Nodes
        symbol_nodes: list[GraphNode] = []
        symbol_id_to_node: dict[str, GraphNode] = {}
        entry_points: list[EntryPointMetadata] = []

        for s in symbols:
            s_id = str(getattr(s, "id", ""))
            s_name = str(getattr(s, "name", ""))
            s_kind = str(getattr(s, "kind", "symbol"))
            s_file_id = str(getattr(s, "file_id", ""))
            s_path = file_id_to_path.get(s_file_id, "")
            s_start = int(getattr(s, "start_line", 1) or 1)
            s_end = int(getattr(s, "end_line", s_start) or s_start)
            s_sig = getattr(s, "signature", None)

            node = GraphNode(
                id=s_id,
                type=s_kind,
                name=s_name,
                file=s_path,
                start_line=s_start,
                end_line=s_end,
                signature=s_sig,
            )
            symbol_nodes.append(node)
            symbol_id_to_node[s_id] = node

            # Attach symbol name to file metadata
            if s_path in file_intel_map and s_name not in file_intel_map[s_path].symbols:
                file_intel_map[s_path].symbols.append(s_name)

            # Check for API route or CLI entry point
            entry = self._detect_entry_point(node, s_sig or "", s_path, contents.get(s_path, ""))
            if entry:
                entry_points.append(entry)
                if s_path in file_intel_map:
                    file_intel_map[s_path].is_entry_point = True

        # 3. Process Graph Edges
        graph_edges: list[GraphEdge] = []
        seen_edges: set[tuple[str, str, str]] = set()

        for e in edges:
            src_id = str(getattr(e, "source_symbol_id", getattr(e, "source_id", getattr(e, "source", ""))))
            tgt_id = str(getattr(e, "target_symbol_id", getattr(e, "target_id", getattr(e, "target", ""))))
            e_type = str(getattr(e, "edge_type", getattr(e, "type", "calls"))).lower()
            if e_type not in ("calls", "imports", "extends", "implements", "tests", "uses"):
                e_type = "calls"

            # Validate that edge points between recognized nodes (or symbol names)
            if (src_id, tgt_id, e_type) not in seen_edges:
                seen_edges.add((src_id, tgt_id, e_type))
                graph_edges.append(
                    GraphEdge(
                        source=src_id,
                        target=tgt_id,
                        type=e_type,  # type: ignore[arg-type]
                        confidence=1.0,
                    )
                )

        # 4. Cluster Modules
        modules = self._cluster_modules(file_intels, symbol_nodes)

        # 5. Build Architectural Overview
        primary_lang = max(languages_count.items(), key=lambda kv: kv[1])[0] if languages_count else "python"
        frameworks = self._detect_frameworks(file_intels, contents)

        overview = OverviewMetadata(
            project_type="AI Software Development Platform",
            languages=sorted(languages_count.keys()),
            frameworks=frameworks,
            architecture="Modular Architecture",
            summary=f"Repository containing {len(file_intels)} files and {len(symbol_nodes)} symbols across {len(modules)} logical modules.",
            total_files=len(file_intels),
            total_symbols=len(symbol_nodes),
            primary_language=primary_lang,
        )
        if overview_override:
            for k, v in overview_override.items():
                if hasattr(overview, k):
                    setattr(overview, k, v)

        return RepositoryIntelligenceSnapshot(
            schema_version="1.0",
            repository_id=self.repository_id,
            commit_sha=self.commit_sha,
            generated_at=now_iso,
            overview=overview,
            modules=modules,
            files=file_intels,
            nodes=symbol_nodes,
            edges=graph_edges,
            entry_points=entry_points,
            metadata={
                "builder_version": "1.0",
                "graph_valid": len(symbol_nodes) > 0,
            },
        )

    def _determine_module_id(self, path: str) -> str:
        parts = PurePosixPath(path).parts
        if not parts:
            return "root"
        if len(parts) >= 2 and parts[0] in ("backend", "frontend", "src", "app"):
            return f"{parts[0]}_{parts[1]}"
        return parts[0]

    def _generate_file_summary(self, path: str, language: str, is_test: bool) -> str:
        base = PurePosixPath(path).name
        if is_test:
            return f"Automated test suite verifying {base.replace('test_', '').replace('.test', '')}"
        if "api" in path or "routes" in path:
            return f"API endpoints and route definitions for {base}"
        if "service" in path:
            return f"Business logic and application service orchestrator ({base})"
        if "model" in path:
            return f"Database schema and data models ({base})"
        if "schema" in path:
            return f"Data validation schemas and DTOs ({base})"
        return f"{language.capitalize()} module: {base}"

    def _detect_entry_point(
        self,
        node: GraphNode,
        signature: str,
        path: str,
        content: str,
    ) -> EntryPointMetadata | None:
        """Detect API routes, worker entrypoints, and main runners."""
        node_name = node.name.lower()

        # FastAPI / Flask decorator
        route_match = re.search(r'@(?:router|app)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', content)
        if route_match:
            method, route = route_match.groups()
            return EntryPointMetadata(
                id=f"entry_{node.id}",
                path=path,
                symbol=node.name,
                entry_type="api_route",
                method=method.upper(),
                route_path=route,
                framework="fastapi",
            )

        if node_name in ("main", "run", "start") or path.endswith(("main.py", "index.ts")):
            return EntryPointMetadata(
                id=f"entry_{node.id}",
                path=path,
                symbol=node.name,
                entry_type="main_script",
                framework=None,
            )

        return None

    def _cluster_modules(
        self,
        files: list[FileIntelligenceMetadata],
        nodes: list[GraphNode],
    ) -> list[ModuleMetadata]:
        """Group files into coherent architectural modules."""
        module_groups: dict[str, list[FileIntelligenceMetadata]] = defaultdict(list)
        for f in files:
            module_groups[f.module_id or "root"].append(f)

        file_to_node_count: dict[str, int] = defaultdict(int)
        for n in nodes:
            file_to_node_count[n.file] += 1

        modules: list[ModuleMetadata] = []
        for mod_id, mod_files in sorted(module_groups.items(), key=lambda kv: kv[0]):
            common_path = mod_id.replace("_", "/")
            total_symbols = sum(file_to_node_count[f.path] for f in mod_files)
            file_paths = [f.path for f in mod_files]

            responsibility = f"Architectural subsystem managing {mod_id.replace('_', ' ')} components."
            if "api" in mod_id:
                responsibility = "REST API routers, schema serialization, and client endpoints."
            elif "service" in mod_id:
                responsibility = "Core domain logic and service orchestration."
            elif "indexer" in mod_id or "scanner" in mod_id:
                responsibility = "Repository AST parsing, symbol extraction, and indexing engine."
            elif "frontend" in mod_id:
                responsibility = "User interface layouts, state management, and interactive studios."

            modules.append(
                ModuleMetadata(
                    id=mod_id,
                    name=mod_id.replace("_", " ").title(),
                    path=common_path,
                    responsibility=responsibility,
                    files_count=len(mod_files),
                    symbols_count=total_symbols,
                    files=file_paths,
                )
            )

        return modules

    def _detect_frameworks(
        self,
        files: list[FileIntelligenceMetadata],
        contents: dict[str, str],
    ) -> list[str]:
        frameworks: set[str] = set()
        for f in files:
            p = f.path.lower()
            if "fastapi" in p or "app/main.py" in p:
                frameworks.add("FastAPI")
            if "react" in p or p.endswith((".tsx", ".jsx")):
                frameworks.add("React")
            if "vite.config" in p:
                frameworks.add("Vite")
            if "sqlalchemy" in p:
                frameworks.add("SQLAlchemy")
            if "tailwind" in p:
                frameworks.add("TailwindCSS")
            if "pytest" in p or p.startswith("tests/"):
                frameworks.add("pytest")
        return sorted(frameworks)

