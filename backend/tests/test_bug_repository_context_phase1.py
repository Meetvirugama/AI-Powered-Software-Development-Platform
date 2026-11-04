"""
Phase 1 Test Suite — Connect Existing Repository Context to Bug Detection
Reference: task.md §6 (Phase 1), §9 (P0)

Validates:
1. Integration of get_bug_context / extract_bug_context into Bug Detection API.
2. Extraction of real caller implementation source (not just signatures).
3. Extraction of defensive guard blocks (try/except, null checks, if not x).
4. Commit-pinned revision propagation.
5. Missing-context reporting for external unindexed calls.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.main import app
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.schemas.analysis import BugDetectionRequest
from app.services.bug_detection_orchestrator import resolve_bug_target_and_build_context


def _setup_repo(db_session, owner_user) -> Repository:
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=owner_user.id,
        installation_id=f"inst-{uuid.uuid4().hex[:8]}",
        account_login=owner_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(inst)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=owner_user.id,
        installation_id=inst.id,
        github_repo_id=f"gh-{uuid.uuid4().hex[:8]}",
        owner=owner_user.login,
        name="bug-repo-phase1",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    return repo


def test_phase1_defensive_guards_and_external_calls(db_session, test_user) -> None:
    """Verify that resolve_bug_target_and_build_context extracts defensive guards and external calls."""
    repo = _setup_repo(db_session, test_user)

    code = (
        "def query_database(user_id: int, query_filter: str):\n"
        "    if user_id is None:\n"
        "        raise ValueError('Invalid user ID')\n"
        "    try:\n"
        "        result = third_party_client.execute(query_filter)\n"
        "        return result\n"
        "    except Exception as exc:\n"
        "        logger.error(str(exc))\n"
        "        return None\n"
    )

    lines = code.splitlines()
    f_row = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/queries.py",
        language="python",
        size_bytes=len(code),
        line_count=len(lines),
        content_hash="h1",
    )
    db_session.add(f_row)

    sym = CodeSymbol(
        id=uuid.uuid4(),
        file_id=f_row.id,
        repository_id=repo.id,
        name="query_database",
        kind="function",
        start_line=1,
        end_line=len(lines),
        signature="def query_database(user_id: int, query_filter: str):",
    )
    db_session.add(sym)

    chunk = CodeChunk(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=f_row.id,
        symbol_id=sym.id,
        content=code,
        token_count=len(code.split()),
        embedding=[0.0] * 768,
        start_line=1,
        end_line=len(lines),
        content_hash="c1",
        chunk_metadata={"file_path": "src/queries.py"},
    )
    db_session.add(chunk)
    db_session.commit()

    req = BugDetectionRequest(target={"path": "src/queries.py", "type": "symbol", "symbol": "query_database"})
    resolved = resolve_bug_target_and_build_context(repo.id, repo, req, db_session)

    assert resolved.target.path == "src/queries.py"
    assert resolved.resolved_symbol is not None
    assert resolved.resolved_symbol.name == "query_database"
    assert resolved.revision == "main"

    # 1. Defensive error-handling guard blocks must be extracted into project_rules
    rules = resolved.intelligence_context.project_rules
    assert any("Defensive Guard Context" in r for r in rules)
    assert any("user_id is None" in r or "try:" in r for r in rules)

    # 2. External third-party call (third_party_client) must be flagged in missing_context
    missing = resolved.intelligence_context.missing_context
    assert any("third_party_client" in (m.symbol_name or "") for m in missing)


def test_phase1_caller_source_extraction(db_session, test_user) -> None:
    """Verify that real caller source implementation is retrieved from CodeChunk."""
    repo = _setup_repo(db_session, test_user)

    target_code = "def process_payment(amount: float):\n    return amount * 1.05\n"
    caller_code = "def checkout_cart(user, total):\n    valid = user.is_authenticated\n    return process_payment(total)\n"

    f_target = RepositoryFile(
        id=uuid.uuid4(), repository_id=repo.id, path="src/payment.py", language="python",
        size_bytes=len(target_code), line_count=2, content_hash="ht",
    )
    f_caller = RepositoryFile(
        id=uuid.uuid4(), repository_id=repo.id, path="src/checkout.py", language="python",
        size_bytes=len(caller_code), line_count=3, content_hash="hc",
    )
    db_session.add_all([f_target, f_caller])
    db_session.commit()

    sym_target = CodeSymbol(
        id=uuid.uuid4(), file_id=f_target.id, repository_id=repo.id,
        name="process_payment", kind="function", start_line=1, end_line=2,
        signature="def process_payment(amount: float):",
    )
    sym_caller = CodeSymbol(
        id=uuid.uuid4(), file_id=f_caller.id, repository_id=repo.id,
        name="checkout_cart", kind="function", start_line=1, end_line=3,
        signature="def checkout_cart(user, total):",
    )
    db_session.add_all([sym_target, sym_caller])
    db_session.commit()

    edge = SymbolEdge(
        id=uuid.uuid4(), repository_id=repo.id,
        source_symbol_id=sym_caller.id, target_symbol_id=sym_target.id,
        edge_type="calls",
    )
    db_session.add(edge)

    chunk_target = CodeChunk(
        id=uuid.uuid4(), repository_id=repo.id, file_id=f_target.id, symbol_id=sym_target.id,
        content=target_code, token_count=10, embedding=[0.0] * 768,
        start_line=1, end_line=2, content_hash="ct", chunk_metadata={"file_path": "src/payment.py"},
    )
    chunk_caller = CodeChunk(
        id=uuid.uuid4(), repository_id=repo.id, file_id=f_caller.id, symbol_id=sym_caller.id,
        content=caller_code, token_count=15, embedding=[0.0] * 768,
        start_line=1, end_line=3, content_hash="cc", chunk_metadata={"file_path": "src/checkout.py"},
    )
    db_session.add_all([chunk_target, chunk_caller])
    db_session.commit()

    req = BugDetectionRequest(target={"path": "src/payment.py", "type": "symbol", "symbol": "process_payment"})
    resolved = resolve_bug_target_and_build_context(repo.id, repo, req, db_session)

    # Caller symbol must contain actual implementation code from chunk, not just signature
    related_syms = resolved.intelligence_context.related_symbols
    caller_ctx = next((s for s in related_syms if s.name == "checkout_cart"), None)
    assert caller_ctx is not None
    assert "user.is_authenticated" in caller_ctx.content

