import os
import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import (
    User, GitHubInstallation, Repository, RepositoryFile,
    CodeSymbol, SymbolEdge, CodeChunk, MemoryEntry, MemoryType, MemoryStatus
)
from app.core.config import get_settings
from app.core.database import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    get_settings().database_url,
)

@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"connect_timeout": 2})
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("PostgreSQL test database not available")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()

def test_complete_data_pipeline_end_to_end(db_session):
    """
    Day 7 - DB Integration Test
    Verify the complete data pipeline writes correctly end-to-end:
    GH[GitHub Clone] --> RF[repository_files] --> CS[code_symbols] --> SE[symbol_edges] 
    --> CC[code_chunks] --> EM[embedding vector] --> ME[memory_entries]
    """
    # 1. Identity Schema
    user_id = uuid.uuid4()
    user = User(id=user_id, github_id=f"gh_{uuid.uuid4().hex[:8]}", login=f"test_{uuid.uuid4().hex[:6]}", email="test@example.com")
    db_session.add(user)
    db_session.flush()

    install_id = uuid.uuid4()
    installation = GitHubInstallation(
        id=install_id, user_id=user_id, installation_id=f"inst_{uuid.uuid4().hex[:8]}", account_login=user.login, permissions={}
    )
    db_session.add(installation)
    db_session.flush()

    repo_id = uuid.uuid4()
    repository = Repository(
        id=repo_id, user_id=user_id, installation_id=install_id, github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
        owner=user.login, name="testrepo", default_branch="main"
    )
    db_session.add(repository)
    db_session.flush()

    # 2. Repository Content Schema
    file_id = uuid.uuid4()
    repo_file = RepositoryFile(
        id=file_id, repository_id=repo_id, path="src/main.py", language="python",
        size_bytes=1024, line_count=50, content_hash="hash_123"
    )
    db_session.add(repo_file)
    db_session.flush()

    symbol_id_1 = uuid.uuid4()
    symbol_1 = CodeSymbol(
        id=symbol_id_1, repository_id=repo_id, file_id=file_id, name="MyClass",
        kind="class", start_line=10, end_line=20, signature="class MyClass:"
    )
    symbol_id_2 = uuid.uuid4()
    symbol_2 = CodeSymbol(
        id=symbol_id_2, repository_id=repo_id, file_id=file_id, name="my_function",
        kind="function", start_line=22, end_line=30, signature="def my_function():"
    )
    db_session.add_all([symbol_1, symbol_2])
    db_session.flush()

    edge_id = uuid.uuid4()
    edge = SymbolEdge(
        id=edge_id, repository_id=repo_id, source_symbol_id=symbol_id_2,
        target_symbol_id=symbol_id_1, edge_type="calls"
    )
    db_session.add(edge)
    db_session.flush()

    # 3. RAG Schema (Code Chunks with Embeddings)
    chunk_id = uuid.uuid4()
    chunk = CodeChunk(
        id=chunk_id, repository_id=repo_id, file_id=file_id, symbol_id=symbol_id_1,
        content="class MyClass: ...", token_count=10, embedding=[0.1] * 768,
        start_line=10, end_line=20, content_hash="hash_chunk_123", chunk_metadata={"type": "class"}
    )
    db_session.add(chunk)
    db_session.flush()

    # 4. Memory Schema
    memory_id = uuid.uuid4()
    memory = MemoryEntry(
        id=memory_id, repository_id=repo_id, type_=MemoryType.decision,
        content="We decided to use PostgreSQL", source="agent_run:123", status=MemoryStatus.active
    )
    db_session.add(memory)
    
    # 5. Commit and Verify Data Pipeline Execution
    db_session.commit()

    saved_chunk = db_session.query(CodeChunk).filter_by(id=chunk_id).first()
    assert saved_chunk is not None
    assert saved_chunk.repository_id == repo_id
    assert len(saved_chunk.embedding) == 768

    saved_memory = db_session.query(MemoryEntry).filter_by(id=memory_id).first()
    assert saved_memory is not None
    assert saved_memory.type_ == MemoryType.decision
