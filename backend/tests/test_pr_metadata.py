"""Tests for Parth — Week 2 Day 5: PR Metadata Preparation.

Verifies:
1. PRMetadata data collection matches week2.md:
   - task_id: UUID
   - branch: str ("agent/task-f47ac10b")
   - base_branch: str ("main")
   - changed_files: list[str] (["src/auth/jwt.service.ts", ...])
   - commit_message: str ("feat: Add JWT authentication")
   - test_summary: str ("24 passed, 0 failed")
   - verification_summary: str ("Requirement match: PASS, ...")
2. Data persistence to database table pull_requests (owned exclusively by Parth).
3. Idempotent create-or-update behavior for the same task.
4. Auto-collection of metadata from workspace git repository.
5. PullRequestRepository CRUD operations.
6. REST API routes:
   - POST /api/v1/repositories/{id}/source/pr-metadata
   - GET /api/v1/repositories/{id}/source/pr-metadata/{task_id}
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.errors import APIError
from app.integrations.github.schemas import PRMetadata
from app.main import app
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.user import User
from app.repositories.pull_request_repository import PullRequestRepository
from app.services.git_branch import GitBranchService


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def db_session() -> Session:
    """Create a fresh in-memory SQLite database for testing models and repository."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    Repository.__table__.create(engine)
    PullRequest.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_user(db_session: Session) -> User:
    user = User(
        id=uuid4(),
        email="dev@example.com",
        github_id="gh-12345",
        login="leaddev",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_repo(db_session: Session, test_user: User) -> Repository:
    repo = Repository(
        id=uuid4(),
        user_id=test_user.id,
        installation_id=uuid4(),
        github_repo_id="12345678",
        owner="acme",
        name="web-platform",
        default_branch="main",
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)
    return repo


@pytest.fixture
def git_workspace(tmp_path: Path) -> Path:
    """Initialize a git workspace with changes on an agent branch."""
    ws = tmp_path / "workspace_task_f47ac10b"
    ws.mkdir(parents=True, exist_ok=True)

    def run_cmd(*args: str):
        subprocess.run(
            ["git", *args],
            cwd=str(ws),
            check=True,
            capture_output=True,
            text=True,
        )

    run_cmd("init", "-b", "main")
    run_cmd("config", "user.name", "Workspace Setup")
    run_cmd("config", "user.email", "setup@test.local")

    f1 = ws / "README.md"
    f1.write_text("# Readme\n", encoding="utf-8")
    run_cmd("add", "README.md")
    run_cmd("commit", "-m", "Initial commit")

    # Branch off
    run_cmd("checkout", "-b", "agent/task-f47ac10b")
    f2 = ws / "jwt.service.ts"
    f2.write_text("export class JwtService {}\n", encoding="utf-8")
    run_cmd("add", "jwt.service.ts")
    run_cmd("commit", "-m", "feat: Add JWT authentication")

    return ws


# ═══════════════════════════════════════════════════════════════════════════
# 1. PRMetadata Preparation Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPRMetadataPreparation:
    """Test suite for Day 5 PR metadata collection and persistence."""

    def test_prepare_pr_metadata_persists_to_db(
        self, db_session: Session, test_repo: Repository, test_user: User
    ):
        """Prepares PR metadata and stores in pull_requests table."""
        service = GitBranchService(db_session)
        task_id = UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")

        meta = service.prepare_pr_metadata(
            task_id=task_id,
            repository_id=test_repo.id,
            branch="agent/task-f47ac10b",
            base_branch="main",
            changed_files=["src/auth/jwt.service.ts", "src/auth/routes.ts"],
            commit_message="feat: Add JWT authentication",
            test_summary="24 passed, 0 failed",
            verification_summary="Requirement match: PASS, Test adequacy: PASS",
            user_id=test_user.id,
        )

        assert isinstance(meta, PRMetadata)
        assert meta.task_id == task_id
        assert meta.branch == "agent/task-f47ac10b"
        assert meta.base_branch == "main"
        assert meta.changed_files == ["src/auth/jwt.service.ts", "src/auth/routes.ts"]
        assert meta.commit_message == "feat: Add JWT authentication"
        assert meta.test_summary == "24 passed, 0 failed"
        assert meta.verification_summary == "Requirement match: PASS, Test adequacy: PASS"
        assert meta.status == "prepared"

        # Verify database record exists
        repo_layer = PullRequestRepository(db_session)
        db_record = repo_layer.get_by_task_id(task_id)
        assert db_record is not None
        assert db_record.task_id == task_id
        assert db_record.repository_id == test_repo.id
        assert db_record.branch == "agent/task-f47ac10b"
        assert db_record.changed_files == ["src/auth/jwt.service.ts", "src/auth/routes.ts"]

    def test_prepare_pr_metadata_idempotent_update(
        self, db_session: Session, test_repo: Repository
    ):
        """Updating PR metadata for an existing task modifies the record in-place."""
        service = GitBranchService(db_session)
        task_id = uuid4()

        # Initial preparation
        service.prepare_pr_metadata(
            task_id=task_id,
            repository_id=test_repo.id,
            branch="agent/task-1",
            base_branch="main",
            changed_files=["file1.py"],
            commit_message="Initial commit",
            test_summary="1 passed",
            verification_summary="PASS",
        )

        # Updated after more work
        updated = service.prepare_pr_metadata(
            task_id=task_id,
            repository_id=test_repo.id,
            branch="agent/task-1",
            base_branch="main",
            changed_files=["file1.py", "file2.py"],
            commit_message="feat: Add file1 and file2",
            test_summary="2 passed, 0 failed",
            verification_summary="Requirement match: PASS",
        )

        assert updated.changed_files == ["file1.py", "file2.py"]
        assert updated.test_summary == "2 passed, 0 failed"

        # Verify only 1 record exists in DB for this task
        repo_layer = PullRequestRepository(db_session)
        all_records = repo_layer.list_by_repository(test_repo.id)
        assert len(all_records) == 1

    def test_get_pr_metadata_retrieval(
        self, db_session: Session, test_repo: Repository
    ):
        """Retrieves previously stored PR metadata by task ID."""
        service = GitBranchService(db_session)
        task_id = uuid4()

        service.prepare_pr_metadata(
            task_id=task_id,
            repository_id=test_repo.id,
            branch="agent/task-f47ac10b",
            base_branch="main",
            changed_files=["src/auth/jwt.service.ts"],
            commit_message="feat: Add JWT authentication",
            test_summary="24 passed, 0 failed",
            verification_summary="PASS",
        )

        fetched = service.get_pr_metadata(task_id)
        assert fetched.task_id == task_id
        assert fetched.branch == "agent/task-f47ac10b"
        assert fetched.commit_message == "feat: Add JWT authentication"

    def test_get_pr_metadata_not_found_raises_404(
        self, db_session: Session
    ):
        """Non-existent task ID raises 404 RESOURCE_NOT_FOUND."""
        service = GitBranchService(db_session)
        with pytest.raises(APIError) as exc:
            service.get_pr_metadata(uuid4())
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_collect_pr_metadata_from_workspace(
        self, db_session: Session, test_repo: Repository, git_workspace: Path
    ):
        """Auto-discovers commit message, changed files, and branch from local workspace git."""
        service = GitBranchService(db_session)
        task_id = UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")

        meta = await service.collect_pr_metadata_from_workspace(
            workspace_path=git_workspace,
            task_id=task_id,
            repository_id=test_repo.id,
            base_branch="main",
            test_summary="24 passed, 0 failed",
            verification_summary="Requirement match: PASS",
        )

        assert meta.branch == "agent/task-f47ac10b"
        assert meta.commit_message == "feat: Add JWT authentication"
        assert "jwt.service.ts" in meta.changed_files
        assert meta.test_summary == "24 passed, 0 failed"


# ═══════════════════════════════════════════════════════════════════════════
# 2. PullRequestRepository Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPullRequestRepository:
    """Test suite for repository CRUD operations."""

    def test_repository_lifecycle_methods(
        self, db_session: Session, test_repo: Repository
    ):
        repo_layer = PullRequestRepository(db_session)
        task_id = uuid4()

        # Create
        pr = repo_layer.create_or_update(
            task_id=task_id,
            repository_id=test_repo.id,
            branch="agent/task-xyz",
            base_branch="main",
            changed_files=["app.py"],
            commit_message="Initial",
            test_summary="Tests OK",
            verification_summary="VERIFIED",
        )
        assert pr.status == "prepared"

        # Update status (e.g. ready for approval in Week 3)
        updated = repo_layer.update_status(
            task_id=task_id,
            status="waiting_push_approval",
            pr_number=42,
            pr_url="https://github.com/acme/web-platform/pull/42",
        )
        assert updated.status == "waiting_push_approval"
        assert updated.pr_number == 42
        assert updated.pr_url == "https://github.com/acme/web-platform/pull/42"

        # Delete on task cancellation
        deleted = repo_layer.delete_by_task_id(task_id)
        assert deleted is True
        assert repo_layer.get_by_task_id(task_id) is None


# ═══════════════════════════════════════════════════════════════════════════
# 3. REST API Route Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPRMetadataRoutes:
    """Test suite for POST/GET /api/v1/repositories/{id}/source/pr-metadata."""

    def _setup_auth(self, monkeypatch):
        """Configure JWT and Redis mocks for authenticated requests."""
        from app.core.config import get_settings

        monkeypatch.setenv("JWT_SECRET", "test-secret")
        get_settings.cache_clear()

        class FakeRedis:
            def exists(self, key: str) -> int:
                return 0
            def setex(self, *args) -> None:
                pass
            def rpush(self, *args) -> int:
                return 1

        fake_redis = FakeRedis()
        monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
        return fake_redis

    def test_post_and_get_pr_metadata_endpoints(
        self, db_session: Session, test_repo: Repository, test_user: User, monkeypatch
    ):
        self._setup_auth(monkeypatch)
        from app.core.security import create_access_token

        app.dependency_overrides[get_db] = lambda: db_session
        client = TestClient(app)

        task_id = uuid4()
        payload = {
            "task_id": str(task_id),
            "branch": "agent/task-f47ac10b",
            "base_branch": "main",
            "changed_files": ["src/auth/jwt.service.ts"],
            "commit_message": "feat: Add JWT authentication",
            "test_summary": "24 passed, 0 failed",
            "verification_summary": "Requirement match: PASS",
        }

        token, _ = create_access_token(str(test_user.id))
        headers = {"Authorization": f"Bearer {token}"}

        # POST /pr-metadata
        res_post = client.post(
            f"/api/v1/repositories/{test_repo.id}/source/pr-metadata",
            json=payload,
            headers=headers,
        )
        assert res_post.status_code == 200
        data_post = res_post.json()
        assert data_post["task_id"] == str(task_id)
        assert data_post["branch"] == "agent/task-f47ac10b"
        assert data_post["commit_message"] == "feat: Add JWT authentication"

        # GET /pr-metadata/{task_id}
        res_get = client.get(
            f"/api/v1/repositories/{test_repo.id}/source/pr-metadata/{task_id}",
            headers=headers,
        )
        assert res_get.status_code == 200
        data_get = res_get.json()
        assert data_get["task_id"] == str(task_id)
        assert data_get["changed_files"] == ["src/auth/jwt.service.ts"]

        app.dependency_overrides.clear()

