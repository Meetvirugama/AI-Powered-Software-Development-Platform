import re
from typing import List, Dict
from uuid import UUID
from .symbols import Symbol, SymbolEdge

class DependencyGraphBuilder:
    def __init__(self, symbols: List[Symbol]):
        self.symbols = symbols
        self.symbols_by_name = {}
        for s in symbols:
            self.symbols_by_name.setdefault(s.name, []).append(s)

    def build(self) -> List[SymbolEdge]:
        edges = []
        for sym in self.symbols:
            if sym.kind == "import":
                edges.extend(self._parse_import(sym))
            elif sym.kind in ("class", "interface"):
                edges.extend(self._parse_class_inheritance(sym))
            elif sym.kind in ("function", "method"):
                edges.extend(self._parse_calls(sym))
        return edges

    def _parse_import(self, sym: Symbol) -> List[SymbolEdge]:
        edges = []
        # Basic heuristic to extract names from imports
        words = re.findall(r'[a-zA-Z_]\w*', sym.signature)
        for word in words:
            if word in {"import", "from", "as", "const", "let", "var", "require", "type"}:
                continue
            if word in self.symbols_by_name:
                for target_sym in self.symbols_by_name[word]:
                    # Ignore self reference just in case
                    if target_sym.id != sym.id:
                        edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="imports"))
        
        # Resolve import paths to modules if possible
        # Ex: import { Router } from 'express' or from './my_module'
        # We can look for string literals
        strings = re.findall(r'["\']([^"\']+)["\']', sym.signature)
        for s in strings:
            # Check if this matches a module name in symbols
            if s in self.symbols_by_name:
                for target_sym in self.symbols_by_name[s]:
                    if target_sym.id != sym.id:
                        edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="imports"))
            else:
                # sometimes module names in our symbol table might be the basename
                basename = s.split('/')[-1]
                if basename in self.symbols_by_name:
                    for target_sym in self.symbols_by_name[basename]:
                        if target_sym.kind == "module" and target_sym.id != sym.id:
                            edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="imports"))

        return edges

    def _parse_class_inheritance(self, sym: Symbol) -> List[SymbolEdge]:
        edges = []
        
        # Check 'extends' for JS/TS/Java
        extends_match = re.search(r'extends\s+([a-zA-Z_]\w*)', sym.signature)
        if extends_match:
            target_name = extends_match.group(1)
            if target_name in self.symbols_by_name:
                for target_sym in self.symbols_by_name[target_name]:
                    edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="extends"))
                    
        # Check Python inheritance: class A(B):
        py_match = re.search(r'class\s+\w+\s*\(\s*([a-zA-Z_]\w*)\s*\)', sym.signature)
        if py_match:
            target_name = py_match.group(1)
            if target_name in self.symbols_by_name:
                for target_sym in self.symbols_by_name[target_name]:
                    edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="extends"))

        # Check 'implements' for JS/TS/Java
        implements_match = re.search(r'implements\s+([a-zA-Z_]\w*(?:\s*,\s*[a-zA-Z_]\w*)*)', sym.signature)
        if implements_match:
            targets_str = implements_match.group(1)
            targets = [t.strip() for t in targets_str.split(',')]
            for target_name in targets:
                if target_name in self.symbols_by_name:
                    for target_sym in self.symbols_by_name[target_name]:
                        edges.append(SymbolEdge(source_id=sym.id, target_id=target_sym.id, edge_type="implements"))
                        
        return edges

    def _parse_calls(self, sym: Symbol) -> List[SymbolEdge]:
        edges = []
        # Since we only have access to signatures in the Symbol table, 
        # and calls happen in the body, we can't reliably detect calls here 
        # without parsing the tree again. For this implementation using only 
        # the Symbol table from Day 4 as instructed, we skip or use a regex on signature if it had a body.
        return edges
