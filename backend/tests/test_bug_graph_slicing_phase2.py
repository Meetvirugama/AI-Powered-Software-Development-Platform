"""Tests for Phase 2: Graph-Guided Detection & Program Slicing.

Verifies:
1. TaintAnalyzer: Source-to-sink tracking, sanitizer detection, safe vs unsafe flows.
2. BugGraphContextService: Multi-hop backward and forward slicing, test association, trace steps.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.services.bug_graph_context_service import BugGraphContextService
from scanner.taint_analyzer import TaintAnalyzer


def test_taint_analyzer_sql_injection_detected():
    """Verify TaintAnalyzer flags unsanitized SQL injection with string formatting."""
    code = """
def search_user():
    user_input = request.query_params["username"]
    query = f"SELECT * FROM users WHERE name = '{user_input}'"
    cursor.execute(query)
"""
    analyzer = TaintAnalyzer()
    candidates = analyzer.analyze_source(code, file_path="backend/app/api/users.py")

    assert len(candidates) >= 1
    sql_candidates = [c for c in candidates if c.vulnerability_type == "sql_injection"]
    assert len(sql_candidates) >= 1
    cand = sql_candidates[0]
    assert cand.severity in ("CRITICAL", "HIGH")
    assert not cand.is_sanitized
    assert "request.query_params" in cand.source.name
    assert cand.sink.name == "execute"
    assert cand.start_line == 5  # cursor.execute(query) line


def test_taint_analyzer_sanitized_sql_not_critical():
    """Verify TaintAnalyzer recognizes typecast or parameterized queries as sanitized."""
    code = """
def get_user_by_id():
    raw_id = request.query_params["id"]
    safe_id = int(raw_id)
    query = f"SELECT * FROM users WHERE id = {safe_id}"
    cursor.execute(query)
"""
    analyzer = TaintAnalyzer()
    candidates = analyzer.analyze_source(code, file_path="backend/app/api/users.py")

    sql_candidates = [c for c in candidates if c.vulnerability_type == "sql_injection"]
    assert len(sql_candidates) >= 1
    cand = sql_candidates[0]
    assert cand.is_sanitized is True
    assert cand.severity == "LOW"
    assert len(cand.sanitizers_found) >= 1
    assert cand.sanitizers_found[0].name == "int"


def test_taint_analyzer_command_injection():
    """Verify TaintAnalyzer detects untrusted input passed to subprocess."""
    code = """
import subprocess

def run_backup():
    target = request.json["target"]
    cmd = f"tar -czf backup.tar.gz {target}"
    subprocess.run(cmd, shell=True)
"""
    analyzer = TaintAnalyzer()
    candidates = analyzer.analyze_source(code, file_path="backend/backup.py")

    cmd_candidates = [c for c in candidates if c.vulnerability_type == "command_injection"]
    assert len(cmd_candidates) >= 1
    cand = cmd_candidates[0]
    assert cand.severity == "CRITICAL"
    assert not cand.is_sanitized
    assert "request.json" in cand.source.name


def test_taint_analyzer_path_traversal():
    """Verify TaintAnalyzer detects open() on untrusted file input."""
    code = """
def read_user_file():
    filename = request.args["filename"]
    with open(f"/var/data/{filename}") as f:
        return f.read()
"""
    analyzer = TaintAnalyzer()
    candidates = analyzer.analyze_source(code, file_path="backend/files.py")

    path_candidates = [c for c in candidates if c.vulnerability_type == "path_traversal"]
    assert len(path_candidates) >= 1
    cand = path_candidates[0]
    assert cand.vulnerability_type == "path_traversal"
    assert cand.sink.name == "open"


@pytest.mark.asyncio
async def test_bug_graph_context_service_multi_hop_slice():
    """Verify BugGraphContextService constructs backward and forward slices across symbol edges."""
    repo_id = uuid.uuid4()
    file_id = uuid.uuid4()
    caller_file_id = uuid.uuid4()

    # Target symbol: execute_query
    target_sym_id = uuid.uuid4()
    target_sym = CodeSymbol(
        id=target_sym_id,
        repository_id=repo_id,
        file_id=file_id,
        name="execute_query",
        kind="function",
        start_line=40,
        end_line=50,
        signature="def execute_query(sql: str)",
    )

    # Caller symbol: user_service_search
    caller_sym_id = uuid.uuid4()
    caller_sym = CodeSymbol(
        id=caller_sym_id,
        repository_id=repo_id,
        file_id=caller_file_id,
        name="user_service_search",
        kind="function",
        start_line=20,
        end_line=30,
        signature="def user_service_search(name: str)",
    )

    # SymbolEdge: caller -> target
    edge = SymbolEdge(
        repository_id=repo_id,
        source_symbol_id=caller_sym_id,
        target_symbol_id=target_sym_id,
        edge_type="calls",
    )

    db = AsyncMock()

    # Mock execute results based on select queries
    async def mock_execute(statement, *args, **kwargs):
        stmt_str = str(statement).lower()
        mock_res = MagicMock()

        if "repository_files" in stmt_str and "code_symbols" in stmt_str:
            # Join query for neighbor details or test caller query
            mock_res.first.return_value = (caller_sym, "backend/services/user_service.py")
            mock_res.all.return_value = [(caller_sym, "backend/services/user_service.py")]
            return mock_res

        if "from code_symbols" in stmt_str:
            mock_res.scalar_one_or_none.return_value = target_sym
            return mock_res

        if "from symbol_edges" in stmt_str and "target_symbol_id" in stmt_str:
            # Backward slice query
            mock_res.scalars.return_value.all.return_value = [edge]
            return mock_res

        if "from symbol_edges" in stmt_str and "source_symbol_id" in stmt_str:
            # Forward slice query
            mock_res.scalars.return_value.all.return_value = []
            return mock_res

        if "from code_chunks" in stmt_str:
            mock_res.scalar_one_or_none.return_value = "def user_service_search(name: str):\n    execute_query(name)"
            return mock_res

        if "from repository_files" in stmt_str:
            mock_res.scalars.return_value.first.return_value = None
            mock_res.scalar_one_or_none.return_value = None
            return mock_res

        mock_res.scalars.return_value.all.return_value = []
        mock_res.all.return_value = []
        mock_res.first.return_value = None
        mock_res.scalar_one_or_none.return_value = None
        return mock_res

    db.execute.side_effect = mock_execute

    service = BugGraphContextService(db=db)
    slice_result = await service.build_program_slice(
        repository_id=repo_id,
        target_file_path="backend/repositories/user_repo.py",
        target_symbol_id=target_sym_id,
        max_depth=2,
    )

    assert slice_result.target_symbol_name == "execute_query"
    assert len(slice_result.backward_slice) == 1
    caller_node = slice_result.backward_slice[0]
    assert caller_node.name == "user_service_search"
    assert caller_node.file_path == "backend/services/user_service.py"
    assert caller_node.hop_distance == 1
    assert "user_service.py:20 (user_service_search)" in slice_result.dependency_trace[0]
    assert "user_repo.py:40 (execute_query)" in slice_result.dependency_trace[1]
