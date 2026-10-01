import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    User, GitHubInstallation, Repository, RepositoryFile,
    CodeSymbol, SymbolEdge, CodeChunk, MemoryEntry, MemoryType, MemoryStatus
)
from app.models.base import Base

# Note: This test requires a real PostgreSQL database with pgvector installed to pass.
# For local development with docker-compose, postgres is on localhost:5432
TEST_DATABASE_URL = "postgresql://platform:platform@localhost:5432/agent_platform"

@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    # create_all will create tables that don't exist yet
    Base.metadata.create_all(engine)
    yield engine
    # In a real environment we might drop tables or just clear them
    # Base.metadata.drop_all(engine)
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
    user = User(id=user_id, github_id="gh_123", login="testuser", email="test@example.com")
    db_session.add(user)
    
    install_id = uuid.uuid4()
    installation = GitHubInstallation(
        id=install_id, user_id=user_id, installation_id="inst_123", account_login="testuser", permissions={}
    )
    db_session.add(installation)
    
    repo_id = uuid.uuid4()
    repository = Repository(
        id=repo_id, user_id=user_id, installation_id=install_id, github_repo_id="repo_123",
        owner="testuser", name="testrepo", default_branch="main"
    )
    db_session.add(repository)
    db_session.flush()

    # 2. Repository Content Schema
    file_id = uuid.uuid4()
    repo_file = RepositoryFile(
        id=file_id, repository_id=repo_id, path="src/main.py", language="python",
        size_bytes=1024, line_count=50, content_hash="hash_123", is_binary=False
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
        content="class MyClass: ...", token_count=10, embedding=[0.1] * 1536,
        start_line=10, end_line=20, content_hash="hash_chunk_123", metadata_json={"type": "class"}
    )
    db_session.add(chunk)
    db_session.flush()

    # 4. Memory Schema
    memory_id = uuid.uuid4()
    memory = MemoryEntry(
        id=memory_id, repository_id=repo_id, type=MemoryType.decision,
        content="We decided to use PostgreSQL", source="agent_run:123", status=MemoryStatus.active
    )
    db_session.add(memory)
    
    # 5. Commit and Verify Data Pipeline Execution
    db_session.commit()

    saved_chunk = db_session.query(CodeChunk).filter_by(id=chunk_id).first()
    assert saved_chunk is not None
    assert saved_chunk.repository_id == repo_id
    assert len(saved_chunk.embedding) == 1536

    saved_memory = db_session.query(MemoryEntry).filter_by(id=memory_id).first()
    assert saved_memory is not None
    assert saved_memory.type == MemoryType.decision
