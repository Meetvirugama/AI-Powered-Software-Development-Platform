import os
import sys
import uuid
import hashlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.database import SessionLocal
from app.models import User, GitHubInstallation, Repository, RepositoryFile, CodeChunk

from sqlalchemy import create_engine
from app.core.database import Base
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

try:
    from pgvector.sqlalchemy import Vector
    @compiles(Vector, "sqlite")
    def _compile_vector_sqlite(type_, compiler, **kw):
        return "TEXT"
except ImportError:
    pass

def seed():
    # Use SQLite for local testing without Docker
    db_path = os.path.join(os.path.dirname(__file__), "..", "test.db")
    engine = create_engine(f"sqlite:///{db_path}")
    
    # Filter out postgresql-specific indexes if creating on SQLite
    for table in Base.metadata.tables.values():
        indexes_to_remove = [
            idx
            for idx in table.indexes
            if any(
                "to_tsvector" in str(getattr(expr, "text", expr))
                or idx.dialect_options.get("postgresql", {}).get("using") in ("hnsw", "gin")
                for expr in idx.expressions
            )
        ]
        for idx in indexes_to_remove:
            table.indexes.remove(idx)
            
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    # 1. Create a dummy user
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"test_{user_id}@example.com",
        github_id=str(uuid.uuid4().int)[:10],
        login="testuser"
    )
    db.add(user)
    
    # 2. Create an installation
    install_id = uuid.uuid4()
    install = GitHubInstallation(
        id=install_id,
        user_id=user_id,
        installation_id=str(uuid.uuid4().int)[:10],
        account_login="test_account"
    )
    db.add(install)
    
    # 3. Create a repository with a HARDCODED UUID so benchmark_rag.py can find it
    repo_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    repo = Repository(
        id=repo_id,
        user_id=user_id,
        installation_id=install_id,
        github_repo_id=str(uuid.uuid4().int)[:10],
        owner="testuser",
        name="python_sample",
        language="python"
    )
    db.add(repo)
    
    db.commit()
    
    print(f"Created repository {repo_id}")
    
    # 4. Read the fixture files and insert them
    fixtures_dir = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "python_sample")
    
    for filename in os.listdir(fixtures_dir):
        if not filename.endswith(".py"):
            continue
            
        filepath = os.path.join(fixtures_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        file_id = uuid.uuid4()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        
        repo_file = RepositoryFile(
            id=file_id,
            repository_id=repo_id,
            path=filename,
            language="python",
            size_bytes=len(content.encode('utf-8')),
            line_count=len(content.splitlines()),
            content_hash=content_hash
        )
        db.add(repo_file)
        
        # We dump the whole file as a single chunk for the LexicalRetriever to find
        chunk = CodeChunk(
            id=uuid.uuid4(),
            repository_id=repo_id,
            file_id=file_id,
            content=content,
            token_count=len(content.split()),
            embedding=[0.0] * 1536,
            start_line=1,
            end_line=len(content.splitlines()),
            content_hash=content_hash,
            chunk_metadata={"file_path": filename}
        )
        db.add(chunk)
        print(f"Indexed {filename}")
        
    db.commit()
    print("Database seeding complete!")

if __name__ == "__main__":
    seed()
