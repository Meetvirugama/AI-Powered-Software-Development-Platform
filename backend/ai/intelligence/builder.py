"""
Repository Intelligence Builder.
Reference: task.md §3, §4, §10 & Issue 1 (PageRank F05-C3 + Co-Change Coupling)

Synthesizes deterministic AST symbols, import maps, calls, PageRank importance scores,
Git co-change coupling, modules, and entry points into a unified, validated
RepositoryIntelligenceSnapshot.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
import logging
from pathlib import Path, PurePosixPath
import re
from typing import Any
from uuid import UUID

from ai.intelligence.co_change import GitCoChangeMiner
from ai.intelligence.models import (
    CoChangeEdge,
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
        *,
        co_change_miner: GitCoChangeMiner | None = None,
    ) -> None:
        self.repository_id = str(repository_id)
        self.commit_sha = commit_sha or "HEAD"
        self.co_change_miner = co_change_miner or GitCoChangeMiner()

    def build_snapshot(
        self,
        files: Sequence[Any],
        symbols: Sequence[Any],
        edges: Sequence[Any],
        file_contents: dict[str, str] | None = None,
        overview_override: dict[str, Any] | None = None,
        *,
        repo_root: str | Path | None = None,
        commit_history: Sequence[Any] | None = None,
        co_change_edges: Sequence[CoChangeEdge] | None = None,
    ) -> RepositoryIntelligenceSnapshot:
        """Construct the complete intelligence snapshot from database records, AST data, PageRank, and Git co-change history."""
        contents = file_contents or {}
        now_iso = datetime.now(UTC).isoformat()

        # 1. Process files
        file_id_to_path: dict[str, str] = {}
        file_intels: list[FileIntelligenceMetadata] = []
        languages_count: dict[str, int] = defaultdict(int)

        for f in files:
            f_id = str(getattr(f, "id", ""))
            f_path = str(getattr(f, "path", "")).replace("\\", "/")
            f_lang = str(getattr(f, "language", "") or "text").lower()
            file_id_to_path[f_id] = f_path

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
        entry_points: list[EntryPointMetadata] = []

        for s in symbols:
            s_id = str(getattr(s, "id", ""))
            s_name = str(getattr(s, "name", ""))
            s_kind = str(getattr(s, "kind", "symbol"))
            s_file_id = str(getattr(s, "file_id", ""))
            s_path = (
                str(getattr(s, "file_path", "") or "").replace("\\", "/")
                or file_id_to_path.get(s_file_id, "")
            )
            s_start = int(getattr(s, "start_line", 1) or 1)
            s_end = int(getattr(s, "end_line", s_start) or s_start)
            s_sig = getattr(s, "signature", None)
            s_imp = float(getattr(s, "importance_score", 0.0) or 0.0)

            node = GraphNode(
                id=s_id,
                type=s_kind,
                name=s_name,
                file=s_path,
                start_line=s_start,
                end_line=s_end,
                signature=s_sig,
                importance_score=s_imp,
            )
            symbol_nodes.append(node)

            if s_path in file_intel_map and s_name not in file_intel_map[s_path].symbols:
                file_intel_map[s_path].symbols.append(s_name)

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
            raw_tgt = getattr(e, "target_symbol_id", getattr(e, "target_id", getattr(e, "target", None)))
            tgt_id = str(raw_tgt) if raw_tgt is not None else str(getattr(e, "target_name", "") or "")
            if not src_id or not tgt_id:
                continue
            e_type = str(getattr(e, "edge_type", getattr(e, "type", "calls"))).lower()
            if e_type == "inherits":
                e_type = "extends"
            if e_type not in ("calls", "imports", "extends", "implements", "tests", "uses"):
                e_type = "calls"

            if (src_id, tgt_id, e_type) not in seen_edges:
                seen_edges.add((src_id, tgt_id, e_type))
                graph_edges.append(
                    GraphEdge(
                        source=src_id,
                        target=tgt_id,
                        type=e_type,  # type: ignore[arg-type]
                        confidence=float(getattr(e, "confidence", 1.0) or 1.0),
                        provenance=str(getattr(e, "provenance", "tree_sitter") or "tree_sitter"),
                        resolution_status=str(getattr(e, "resolution_status", "resolved") or "resolved"),
                        weight=float(getattr(e, "weight", 1.0) or 1.0),
                    )
                )

        # 3b. Compute PageRank importance (F05-C3) on symbol nodes when not pre-populated
        self._compute_and_propagate_importance(symbol_nodes, graph_edges, file_intels)

        # 3c. Mine or attach Git Co-Change Coupling edges
        resolved_co_changes: list[CoChangeEdge] = []
        if co_change_edges is not None:
            resolved_co_changes = list(co_change_edges)
        elif commit_history is not None or repo_root is not None:
            known_paths = [fi.path for fi in file_intels if fi.path]
            resolved_co_changes = self.co_change_miner.mine_co_changes(
                repo_root=repo_root,
                commit_history=commit_history,
                known_files=known_paths if known_paths else None,
            )

        # 4. Cluster Modules (propagating file importance into module importance)
        modules = self._cluster_modules(file_intels, symbol_nodes)

        # 5. Rank top important non-test files
        ranked_files = sorted(
            [fi for fi in file_intels if not fi.is_test],
            key=lambda fi: (fi.importance_score, len(fi.symbols)),
            reverse=True,
        )
        top_important_files = [fi.path for fi in ranked_files[:10] if fi.path]

        # 6. Build Architectural Overview
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
            schema_version="1.1",
            repository_id=self.repository_id,
            commit_sha=self.commit_sha,
            generated_at=now_iso,
            overview=overview,
            modules=modules,
            files=file_intels,
            nodes=symbol_nodes,
            edges=graph_edges,
            co_change_edges=resolved_co_changes,
            top_important_files=top_important_files,
            entry_points=entry_points,
            metadata={
                "builder_version": "1.1",
                "graph_valid": len(symbol_nodes) > 0,
                "pagerank_computed": True,
                "co_change_count": len(resolved_co_changes),
            },
        )

    def _compute_and_propagate_importance(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        files: list[FileIntelligenceMetadata],
    ) -> None:
        """
        Ensure every GraphNode and FileIntelligenceMetadata carries a normalized PageRank
        importance score in [0.0, 1.0] (F05-C3).
        """
        if not nodes and not files:
            return

        # If symbol nodes do not yet have PageRank scores, compute weighted PageRank over nodes & edges
        if nodes and all(n.importance_score <= 0.0 for n in nodes):
            node_ids = [n.id for n in nodes if n.id]
            name_to_id = {n.name: n.id for n in nodes if n.name and n.id}
            id_set = set(node_ids)
            n_count = len(node_ids)

            if n_count == 1:
                nodes[0].importance_score = 1.0
            elif n_count > 1:
                damping = 0.85
                edge_type_weights = {
                    "calls": 1.0,
                    "inherits": 1.2,
                    "extends": 1.2,
                    "implements": 1.1,
                    "imports": 0.6,
                    "uses": 0.8,
                    "tests": 0.3,
                }
                outgoing: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
                for e in edges:
                    if e.resolution_status == "unresolved":
                        continue
                    src = e.source if e.source in id_set else name_to_id.get(e.source, "")
                    tgt = e.target if e.target in id_set else name_to_id.get(e.target, "")
                    if src and tgt and src != tgt:
                        w = float(e.weight or 1.0) * edge_type_weights.get(e.type, 1.0) * float(e.confidence or 1.0)
                        outgoing[src][tgt] += w

                scores = {nid: 1.0 / n_count for nid in node_ids}
                out_totals = {nid: sum(outgoing[nid].values()) for nid in node_ids}

                for _ in range(25):
                    dangling_mass = sum(scores[nid] for nid in node_ids if out_totals[nid] <= 0.0)
                    base_rank = (1.0 - damping) / n_count + (damping * dangling_mass / n_count)
                    new_scores = {nid: base_rank for nid in node_ids}
                    for src_id, targets in outgoing.items():
                        total_w = out_totals[src_id]
                        if total_w > 0.0:
                            src_share = damping * scores[src_id] / total_w
                            for tgt_id, w in targets.items():
                                new_scores[tgt_id] += src_share * w
                    diff = sum(abs(new_scores[nid] - scores[nid]) for nid in node_ids)
                    scores = new_scores
                    if diff < 1e-6:
                        break

                max_s = max(scores.values(), default=0.0)
                for node in nodes:
                    raw_s = scores.get(node.id, 0.0)
                    raw_norm = (raw_s / max_s) if max_s > 0.0 else 0.0
                    # Apply vendor/test discount
                    f_lower = (node.file or "").lower()
                    if any(seg in f_lower for seg in ("vendor/", "node_modules/", "dist/", "generated/")):
                        raw_norm *= 0.25
                    elif "test" in f_lower:
                        raw_norm *= 0.65
                    node.importance_score = round(min(1.0, max(0.0, raw_norm)), 4)

        # Propagate symbol importance to files (combining max symbol score + mean symbol score + entry-point bonus)
        scores_by_file: dict[str, list[float]] = defaultdict(list)
        for n in nodes:
            if n.file:
                scores_by_file[n.file].append(float(n.importance_score or 0.0))

        raw_file_scores: dict[str, float] = {}
        for fi in files:
            f_scores = scores_by_file.get(fi.path, [])
            if f_scores:
                max_sym = max(f_scores)
                avg_sym = sum(f_scores) / len(f_scores)
                combined = 0.7 * max_sym + 0.3 * avg_sym
            else:
                combined = 0.1 if not fi.is_test else 0.05
            if fi.is_entry_point:
                combined = min(1.0, combined + 0.15)
            if fi.is_test:
                combined *= 0.65
            raw_file_scores[fi.path] = combined

        max_file_score = max(raw_file_scores.values(), default=0.0)
        for fi in files:
            norm_f = (raw_file_scores.get(fi.path, 0.0) / max_file_score) if max_file_score > 0.0 else 0.0
            fi.importance_score = round(min(1.0, max(0.0, norm_f)), 4)

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

        search_body = f"{signature}\n{content}" if signature else content
        route_match = re.search(r'@(?:router|app)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', search_body)
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
            mod_importance = (
                round(max((f.importance_score for f in mod_files), default=0.0), 4)
            )

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
                    importance_score=mod_importance,
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
