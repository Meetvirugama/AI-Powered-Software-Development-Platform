"""Dependency graph builder with provenance, resolution status, and duplicate reconciliation.

Owner: Prit — Repository Engine Lead (W1-21)
Modernized for P2: Edge provenance, resolution status (resolved / ambiguous / unresolved),
consistent edge direction (source_id = caller/importer/subclass -> target_id = callee/imported/superclass),
unresolved reference preservation, and multi-provider provenance reconciliation.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from .import_tracker import FileImportMap
from .symbols import EDGE_TYPE_DEFAULT_WEIGHTS, Symbol, SymbolEdge

logger = logging.getLogger(__name__)

_RESOLUTION_PRIORITY: dict[str, int] = {
    "resolved": 3,
    "ambiguous": 2,
    "unresolved": 1,
}

_IGNORED_CALL_KEYWORDS: set[str] = {
    "if", "for", "while", "switch", "catch", "return", "sizeof", "typeof",
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict",
    "set", "tuple", "super", "isinstance", "getattr", "setattr", "hasattr",
    "min", "max", "sum", " abs", "sorted", "enumerate", "zip", "map", "filter",
    "open", "Exception", "ValueError", "TypeError", "RuntimeError", "KeyError",
}


def merge_provenance(existing: str, incoming: str) -> str:
    """Combine provenance labels deterministically without duplicates.

    Example: merge_provenance('tree_sitter', 'scip') -> 'scip,tree_sitter'
    """
    parts = {
        p.strip()
        for raw in (existing, incoming)
        for p in (raw or "").split(",")
        if p.strip()
    }
    if not parts:
        return "tree_sitter"
    return ",".join(sorted(parts))


class DependencyGraphBuilder:
    """Resolves symbols across a repository and builds a directed graph of SymbolEdges.

    Supports both:
      1. `DependencyGraphBuilder(symbols, file_contents=..., file_paths=..., import_maps=...).build()`
      2. `DependencyGraphBuilder().build(symbols=..., file_contents=..., import_maps=...)`

    Edge direction convention (strictly enforced across all providers):
      - `calls`:      source_id = caller symbol      -> target_id = callee symbol
      - `imports`:    source_id = importing symbol   -> target_id = imported symbol
      - `extends` / `inherits`: source_id = subclass -> target_id = superclass
      - `implements`: source_id = implementing class -> target_id = interface/trait symbol

    Resolution status convention:
      - `resolved`:   Unambiguously matched to a single target symbol in the repository
                      (via same-file definition, explicit import map, or unique repository-wide match).
      - `ambiguous`:  Multiple candidate symbols share the name across the repository and neither
                      same-file scope nor import tracking disambiguates them. `target_id` is left
                      `None` (never arbitrarily assigned) and `candidate_target_ids` records the
                      candidate UUIDs.
      - `unresolved`: Reference targets an external library, built-in, or unindexed symbol.
                      `target_id` is `None` and `target_name` preserves the raw reference name.
    """

    def __init__(
        self,
        symbols: Sequence[Symbol] | None = None,
        file_contents: dict[UUID, str] | None = None,
        *,
        file_paths: dict[UUID, str] | None = None,
        import_maps: dict[str, FileImportMap] | None = None,
        include_unresolved: bool = False,
        include_ambiguous: bool = False,
    ) -> None:
        self.symbols: list[Symbol] = list(symbols or [])
        self.file_contents: dict[UUID, str] = dict(file_contents or {})
        self.file_paths: dict[UUID, str] = dict(file_paths or {})
        self.import_maps: dict[str, FileImportMap] = dict(import_maps or {})
        self.include_unresolved = include_unresolved
        self.include_ambiguous = include_ambiguous

        self.symbols_by_name: dict[str, list[Symbol]] = defaultdict(list)
        for s in self.symbols:
            self.symbols_by_name[s.name].append(s)

        self._last_all_edges: list[SymbolEdge] = []
        self._last_unresolved_edges: list[SymbolEdge] = []

    @property
    def all_edges(self) -> list[SymbolEdge]:
        """All edges from the most recent `build()` call, including unresolved and ambiguous."""
        return list(self._last_all_edges)

    @property
    def unresolved_edges(self) -> list[SymbolEdge]:
        """Unresolved and ambiguous edges from the most recent `build()` call."""
        return list(self._last_unresolved_edges)

    def build(
        self,
        symbols: Sequence[Symbol] | None = None,
        *,
        file_contents: dict[UUID, str] | None = None,
        file_paths: dict[UUID, str] | None = None,
        import_maps: dict[str, FileImportMap] | None = None,
        include_unresolved: bool | None = None,
        include_ambiguous: bool | None = None,
        external_edges: Sequence[SymbolEdge] | None = None,
    ) -> list[SymbolEdge]:
        """Build SymbolEdges for the repository symbols.

        By default (`include_unresolved=False`, `include_ambiguous=False`), returns resolved
        symbol-to-symbol edges while retaining all unresolved and ambiguous references in
        `self.unresolved_edges` and `self.all_edges`.
        """
        active_symbols = list(symbols) if symbols is not None else self.symbols
        active_contents = file_contents if file_contents is not None else self.file_contents
        active_paths = file_paths if file_paths is not None else self.file_paths
        active_imports = import_maps if import_maps is not None else self.import_maps
        keep_unresolved = (
            self.include_unresolved if include_unresolved is None else include_unresolved
        )
        keep_ambiguous = (
            self.include_ambiguous if include_ambiguous is None else include_ambiguous
        )

        symbols_by_name: dict[str, list[Symbol]] = defaultdict(list)
        symbols_by_file_id: dict[UUID, list[Symbol]] = defaultdict(list)
        symbols_by_path: dict[str, list[Symbol]] = defaultdict(list)

        for s in active_symbols:
            symbols_by_name[s.name].append(s)
            if s.file_id:
                symbols_by_file_id[s.file_id].append(s)
            sym_path = self._get_symbol_path(s, active_paths)
            if sym_path:
                symbols_by_path[sym_path].append(s)

        raw_edges: list[SymbolEdge] = []

        # 1. File-level ImportTracker maps (when provided)
        for norm_file_path, imp_map in active_imports.items():
            clean_path = self._norm_path(norm_file_path)
            file_syms = symbols_by_path.get(clean_path, [])
            anchor_sym = next(
                (s for s in file_syms if s.kind == "import"),
                file_syms[0] if file_syms else None,
            )
            if anchor_sym is None:
                continue
            for imp in imp_map.imports:
                target_name = imp.name if imp.name != "*" else imp.module
                if not target_name:
                    continue
                if imp.resolved_path:
                    res_path = self._norm_path(imp.resolved_path)
                    target_file_syms = symbols_by_path.get(res_path, [])
                    exact = [
                        ts
                        for ts in target_file_syms
                        if ts.name == imp.name and ts.id != anchor_sym.id and ts.kind != "import"
                    ]
                    if len(exact) == 1:
                        raw_edges.append(
                            SymbolEdge(
                                source_id=anchor_sym.id,
                                target_id=exact[0].id,
                                edge_type="imports",
                                target_name=target_name,
                                provenance="import_tracker",
                                resolution_status="resolved",
                                confidence=1.0,
                                weight=EDGE_TYPE_DEFAULT_WEIGHTS["imports"],
                            )
                        )
                        continue
                edge = self._resolve_reference(
                    source_sym=anchor_sym,
                    target_name=target_name,
                    edge_type="imports",
                    symbols_by_name=symbols_by_name,
                    symbols_by_path=symbols_by_path,
                    active_paths=active_paths,
                    file_import_map=imp_map,
                    provenance="import_tracker",
                    allowed_kinds=None,
                )
                if edge is not None:
                    raw_edges.append(edge)

        # 2. Symbol-level edges (`import`, `class`/`interface`, `function`/`method`)
        for sym in active_symbols:
            sym_path = self._get_symbol_path(sym, active_paths)
            file_imp_map = active_imports.get(sym_path) if sym_path else None

            if sym.kind == "import":
                raw_edges.extend(
                    self._extract_import_edges(
                        sym,
                        symbols_by_name=symbols_by_name,
                        symbols_by_path=symbols_by_path,
                        active_paths=active_paths,
                        file_import_map=file_imp_map,
                    )
                )
            elif sym.kind in ("class", "interface", "struct"):
                raw_edges.extend(
                    self._extract_inheritance_edges(
                        sym,
                        symbols_by_name=symbols_by_name,
                        symbols_by_path=symbols_by_path,
                        active_paths=active_paths,
                        file_import_map=file_imp_map,
                    )
                )
            elif sym.kind in ("function", "method"):
                raw_edges.extend(
                    self._extract_call_edges(
                        sym,
                        active_contents=active_contents,
                        symbols_by_name=symbols_by_name,
                        symbols_by_path=symbols_by_path,
                        active_paths=active_paths,
                        file_import_map=file_imp_map,
                    )
                )

        if external_edges:
            raw_edges.extend(external_edges)

        reconciled = self.reconcile_edges(raw_edges)
        self._last_all_edges = reconciled
        self._last_unresolved_edges = [
            e for e in reconciled if e.resolution_status in ("unresolved", "ambiguous")
        ]

        filtered: list[SymbolEdge] = []
        for edge in reconciled:
            if edge.resolution_status == "resolved" and edge.target_id is not None:
                filtered.append(edge)
            elif edge.resolution_status == "ambiguous" and keep_ambiguous:
                filtered.append(edge)
            elif edge.resolution_status == "unresolved" and keep_unresolved:
                filtered.append(edge)

        return filtered

    def build_with_unresolved(
        self,
        symbols: Sequence[Symbol] | None = None,
        *,
        file_contents: dict[UUID, str] | None = None,
        file_paths: dict[UUID, str] | None = None,
        import_maps: dict[str, FileImportMap] | None = None,
        external_edges: Sequence[SymbolEdge] | None = None,
    ) -> list[SymbolEdge]:
        """Build and return all edges including resolved, ambiguous, and unresolved references."""
        return self.build(
            symbols=symbols,
            file_contents=file_contents,
            file_paths=file_paths,
            import_maps=import_maps,
            include_unresolved=True,
            include_ambiguous=True,
            external_edges=external_edges,
        )

    @staticmethod
    def reconcile_edges(edges: Sequence[SymbolEdge]) -> list[SymbolEdge]:
        """Deduplicate edges while preserving multi-provider provenance and highest confidence.

        - Resolved edges with the same `(source_id, target_id, edge_type)` are merged into a
          single edge whose `provenance` combines all contributing providers (e.g.
          `import_tracker,tree_sitter` or `scip,tree_sitter`) and whose `confidence` / `weight`
          take the maximum observed values.
        - Unresolved/ambiguous edges with the same `(source_id, target_name, edge_type)` are
          automatically upgraded if a resolved edge for `(source_id, target_name, edge_type)`
          is present from another provider (e.g. SCIP or ImportTracker).
        """
        resolved_by_key: dict[tuple[UUID, UUID, str], SymbolEdge] = {}
        resolved_by_name: dict[tuple[UUID, str, str], tuple[UUID, UUID, str]] = {}
        unresolved_by_name: dict[tuple[UUID, str, str], SymbolEdge] = {}

        for edge in edges:
            if edge.target_id is not None and edge.resolution_status == "resolved":
                if edge.source_id == edge.target_id:
                    continue
                key = (edge.source_id, edge.target_id, edge.edge_type)
                existing = resolved_by_key.get(key)
                if existing is None:
                    cloned = SymbolEdge(
                        source_id=edge.source_id,
                        target_id=edge.target_id,
                        edge_type=edge.edge_type,
                        target_name=edge.target_name,
                        provenance=edge.provenance,
                        resolution_status="resolved",
                        confidence=edge.confidence,
                        weight=edge.weight,
                        candidate_target_ids=edge.candidate_target_ids,
                    )
                    resolved_by_key[key] = cloned
                    if edge.target_name:
                        resolved_by_name[(edge.source_id, edge.target_name, edge.edge_type)] = key
                else:
                    existing.provenance = merge_provenance(existing.provenance, edge.provenance)
                    existing.confidence = max(existing.confidence, edge.confidence)
                    existing.weight = max(existing.weight, edge.weight)
                    if not existing.target_name and edge.target_name:
                        existing.target_name = edge.target_name
                        resolved_by_name[(edge.source_id, edge.target_name, edge.edge_type)] = key

        for edge in edges:
            if edge.target_id is not None and edge.resolution_status == "resolved":
                continue
            tname = edge.target_name or ""
            name_key = (edge.source_id, tname, edge.edge_type)
            if name_key in resolved_by_name:
                res_key = resolved_by_name[name_key]
                res_edge = resolved_by_key[res_key]
                res_edge.provenance = merge_provenance(res_edge.provenance, edge.provenance)
                continue

            existing_unres = unresolved_by_name.get(name_key)
            if existing_unres is None:
                unresolved_by_name[name_key] = SymbolEdge(
                    source_id=edge.source_id,
                    target_id=None,
                    edge_type=edge.edge_type,
                    target_name=tname or None,
                    provenance=edge.provenance,
                    resolution_status=edge.resolution_status,
                    confidence=edge.confidence,
                    weight=edge.weight,
                    candidate_target_ids=edge.candidate_target_ids,
                )
            else:
                existing_unres.provenance = merge_provenance(
                    existing_unres.provenance, edge.provenance
                )
                if (
                    _RESOLUTION_PRIORITY.get(str(edge.resolution_status), 0)
                    > _RESOLUTION_PRIORITY.get(str(existing_unres.resolution_status), 0)
                ):
                    existing_unres.resolution_status = edge.resolution_status
                existing_unres.confidence = max(existing_unres.confidence, edge.confidence)
                existing_unres.weight = max(existing_unres.weight, edge.weight)
                if edge.candidate_target_ids:
                    merged_cands = tuple(
                        dict.fromkeys(
                            list(existing_unres.candidate_target_ids)
                            + list(edge.candidate_target_ids)
                        )
                    )
                    existing_unres.candidate_target_ids = merged_cands

        return list(resolved_by_key.values()) + list(unresolved_by_name.values())

    def _extract_import_edges(
        self,
        sym: Symbol,
        *,
        symbols_by_name: dict[str, list[Symbol]],
        symbols_by_path: dict[str, list[Symbol]],
        active_paths: dict[UUID, str],
        file_import_map: FileImportMap | None,
    ) -> list[SymbolEdge]:
        edges: list[SymbolEdge] = []
        sig = sym.signature or ""
        if not sig:
            return edges

        ignored_kw = {
            "import", "from", "as", "const", "let", "var", "require", "type",
            "use", "pub", "crate", "self", "super", "mod", "include", "static", "package",
        }

        # Extract imported symbol identifiers
        words = re.findall(r"[a-zA-Z_]\w*", sig)
        # In `from pkg.helpers import BaseHelper, compute_checksum`, skip module path words if `import` keyword is present
        if "from " in sig and " import " in sig:
            after_import = sig.split(" import ", 1)[1]
            candidate_words = [
                w.strip().split(" as ")[0].strip()
                for w in re.findall(r"[a-zA-Z_]\w*", after_import)
                if w not in ignored_kw
            ]
        else:
            candidate_words = [w for w in words if w not in ignored_kw]

        seen_words: set[str] = set()
        for word in candidate_words:
            if not word or word in seen_words:
                continue
            seen_words.add(word)
            edge = self._resolve_reference(
                source_sym=sym,
                target_name=word,
                edge_type="imports",
                symbols_by_name=symbols_by_name,
                symbols_by_path=symbols_by_path,
                active_paths=active_paths,
                file_import_map=file_import_map,
                provenance="tree_sitter",
                allowed_kinds=None,
            )
            if edge is not None:
                edges.append(edge)

        strings = re.findall(r'["\']([^"\']+)["\']', sig)
        for s in strings:
            basename = s.split("/")[-1]
            for lookup in (s, basename):
                if lookup and lookup in symbols_by_name and lookup not in seen_words:
                    seen_words.add(lookup)
                    edge = self._resolve_reference(
                        source_sym=sym,
                        target_name=lookup,
                        edge_type="imports",
                        symbols_by_name=symbols_by_name,
                        symbols_by_path=symbols_by_path,
                        active_paths=active_paths,
                        file_import_map=file_import_map,
                        provenance="tree_sitter",
                        allowed_kinds=None,
                    )
                    if edge is not None:
                        edges.append(edge)

        return edges

    def _extract_inheritance_edges(
        self,
        sym: Symbol,
        *,
        symbols_by_name: dict[str, list[Symbol]],
        symbols_by_path: dict[str, list[Symbol]],
        active_paths: dict[UUID, str],
        file_import_map: FileImportMap | None,
    ) -> list[SymbolEdge]:
        edges: list[SymbolEdge] = []
        sig = sym.signature or ""
        if not sig:
            return edges

        # 1. `extends Base`
        extends_match = re.search(r"\bextends\s+([a-zA-Z_]\w*)", sig)
        if extends_match:
            target_name = extends_match.group(1)
            edge = self._resolve_reference(
                source_sym=sym,
                target_name=target_name,
                edge_type="extends",
                symbols_by_name=symbols_by_name,
                symbols_by_path=symbols_by_path,
                active_paths=active_paths,
                file_import_map=file_import_map,
                provenance="tree_sitter",
                allowed_kinds={"class", "interface", "struct"},
            )
            if edge is not None:
                edges.append(edge)

        # 2. Python `class Sub(Base1, Base2):`
        py_match = re.search(r"class\s+\w+\s*\(([^)]+)\)", sig)
        if py_match:
            for raw_parent in py_match.group(1).split(","):
                target_name = self._clean_type_name(raw_parent)
                if target_name and target_name not in ("object", "ABC", "Enum", "BaseModel"):
                    edge = self._resolve_reference(
                        source_sym=sym,
                        target_name=target_name,
                        edge_type="extends",
                        symbols_by_name=symbols_by_name,
                        symbols_by_path=symbols_by_path,
                        active_paths=active_paths,
                        file_import_map=file_import_map,
                        provenance="tree_sitter",
                        allowed_kinds={"class", "interface", "struct"},
                    )
                    if edge is not None:
                        edges.append(edge)

        # 3. C++ `class Sub : public Base`
        cpp_match = re.search(r"(?:class|struct)\s+\w+\s*:\s*([^{]+)", sig)
        if cpp_match:
            for raw_parent in cpp_match.group(1).split(","):
                target_name = self._clean_type_name(raw_parent)
                if target_name and target_name != sym.name:
                    edge = self._resolve_reference(
                        source_sym=sym,
                        target_name=target_name,
                        edge_type="extends",
                        symbols_by_name=symbols_by_name,
                        symbols_by_path=symbols_by_path,
                        active_paths=active_paths,
                        file_import_map=file_import_map,
                        provenance="tree_sitter",
                        allowed_kinds={"class", "interface", "struct"},
                    )
                    if edge is not None:
                        edges.append(edge)

        # 4. `implements Iface1, Iface2`
        implements_match = re.search(
            r"\bimplements\s+([a-zA-Z_]\w*(?:\s*,\s*[a-zA-Z_]\w*)*)", sig
        )
        if implements_match:
            targets_str = implements_match.group(1)
            for raw_t in targets_str.split(","):
                target_name = self._clean_type_name(raw_t)
                if target_name:
                    edge = self._resolve_reference(
                        source_sym=sym,
                        target_name=target_name,
                        edge_type="implements",
                        symbols_by_name=symbols_by_name,
                        symbols_by_path=symbols_by_path,
                        active_paths=active_paths,
                        file_import_map=file_import_map,
                        provenance="tree_sitter",
                        allowed_kinds={"interface", "class", "struct"},
                    )
                    if edge is not None:
                        edges.append(edge)

        return edges

    def _extract_call_edges(
        self,
        sym: Symbol,
        *,
        active_contents: dict[UUID, str],
        symbols_by_name: dict[str, list[Symbol]],
        symbols_by_path: dict[str, list[Symbol]],
        active_paths: dict[UUID, str],
        file_import_map: FileImportMap | None,
    ) -> list[SymbolEdge]:
        edges: list[SymbolEdge] = []
        body_text = ""
        if sym.file_id and sym.file_id in active_contents:
            lines = active_contents[sym.file_id].splitlines()
            start_idx = max(0, (sym.start_line or 1) - 1)
            end_idx = min(len(lines), sym.end_line or len(lines))
            body_text = "\n".join(lines[start_idx:end_idx])
        if not body_text:
            body_text = sym.signature or ""

        call_names: set[str] = set(sym.calls or [])
        if body_text:
            # Strip the function/method declaration header on the first line so its own name isn't treated as a call
            body_lines = body_text.splitlines()
            scan_text = "\n".join(body_lines[1:]) if len(body_lines) > 1 else body_text
            for m in re.finditer(r"\b([a-zA-Z_]\w*)\s*\(", scan_text):
                callee = m.group(1)
                if callee != sym.name and callee not in _IGNORED_CALL_KEYWORDS:
                    call_names.add(callee)

        for raw_callee in sorted(call_names):
            callee = self._normalize_call_name(raw_callee)
            if not callee or callee == sym.name or callee in _IGNORED_CALL_KEYWORDS:
                continue
            edge = self._resolve_reference(
                source_sym=sym,
                target_name=callee,
                edge_type="calls",
                symbols_by_name=symbols_by_name,
                symbols_by_path=symbols_by_path,
                active_paths=active_paths,
                file_import_map=file_import_map,
                provenance="tree_sitter",
                allowed_kinds={"function", "method", "class", "struct"},
            )
            if edge is not None:
                edges.append(edge)

        return edges

    def _resolve_reference(
        self,
        *,
        source_sym: Symbol,
        target_name: str,
        edge_type: str,
        symbols_by_name: dict[str, list[Symbol]],
        symbols_by_path: dict[str, list[Symbol]],
        active_paths: dict[UUID, str],
        file_import_map: FileImportMap | None,
        provenance: str,
        allowed_kinds: set[str] | None,
    ) -> SymbolEdge | None:
        default_weight = EDGE_TYPE_DEFAULT_WEIGHTS.get(edge_type, 1.0)
        lookup_name = target_name
        imported_entry = None

        if file_import_map is not None and target_name in file_import_map.by_name:
            imported_entry = file_import_map.by_name[target_name]
            if imported_entry.name and imported_entry.name != "*":
                lookup_name = imported_entry.name

        candidates = [
            c
            for c in symbols_by_name.get(lookup_name, [])
            if c.id != source_sym.id
            and c.kind != "import"
            and (allowed_kinds is None or c.kind in allowed_kinds)
        ]

        source_path = self._get_symbol_path(source_sym, active_paths)

        # 1. Same-file definition (when not explicitly imported from another file)
        if imported_entry is None:
            same_file = [
                c
                for c in candidates
                if (source_sym.file_id and c.file_id == source_sym.file_id)
                or (source_path and self._get_symbol_path(c, active_paths) == source_path)
            ]
            if len(same_file) == 1:
                return SymbolEdge(
                    source_id=source_sym.id,
                    target_id=same_file[0].id,
                    edge_type=edge_type,
                    target_name=lookup_name,
                    provenance=provenance,
                    resolution_status="resolved",
                    confidence=1.0,
                    weight=default_weight,
                )

        # 2. ImportTracker-resolved file definition
        if imported_entry is not None and imported_entry.resolved_path:
            res_path = self._norm_path(imported_entry.resolved_path)
            imp_matches = [
                c
                for c in candidates
                if self._get_symbol_path(c, active_paths) == res_path
            ]
            if len(imp_matches) == 1:
                return SymbolEdge(
                    source_id=source_sym.id,
                    target_id=imp_matches[0].id,
                    edge_type=edge_type,
                    target_name=lookup_name,
                    provenance=merge_provenance(provenance, "import_tracker"),
                    resolution_status="resolved",
                    confidence=0.98,
                    weight=default_weight,
                )

        # 3. Unique repository-wide definition
        if len(candidates) == 1:
            return SymbolEdge(
                source_id=source_sym.id,
                target_id=candidates[0].id,
                edge_type=edge_type,
                target_name=lookup_name,
                provenance=provenance,
                resolution_status="resolved",
                confidence=0.9,
                weight=default_weight,
            )

        # 4. Same-directory unique definition
        if len(candidates) > 1 and source_path:
            src_dir = os.path.dirname(source_path)
            same_dir = [
                c
                for c in candidates
                if os.path.dirname(self._get_symbol_path(c, active_paths)) == src_dir
            ]
            if len(same_dir) == 1:
                return SymbolEdge(
                    source_id=source_sym.id,
                    target_id=same_dir[0].id,
                    edge_type=edge_type,
                    target_name=lookup_name,
                    provenance=provenance,
                    resolution_status="resolved",
                    confidence=0.85,
                    weight=default_weight,
                )

        # 5. Ambiguous reference -> do NOT assign arbitrary target_id
        if len(candidates) > 1:
            return SymbolEdge(
                source_id=source_sym.id,
                target_id=None,
                edge_type=edge_type,
                target_name=lookup_name,
                provenance=provenance,
                resolution_status="ambiguous",
                confidence=round(1.0 / len(candidates), 4),
                weight=default_weight,
                candidate_target_ids=tuple(c.id for c in candidates),
            )

        # 6. Unresolved reference -> target_id=None, target_name preserved
        return SymbolEdge(
            source_id=source_sym.id,
            target_id=None,
            edge_type=edge_type,
            target_name=lookup_name,
            provenance=provenance,
            resolution_status="unresolved",
            confidence=0.0,
            weight=default_weight,
        )

    def _get_symbol_path(self, sym: Symbol, active_paths: dict[UUID, str]) -> str:
        if sym.file_path:
            return self._norm_path(sym.file_path)
        if sym.file_id and sym.file_id in active_paths:
            return self._norm_path(active_paths[sym.file_id])
        return ""

    @staticmethod
    def _norm_path(path: str) -> str:
        p = path.replace("\\", "/")
        if p.startswith("./"):
            p = p[2:]
        return p.lstrip("/")

    @staticmethod
    def _normalize_call_name(raw_call: str) -> str:
        clean = raw_call.strip()
        if "::" in clean:
            clean = clean.split("::")[-1]
        if "." in clean:
            clean = clean.split(".")[-1]
        return clean.strip()

    @staticmethod
    def _clean_type_name(raw_type: str) -> str:
        cleaned = re.sub(r"<[^>]*>", "", raw_type).strip()
        cleaned = re.sub(r"^(?:public|protected|private|virtual)\s+", "", cleaned).strip()
        if "::" in cleaned:
            cleaned = cleaned.split("::")[-1]
        if "." in cleaned:
            cleaned = cleaned.split(".")[-1]
        return cleaned.strip()
