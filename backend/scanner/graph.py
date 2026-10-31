import re
from typing import Dict, List, Optional
from uuid import UUID
from .symbols import Symbol, SymbolEdge


class DependencyGraphBuilder:
    def __init__(
        self,
        symbols: List[Symbol],
        file_contents: Optional[Dict[UUID, str]] = None,
    ):
        self.symbols = symbols
        self.file_contents: Dict[UUID, str] = file_contents or {}
        self.symbols_by_name: Dict[str, List[Symbol]] = {}
        for s in symbols:
            self.symbols_by_name.setdefault(s.name, []).append(s)

    def build(self) -> List[SymbolEdge]:
        edges: List[SymbolEdge] = []
        seen: set[tuple[UUID, UUID, str]] = set()
        for sym in self.symbols:
            sym_edges: List[SymbolEdge] = []
            if sym.kind == "import":
                sym_edges.extend(self._parse_import(sym))
            elif sym.kind in ("class", "interface"):
                sym_edges.extend(self._parse_class_inheritance(sym))
            elif sym.kind in ("function", "method"):
                sym_edges.extend(self._parse_calls(sym))

            for e in sym_edges:
                key = (e.source_id, e.target_id, e.edge_type)
                if key not in seen:
                    seen.add(key)
                    edges.append(e)
        return edges

    def _parse_import(self, sym: Symbol) -> List[SymbolEdge]:
        edges = []
        words = re.findall(r'[a-zA-Z_]\w*', sym.signature or "")
        for word in words:
            if word in {"import", "from", "as", "const", "let", "var", "require", "type"}:
                continue
            if word in self.symbols_by_name:
                for target_sym in self.symbols_by_name[word]:
                    if target_sym.id != sym.id:
                        edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="imports"))

        strings = re.findall(r'["\']([^"\']+)["\']', sym.signature or "")
        for s in strings:
            if s in self.symbols_by_name:
                for target_sym in self.symbols_by_name[s]:
                    if target_sym.id != sym.id:
                        edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="imports"))
            else:
                basename = s.split('/')[-1]
                if basename in self.symbols_by_name:
                    for target_sym in self.symbols_by_name[basename]:
                        if target_sym.kind == "module" and target_sym.id != sym.id:
                            edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="imports"))

        return edges

    def _parse_class_inheritance(self, sym: Symbol) -> List[SymbolEdge]:
        edges = []

        extends_match = re.search(r'extends\s+([a-zA-Z_]\w*)', sym.signature or "")
        if extends_match:
            target_name = extends_match.group(1)
            if target_name in self.symbols_by_name:
                for target_sym in self.symbols_by_name[target_name]:
                    if target_sym.id != sym.id:
                        edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="extends"))

        py_match = re.search(r'class\s+\w+\s*\(\s*([a-zA-Z_]\w*)\s*\)', sym.signature or "")
        if py_match:
            target_name = py_match.group(1)
            if target_name in self.symbols_by_name:
                for target_sym in self.symbols_by_name[target_name]:
                    if target_sym.id != sym.id:
                        edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="extends"))

        implements_match = re.search(r'implements\s+([a-zA-Z_]\w*(?:\s*,\s*[a-zA-Z_]\w*)*)', sym.signature or "")
        if implements_match:
            targets_str = implements_match.group(1)
            targets = [t.strip() for t in targets_str.split(',')]
            for target_name in targets:
                if target_name in self.symbols_by_name:
                    for target_sym in self.symbols_by_name[target_name]:
                        if target_sym.id != sym.id:
                            edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="implements"))

        return edges

    def _parse_calls(self, sym: Symbol) -> List[SymbolEdge]:
        edges: List[SymbolEdge] = []
        body_text = ""
        if sym.file_id and sym.file_id in self.file_contents:
            lines = self.file_contents[sym.file_id].splitlines()
            start_idx = max(0, (sym.start_line or 1) - 1)
            end_idx = min(len(lines), sym.end_line or len(lines))
            body_text = "\n".join(lines[start_idx:end_idx])
        if not body_text:
            body_text = sym.signature or ""

        if not body_text:
            return edges

        call_names = set(re.findall(r'\b([a-zA-Z_]\w*)\s*\(', body_text))
        ignored = {
            sym.name, "if", "for", "while", "switch", "catch", "return", "sizeof",
            "typeof", "print", "len", "range", "str", "int", "float", "bool",
            "list", "dict", "set", "tuple", "super", "isinstance", "getattr", "setattr",
        }
        for callee in call_names - ignored:
            for target_sym in self.symbols_by_name.get(callee, []):
                if target_sym.id != sym.id and target_sym.kind in ("function", "method", "class"):
                    edges.append(
                        SymbolEdge(
                            source_id=sym.id,
                            target_id=target_sym.id,
                            edge_type="calls",
                        )
                    )
        return edges
