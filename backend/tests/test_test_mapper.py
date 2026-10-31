import pytest
from uuid import uuid4
from scanner.symbols import Symbol, SymbolEdge
from scanner.test_mapper import FileTestMapper

def test_mapper_name_heuristics():
    fid_src = uuid4()
    fid_test = uuid4()
    
    file_paths = {
        fid_src: "src/auth/service.ts",
        fid_test: "src/auth/service.test.ts"
    }
    
    mapper = FileTestMapper([], [], file_paths)
    mapping = mapper.map_tests()
    
    assert mapping["src/auth/service.test.ts"] == "src/auth/service.ts"

def test_mapper_python_tests_dir():
    fid_src = uuid4()
    fid_test = uuid4()
    
    file_paths = {
        fid_src: "auth/service.py",
        fid_test: "tests/auth/test_service.py"
    }
    
    mapper = FileTestMapper([], [], file_paths)
    mapping = mapper.map_tests()
    
    assert mapping["tests/auth/test_service.py"] == "auth/service.py"

def test_mapper_imports():
    fid_src = uuid4()
    fid_test = uuid4()
    fid_other = uuid4()
    
    file_paths = {
        fid_src: "lib/complex_logic.js",
        fid_test: "specs/logic.spec.js",
        fid_other: "lib/other.js"
    }
    
    sym_test_import = Symbol(id=uuid4(), name="import_complex", kind="import", file_id=fid_test, start_line=1, end_line=1, signature="", parent_id=None)
    sym_src_class = Symbol(id=uuid4(), name="ComplexLogic", kind="class", file_id=fid_src, start_line=1, end_line=10, signature="", parent_id=None)
    
    symbols = [sym_test_import, sym_src_class]
    edges = [SymbolEdge(source_id=sym_test_import.id, target_id=sym_src_class.id, edge_type="imports")]
    
    mapper = FileTestMapper(symbols, edges, file_paths)
    mapping = mapper.map_tests()
    
    assert mapping["specs/logic.spec.js"] == "lib/complex_logic.js"
