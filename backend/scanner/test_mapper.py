import os
from typing import Dict, List, Set
from uuid import UUID
from .symbols import Symbol, SymbolEdge

class FileTestMapper:
    def __init__(self, symbols: List[Symbol], edges: List[SymbolEdge], file_paths: Dict[UUID, str]):
        self.symbols = symbols
        self.edges = edges
        self.file_paths = file_paths
        
        self.symbols_by_id = {s.id: s for s in self.symbols}
        self.symbols_by_file = {}
        for s in self.symbols:
            self.symbols_by_file.setdefault(s.file_id, []).append(s)

    def is_test_file(self, file_id: UUID) -> bool:
        path = self.file_paths.get(file_id, "")
        basename = os.path.basename(path).lower()
        if "test" in basename or "spec" in basename:
            return True
        
        # Check symbols
        file_symbols = self.symbols_by_file.get(file_id, [])
        for sym in file_symbols:
            if sym.kind in ("function", "method"):
                name = sym.name.lower()
                if name.startswith("test_") or name == "describe" or name == "it":
                    return True
        return False

    def get_source_from_name(self, test_path: str) -> str:
        basename = os.path.basename(test_path)
        
        parts = test_path.split(os.sep)
        clean_parts = [p for p in parts if p.lower() not in ("tests", "test", "__tests__")]
        clean_path_no_test_dir = os.sep.join(clean_parts)
        
        clean_name = basename
        for suffix in [".test.ts", ".spec.ts", ".test.js", ".spec.js", "_test.py", "_test.go", "Test.java"]:
            if basename.endswith(suffix):
                ext = suffix.split(".")[-1]
                clean_name = basename[:-len(suffix)] + "." + ext
                break
        
        if clean_name == basename:
            if basename.startswith("test_"):
                clean_name = basename[5:]
        
        clean_path = os.path.join(os.path.dirname(clean_path_no_test_dir), clean_name)
        clean_path = clean_path.replace("\\", "/")
        return clean_path

    def map_tests(self) -> Dict[str, str]:
        mapping = {}
        
        test_file_ids = {fid for fid in self.file_paths if self.is_test_file(fid)}
        non_test_file_ids = set(self.file_paths.keys()) - test_file_ids
        
        for fid in test_file_ids:
            t_path = self.file_paths[fid]
            candidate_paths = []
            
            clean_name = self.get_source_from_name(t_path)
            for nt_path in [self.file_paths[nt_id] for nt_id in non_test_file_ids]:
                nt_path_norm = nt_path.replace("\\", "/")
                t_path_norm = clean_name.replace("\\", "/")
                
                if nt_path_norm == t_path_norm or nt_path_norm.endswith("/" + os.path.basename(t_path_norm)):
                    candidate_paths.append(nt_path)
                    
            if len(candidate_paths) == 1:
                mapping[t_path] = candidate_paths[0]
                continue
            
            file_symbols = self.symbols_by_file.get(fid, [])
            file_symbol_ids = {s.id for s in file_symbols}
            
            imported_file_ids = set()
            for edge in self.edges:
                if edge.edge_type == "imports" and edge.source_id in file_symbol_ids:
                    target_sym = self.symbols_by_id.get(edge.target_id)
                    if target_sym and target_sym.file_id in non_test_file_ids:
                        imported_file_ids.add(target_sym.file_id)
                        
            if len(imported_file_ids) == 1:
                target_fid = imported_file_ids.pop()
                mapping[t_path] = self.file_paths[target_fid]
            elif len(imported_file_ids) > 1 and len(candidate_paths) > 0:
                intersection = set(candidate_paths).intersection({self.file_paths[i] for i in imported_file_ids})
                if len(intersection) == 1:
                    mapping[t_path] = intersection.pop()
                else:
                    mapping[t_path] = candidate_paths[0]
            elif len(candidate_paths) > 0:
                mapping[t_path] = candidate_paths[0]
                
        return mapping
