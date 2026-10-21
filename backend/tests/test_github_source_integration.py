"""Tests for Parth's GitHub source integration — Day 1 deliverables.

Covers:
- Schema validation (path traversal, line ranges, enums)
- GitHubClient error handling (rate limits, retries, 404s)
- GitHubSourceService authorization and content retrieval
- API route contract tests (authentication, response shapes)

All tests use deterministic mocks — no real GitHub API calls.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.integrations.github.schemas import (
    CommitAuthor,
    CommitDetail,
    CommitFileChange,
    CommitListResponse,
    DiffStatus,
    FileContentRequest,
    FileContentResponse,
    FileTreeResponse,
    PullRequestDiffResponse,
    PullRequestFile,
    PullRequestInfo,
    SourceReference,
    TreeEntry,
)
from app.integrations.github.client import GitHubAPIError, GitHubClient


# ═══════════════════════════════════════════════════════════════════════════
# 1. Schema validation tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSourceReference:
    """Shared source-reference schema."""

    def test_valid_minimal(self):
        ref = SourceReference(repository_id="abc", file_path="src/main.py")
        assert ref.start_line is None
        assert ref.end_line is None
        assert ref.revision is None
        assert ref.symbol_name is None

    def test_valid_full(self):
        ref = SourceReference(
            repository_id="repo-1",
            file_path="src/main.py",
            start_line=10,
            end_line=20,
            revision="abc123",
            symbol_name="MyClass",
        )
        assert ref.start_line == 10
        assert ref.end_line == 20

    def test_end_before_start_raises(self):
        with pytest.raises(ValueError, match="end_line must be >= start_line"):
            SourceReference(
                repository_id="r",
                file_path="f.py",
                start_line=20,
                end_line=10,
            )


class TestFileContentRequest:
    """Request schema for file retrieval."""

    def test_valid_simple_path(self):
        req = FileContentRequest(path="src/main.py")
        assert req.path == "src/main.py"
        assert req.ref is None

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError, match="Path traversal"):
            FileContentRequest(path="../../../etc/passwd")

    def test_path_traversal_middle_rejected(self):
        with pytest.raises(ValueError, match="Path traversal"):
            FileContentRequest(path="src/../../etc/passwd")

    def test_absolute_path_rejected(self):
        with pytest.raises(ValueError, match="Absolute paths"):
            FileContentRequest(path="/etc/passwd")

    def test_backslash_traversal_rejected(self):
        with pytest.raises(ValueError, match="Path traversal"):
            FileContentRequest(path="src\\..\\..\\etc\\passwd")

    def test_valid_path_with_ref(self):
        req = FileContentRequest(path="lib/utils.py", ref="develop")
        assert req.ref == "develop"

    def test_line_range_validation(self):
        req = FileContentRequest(path="f.py", start_line=5, end_line=10)
        assert req.start_line == 5
        assert req.end_line == 10

    def test_invalid_line_range(self):
        with pytest.raises(ValueError, match="end_line must be >= start_line"):
            FileContentRequest(path="f.py", start_line=20, end_line=5)

    def test_empty_path_rejected(self):
        with pytest.raises(ValueError):
            FileContentRequest(path="")


class TestDiffStatus:
    """DiffStatus enum values."""

    def test_valid_statuses(self):
        assert DiffStatus("added") == DiffStatus.ADDED
        assert DiffStatus("removed") == DiffStatus.REMOVED
        assert DiffStatus("modified") == DiffStatus.MODIFIED
        assert DiffStatus("renamed") == DiffStatus.RENAMED

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            DiffStatus("unknown_status")


class TestFileContentResponse:
    """Response schema for file content."""

    def test_minimal_response(self):
        resp = FileContentResponse(
            path="main.py",
            content="print('hello')",
            size_bytes=14,
            line_count=1,
        )
        assert resp.encoding == "utf-8"
        assert resp.truncated is False
        assert resp.language is None

    def test_full_response_with_source_ref(self):
        ref = SourceReference(repository_id="r", file_path="main.py", revision="abc")
        resp = FileContentResponse(
            path="main.py",
            content="x = 1\ny = 2\n",
            size_bytes=12,
            line_count=2,
            language="Python",
            sha="blobsha",
            ref="main",
            source_reference=ref,
        )
        assert resp.source_reference.revision == "abc"
        assert resp.language == "Python"


class TestCommitDetail:
    """Commit metadata schema."""

    def test_minimal_commit(self):
        c = CommitDetail(
            sha="abc123",
            message="Initial commit",
            author=CommitAuthor(name="Dev"),
        )
        assert c.sha == "abc123"
        assert c.files == []
        assert c.parents == []

    def test_commit_with_files(self):
        c = CommitDetail(
            sha="def456",
            message="Fix bug",
            author=CommitAuthor(name="Dev", email="dev@example.com"),
            files=[
                CommitFileChange(
                    filename="fix.py",
                    status=DiffStatus.MODIFIED,
                    additions=5,
                    deletions=2,
                    changes=7,
                ),
            ],
        )
        assert len(c.files) == 1
        assert c.files[0].status == DiffStatus.MODIFIED


class TestPullRequestInfo:
    """PR metadata schema."""

    def test_minimal_pr(self):
        pr = PullRequestInfo(number=42, title="Add feature", state="open")
        assert pr.author is None
        assert pr.base_ref is None

    def test_full_pr(self):
        pr = PullRequestInfo(
            number=42,
            title="Add feature",
            state="open",
            author="parth",
            base_ref="main",
            head_ref="feature/test",
            body="Description here",
        )
        assert pr.author == "parth"
        assert pr.head_ref == "feature/test"


class TestPullRequestDiffResponse:
    """PR diff response schema."""

    def test_empty_diff(self):
        resp = PullRequestDiffResponse(
            pull_request=PullRequestInfo(number=1, title="t", state="open"),
            files=[],
        )
        assert resp.total_additions == 0
        assert resp.total_changes == 0

    def test_diff_with_files(self):
        resp = PullRequestDiffResponse(
            pull_request=PullRequestInfo(number=1, title="t", state="open"),
            files=[
                PullRequestFile(
                    filename="a.py",
                    status=DiffStatus.ADDED,
                    additions=10,
                    deletions=0,
                    changes=10,
                ),
                PullRequestFile(
                    filename="b.py",
                    status=DiffStatus.MODIFIED,
                    additions=5,
                    deletions=3,
                    changes=8,
                ),
            ],
            total_additions=15,
            total_deletions=3,
            total_changes=18,
        )
        assert len(resp.files) == 2


# ═══════════════════════════════════════════════════════════════════════════
# 2. GitHubClient error handling tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGitHubAPIError:
    """Error class for GitHub API failures."""

    def test_basic_error(self):
        err = GitHubAPIError("Not found", status_code=404)
        assert err.status_code == 404
        assert err.retryable is False
        assert err.rate_limited is False
        assert str(err) == "Not found"

    def test_retryable_error(self):
        err = GitHubAPIError("Server error", status_code=500, retryable=True)
        assert err.retryable is True

    def test_rate_limited_error(self):
        err = GitHubAPIError("Rate limited", status_code=403, retryable=True, rate_limited=True)
        assert err.rate_limited is True


class TestGitHubClient:
    """Low-level client tests using mocked HTTP responses."""

    def test_client_headers(self):
        client = GitHubClient("test-token")
        assert client._headers["Authorization"] == "Bearer test-token"
        assert "application/vnd.github+json" in client._headers["Accept"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. GitHubSourceService tests (mocked)
# ═══════════════════════════════════════════════════════════════════════════


class TestGitHubSourceServiceAuthorization:
    """Authorization boundary tests."""

    def test_missing_repository_raises(self):
        """Requesting a repo that doesn't exist returns 404."""
        from app.integrations.github.service import GitHubSourceService

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        service = GitHubSourceService(mock_db)

        from app.core.errors import APIError
        with pytest.raises(APIError) as exc_info:
            service._get_authorized_repository(uuid4(), uuid4())
        assert exc_info.value.status_code == 404

    def test_missing_installation_raises(self):
        """Missing installation returns 404."""
        from app.integrations.github.service import GitHubSourceService
        from app.core.errors import APIError

        mock_db = MagicMock()
        mock_db.get.return_value = None

        service = GitHubSourceService(mock_db)
        with pytest.raises(APIError) as exc_info:
            service._get_installation(uuid4())
        assert exc_info.value.status_code == 404


class TestLanguageDetection:
    """File-extension to language mapping."""

    def test_python_file(self):
        from app.integrations.github.service import GitHubSourceService
        assert GitHubSourceService._detect_language("src/main.py") == "Python"

    def test_javascript_file(self):
        from app.integrations.github.service import GitHubSourceService
        assert GitHubSourceService._detect_language("app.js") == "JavaScript"

    def test_typescript_file(self):
        from app.integrations.github.service import GitHubSourceService
        assert GitHubSourceService._detect_language("component.tsx") == "TypeScript"

    def test_unknown_extension(self):
        from app.integrations.github.service import GitHubSourceService
        assert GitHubSourceService._detect_language("file.xyz") is None

    def test_no_extension(self):
        from app.integrations.github.service import GitHubSourceService
        assert GitHubSourceService._detect_language("README") is None

    def test_dockerfile(self):
        from app.integrations.github.service import GitHubSourceService
        assert GitHubSourceService._detect_language("Dockerfile") == "Dockerfile"

    def test_makefile(self):
        from app.integrations.github.service import GitHubSourceService
        assert GitHubSourceService._detect_language("Makefile") == "Makefile"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Service method tests with mocked GitHub API
# ═══════════════════════════════════════════════════════════════════════════


class FakeRepository:
    """Minimal repository stand-in for tests."""

    def __init__(self):
        self.id = uuid4()
        self.user_id = uuid4()
        self.installation_id = uuid4()
        self.owner = "test-org"
        self.name = "test-repo"
        self.default_branch = "main"
        self.github_repo_id = "12345"


class FakeInstallation:
    """Minimal installation stand-in for tests."""

    def __init__(self, installation_id: str = "inst-123"):
        self.id = uuid4()
        self.installation_id = installation_id


class TestServiceFileContent:
    """GitHubSourceService.get_file_content tests."""

    @pytest.mark.asyncio
    async def test_successful_file_retrieval(self):
        from app.integrations.github.service import GitHubSourceService

        repo = FakeRepository()
        installation = FakeInstallation()

        content = "print('hello world')\n"
        encoded = base64.b64encode(content.encode()).decode()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(GitHubClient, "get_file_content", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "type": "file",
                    "content": encoded,
                    "encoding": "base64",
                    "sha": "blobsha123",
                    "size": len(content),
                }
                result = await service.get_file_content(
                    repo.id,
                    repo.user_id,
                    FileContentRequest(path="main.py"),
                )

        assert isinstance(result, FileContentResponse)
        assert result.content == content
        assert result.language == "Python"
        assert result.sha == "blobsha123"
        assert result.source_reference is not None
        assert result.source_reference.file_path == "main.py"

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        from app.integrations.github.service import GitHubSourceService
        from app.core.errors import APIError

        repo = FakeRepository()
        installation = FakeInstallation()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(
                GitHubClient,
                "get_file_content",
                new_callable=AsyncMock,
                side_effect=GitHubAPIError("Not found", status_code=404),
            ):
                with pytest.raises(APIError) as exc_info:
                    await service.get_file_content(
                        repo.id,
                        repo.user_id,
                        FileContentRequest(path="nonexistent.py"),
                    )
                assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_line_range_extraction(self):
        from app.integrations.github.service import GitHubSourceService

        repo = FakeRepository()
        installation = FakeInstallation()

        # 5 lines of content
        lines = ["line1\n", "line2\n", "line3\n", "line4\n", "line5\n"]
        content = "".join(lines)
        encoded = base64.b64encode(content.encode()).decode()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(GitHubClient, "get_file_content", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "type": "file",
                    "content": encoded,
                    "encoding": "base64",
                    "sha": "sha",
                    "size": len(content),
                }
                result = await service.get_file_content(
                    repo.id,
                    repo.user_id,
                    FileContentRequest(path="f.py", start_line=2, end_line=4),
                )

        # Lines 2–4 (inclusive)
        assert result.content == "line2\nline3\nline4\n"
        assert result.source_reference.start_line == 2
        assert result.source_reference.end_line == 4

    @pytest.mark.asyncio
    async def test_directory_rejected(self):
        from app.integrations.github.service import GitHubSourceService
        from app.core.errors import APIError

        repo = FakeRepository()
        installation = FakeInstallation()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(GitHubClient, "get_file_content", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {"type": "dir"}
                with pytest.raises(APIError) as exc_info:
                    await service.get_file_content(
                        repo.id,
                        repo.user_id,
                        FileContentRequest(path="src"),
                    )
                assert exc_info.value.status_code == 400


class TestServiceFileTree:
    """GitHubSourceService.get_file_tree tests."""

    @pytest.mark.asyncio
    async def test_successful_tree_retrieval(self):
        from app.integrations.github.service import GitHubSourceService

        repo = FakeRepository()
        installation = FakeInstallation()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(GitHubClient, "get_file_tree", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "sha": "treesha",
                    "tree": [
                        {"path": "src/main.py", "type": "blob", "size": 100, "sha": "s1"},
                        {"path": "src", "type": "tree", "sha": "s2"},
                        {"path": "README.md", "type": "blob", "size": 50, "sha": "s3"},
                    ],
                    "truncated": False,
                }
                result = await service.get_file_tree(repo.id, repo.user_id)

        assert isinstance(result, FileTreeResponse)
        assert len(result.entries) == 3
        assert result.sha == "treesha"
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_empty_tree(self):
        from app.integrations.github.service import GitHubSourceService

        repo = FakeRepository()
        installation = FakeInstallation()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(GitHubClient, "get_file_tree", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {"sha": "s", "tree": [], "truncated": False}
                result = await service.get_file_tree(repo.id, repo.user_id)

        assert result.entries == []


class TestServiceCommits:
    """GitHubSourceService commit retrieval tests."""

    @pytest.mark.asyncio
    async def test_list_commits(self):
        from app.integrations.github.service import GitHubSourceService

        repo = FakeRepository()
        installation = FakeInstallation()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(GitHubClient, "list_commits", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = [
                    {
                        "sha": "abc123",
                        "commit": {
                            "message": "Test commit",
                            "author": {"name": "Dev", "email": "dev@test.com"},
                            "committer": {"name": "Dev", "email": "dev@test.com"},
                        },
                        "parents": [],
                    },
                ]
                result = await service.list_commits(repo.id, repo.user_id)

        assert isinstance(result, CommitListResponse)
        assert len(result.commits) == 1
        assert result.commits[0].sha == "abc123"

    @pytest.mark.asyncio
    async def test_commit_detail(self):
        from app.integrations.github.service import GitHubSourceService

        repo = FakeRepository()
        installation = FakeInstallation()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(GitHubClient, "get_commit", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "sha": "abc123",
                    "commit": {
                        "message": "Fix bug",
                        "author": {"name": "Dev"},
                        "committer": {"name": "Dev"},
                    },
                    "parents": [{"sha": "parent1"}],
                    "files": [
                        {
                            "filename": "fix.py",
                            "status": "modified",
                            "additions": 5,
                            "deletions": 2,
                            "changes": 7,
                            "patch": "@@ -1,5 +1,8 @@\n...",
                        }
                    ],
                    "stats": {"total": 7, "additions": 5, "deletions": 2},
                }
                result = await service.get_commit_detail(repo.id, repo.user_id, "abc123")

        assert isinstance(result, CommitDetail)
        assert len(result.files) == 1
        assert result.files[0].filename == "fix.py"
        assert result.parents == ["parent1"]

    @pytest.mark.asyncio
    async def test_commit_not_found(self):
        from app.integrations.github.service import GitHubSourceService
        from app.core.errors import APIError

        repo = FakeRepository()
        installation = FakeInstallation()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(
                GitHubClient,
                "get_commit",
                new_callable=AsyncMock,
                side_effect=GitHubAPIError("Not found", status_code=404),
            ):
                with pytest.raises(APIError) as exc_info:
                    await service.get_commit_detail(repo.id, repo.user_id, "nonexistent")
                assert exc_info.value.status_code == 404


class TestServicePullRequests:
    """GitHubSourceService PR retrieval tests."""

    @pytest.mark.asyncio
    async def test_pr_diff_retrieval(self):
        from app.integrations.github.service import GitHubSourceService

        repo = FakeRepository()
        installation = FakeInstallation()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(GitHubClient, "get_pull_request", new_callable=AsyncMock) as mock_pr:
                mock_pr.return_value = {
                    "number": 42,
                    "title": "Add feature",
                    "state": "open",
                    "user": {"login": "parth"},
                    "base": {"ref": "main", "sha": "base_sha"},
                    "head": {"ref": "feature", "sha": "head_sha"},
                    "body": "Description",
                }
                with patch.object(GitHubClient, "get_pull_request_files", new_callable=AsyncMock) as mock_files:
                    mock_files.return_value = [
                        {
                            "filename": "new_file.py",
                            "status": "added",
                            "additions": 20,
                            "deletions": 0,
                            "changes": 20,
                            "patch": "@@ +1,20 @@\n...",
                        },
                        {
                            "filename": "existing.py",
                            "status": "modified",
                            "additions": 5,
                            "deletions": 3,
                            "changes": 8,
                            "patch": "@@ -1,10 +1,12 @@\n...",
                        },
                    ]
                    result = await service.get_pull_request_diff(repo.id, repo.user_id, 42)

        assert isinstance(result, PullRequestDiffResponse)
        assert result.pull_request.number == 42
        assert result.pull_request.author == "parth"
        assert len(result.files) == 2
        assert result.total_additions == 25
        assert result.total_deletions == 3
        assert result.total_changes == 28

    @pytest.mark.asyncio
    async def test_pr_not_found(self):
        from app.integrations.github.service import GitHubSourceService
        from app.core.errors import APIError

        repo = FakeRepository()
        installation = FakeInstallation()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(
                GitHubClient,
                "get_pull_request",
                new_callable=AsyncMock,
                side_effect=GitHubAPIError("Not found", status_code=404),
            ):
                with pytest.raises(APIError) as exc_info:
                    await service.get_pull_request_diff(repo.id, repo.user_id, 999)
                assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_pull_requests(self):
        from app.integrations.github.service import GitHubSourceService

        repo = FakeRepository()
        installation = FakeInstallation()

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = repo
        mock_db.get.return_value = installation

        service = GitHubSourceService(mock_db)

        with patch.object(GitHubClient, "get_installation_token", new_callable=AsyncMock, return_value="fake-token"):
            with patch.object(GitHubClient, "list_pull_requests", new_callable=AsyncMock) as mock_list:
                mock_list.return_value = [
                    {
                        "number": 1,
                        "title": "First PR",
                        "state": "open",
                        "user": {"login": "dev"},
                        "base": {"ref": "main"},
                        "head": {"ref": "feature"},
                    },
                ]
                result = await service.list_pull_requests(repo.id, repo.user_id)

        assert len(result) == 1
        assert result[0].number == 1


# ═══════════════════════════════════════════════════════════════════════════
# 5. API route contract tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGitHubSourceRoutes:
    """API endpoint contract tests for GitHub source integration."""

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

    def test_unauthenticated_source_tree_returns_401(self, monkeypatch):
        """Source endpoints require authentication."""
        self._setup_auth(monkeypatch)
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        repo_id = str(uuid4())
        response = client.get(f"/api/v1/repositories/{repo_id}/source/tree")
        assert response.status_code == 401

    def test_unauthenticated_file_returns_401(self, monkeypatch):
        """File content endpoint requires authentication."""
        self._setup_auth(monkeypatch)
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        repo_id = str(uuid4())
        response = client.get(f"/api/v1/repositories/{repo_id}/source/file?path=main.py")
        assert response.status_code == 401

    def test_unauthenticated_commits_returns_401(self, monkeypatch):
        """Commits endpoint requires authentication."""
        self._setup_auth(monkeypatch)
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        repo_id = str(uuid4())
        response = client.get(f"/api/v1/repositories/{repo_id}/source/commits")
        assert response.status_code == 401

    def test_unauthenticated_pulls_returns_401(self, monkeypatch):
        """Pull requests endpoint requires authentication."""
        self._setup_auth(monkeypatch)
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        repo_id = str(uuid4())
        response = client.get(f"/api/v1/repositories/{repo_id}/source/pulls")
        assert response.status_code == 401

    def test_file_content_missing_path_returns_422(self, monkeypatch):
        """File content endpoint requires a 'path' query parameter."""
        self._setup_auth(monkeypatch)
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.security import create_access_token

        token, _ = create_access_token(str(uuid4()))
        client = TestClient(app, raise_server_exceptions=False)
        repo_id = str(uuid4())
        response = client.get(
            f"/api/v1/repositories/{repo_id}/source/file",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422
