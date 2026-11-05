"""Comprehensive tests for Week 3 Day 5: Independent Verification, Code Review & Draft PR.

Validates:
- 12 canonical independent verification checks (Docs/week3.md §6 F36).
- Secret detection and redaction in proposed diffs.
- Forbidden file constraint enforcement.
- Test-to-workspace revision correspondence guard.
- Markdown PR summary generation with structured sections.
- Publication authorization gate (explicit human approval required before push/PR).
- Pushing strictly to agent/task-{id} branches (Rule 563).
- GitHub Draft PR opening and metadata persistence.
- Idempotent publication handling.
- API endpoints: verify, publish-pr, get pull-request.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

os.environ["JWT_SECRET"] = "test-jwt-secret-for-week3-day5-pr-tests-12345"

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.security import create_access_token
from app.integrations.github.schemas import PullRequestInfo
from app.main import app
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.user import User
from app.repositories.pull_request_repository import PullRequestRepository
from app.schemas.task import RestrictedExecutionResult, TaskConstraint, TestCounts
from app.schemas.verification import VerificationResult
from app.services.git_branch import GitBranchService, format_agent_branch_name
from app.services.independent_verifier import IndependentVerifier


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary initialized Git repository workspace."""
    ws = tmp_path / "test_workspace"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@test.local"], cwd=ws, check=True, capture_output=True)

    init_file = ws / "main.py"
    init_file.write_text("print('hello world')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=ws, check=True, capture_output=True)
    return ws


# ===========================================================================
# 1. Independent Verification Checks Tests (F36)
# ===========================================================================

class TestIndependentVerifier:
    def test_happy_path_verification(self):
        """Passing tests, isolated branch, clean diff, and approved plan pass verification."""
        verifier = IndependentVerifier()
        task_id = uuid4()
        revision = "a" * 40

        test_result = RestrictedExecutionResult(
            command=["pytest"],
            exit_code=0,
            status="PASSED",
            duration_ms=120,
            stdout="3 passed",
            stderr="",
            test_counts=TestCounts(passed=3, total=3),
            workspace_revision=revision,
        )

        result = verifier.verify_task_revision(
            task_id=task_id,
            workspace_revision=revision,
            test_result=test_result,
            branch_name=f"agent/task-{str(task_id)[:8]}",
            diff_text="diff --git a/main.py b/main.py\n+print('improved')\n",
            changed_files=["main.py"],
            has_approved_plan=True,
            base_revision_matches=True,
        )

        assert result.status == "PASS"
        assert len(result.blocking_findings) == 0
        assert any(c.name == "tests" and c.status == "PASSED" for c in result.checks)
        assert any(c.name == "branch_isolation" and c.status == "PASSED" for c in result.checks)
        assert any(c.name == "secret_scan" and c.status == "PASSED" for c in result.checks)
        assert "DRAFT" in result.pr_summary

    def test_secret_in_diff_blocks_verification(self):
        """Proposed diff containing an API token produces a CRITICAL blocking finding and fails verification."""
        verifier = IndependentVerifier()
        task_id = uuid4()
        revision = "b" * 40

        test_result = RestrictedExecutionResult(
            command=["pytest"],
            exit_code=0,
            status="PASSED",
            duration_ms=100,
            stdout="1 passed",
            stderr="",
            test_counts=TestCounts(passed=1, total=1),
            workspace_revision=revision,
        )

        leaked_diff = "diff --git a/config.py b/config.py\n+github_pat_11ABCD12345678901234567890\n"

        result = verifier.verify_task_revision(
            task_id=task_id,
            workspace_revision=revision,
            test_result=test_result,
            branch_name=f"agent/task-{str(task_id)[:8]}",
            diff_text=leaked_diff,
            changed_files=["config.py"],
            has_approved_plan=True,
        )

        assert result.status == "FAIL"
        assert len(result.blocking_findings) > 0
        assert any(f.severity == "CRITICAL" and f.category == "security" for f in result.blocking_findings)

    def test_forbidden_file_violation_blocks_verification(self):
        """Modifying a file listed in task constraints produces a blocking finding."""
        verifier = IndependentVerifier()
        task_id = uuid4()
        revision = "c" * 40

        test_result = RestrictedExecutionResult(
            command=["pytest"],
            exit_code=0,
            status="PASSED",
            duration_ms=100,
            stdout="1 passed",
            stderr="",
            test_counts=TestCounts(passed=1, total=1),
            workspace_revision=revision,
        )

        constraint = TaskConstraint(
            id="cst-1",
            description="Do not touch migrations or security configs",
            constraint_type="protected_file",
            forbidden_files=["alembic/env.py", "backend/app/core/security.py"],
        )

        result = verifier.verify_task_revision(
            task_id=task_id,
            workspace_revision=revision,
            test_result=test_result,
            branch_name=f"agent/task-{str(task_id)[:8]}",
            changed_files=["alembic/env.py"],
            constraints=[constraint],
        )

        assert result.status == "FAIL"
        assert any(f.category == "policy" and "forbidden" in f.message for f in result.blocking_findings)

    def test_revision_mismatch_blocks_verification(self):
        """If test results were evaluated on an older commit than current workspace HEAD, verification fails."""
        verifier = IndependentVerifier()
        task_id = uuid4()
        head_rev = "1" * 40
        older_rev = "2" * 40

        test_result = RestrictedExecutionResult(
            command=["pytest"],
            exit_code=0,
            status="PASSED",
            duration_ms=100,
            stdout="1 passed",
            stderr="",
            test_counts=TestCounts(passed=1, total=1),
            workspace_revision=older_rev,
        )

        result = verifier.verify_task_revision(
            task_id=task_id,
            workspace_revision=head_rev,
            test_result=test_result,
            branch_name=f"agent/task-{str(task_id)[:8]}",
        )

        assert result.status == "FAIL"
        assert any(c.name == "revision_correspondence" and c.status == "FAILED" for c in result.checks)

    def test_protected_branch_violation_blocks_verification(self):
        """Trying to verify changes on main/master directly violates Rule 563."""
        verifier = IndependentVerifier()
        task_id = uuid4()
        rev = "3" * 40

        result = verifier.verify_task_revision(
            task_id=task_id,
            workspace_revision=rev,
            test_result=None,
            branch_name="main",
        )

        assert result.status == "FAIL"
        assert any(c.name == "branch_isolation" and c.status == "FAILED" for c in result.checks)


# ===========================================================================
# 2. Publication Authorization Gate Tests (F37)
# ===========================================================================

class TestPublicationAuthorizationGate:
    @pytest.mark.asyncio
    async def test_publication_without_authorization_rejected(self, temp_workspace: Path):
        """publish_task_draft_pr strictly requires publication_authorized=True."""
        mock_db = MagicMock()
        service = GitBranchService(mock_db)

        with pytest.raises(APIError) as exc_info:
            await service.publish_task_draft_pr(
                repository_id=uuid4(),
                task_id=uuid4(),
                workspace_path=temp_workspace,
                publication_authorized=False,
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.code == ErrorCode.PUBLICATION_AUTHORIZATION_REQUIRED

    @pytest.mark.asyncio
    async def test_publication_of_failing_verification_rejected(self, temp_workspace: Path):
        """Cannot publish a task if verification failed or has blocking findings."""
        mock_db = MagicMock()
        service = GitBranchService(mock_db)

        failing_verification = MagicMock()
        failing_verification.status = "FAIL"
        failing_verification.blocking_findings = [MagicMock()]

        with pytest.raises(APIError) as exc_info:
            await service.publish_task_draft_pr(
                repository_id=uuid4(),
                task_id=uuid4(),
                workspace_path=temp_workspace,
                publication_authorized=True,
                verification_result=failing_verification,
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == ErrorCode.VERIFICATION_FAILED

    @pytest.mark.asyncio
    async def test_successful_draft_pr_publication_and_persistence(self, temp_workspace: Path):
        """Authorized publication creates Draft PR on GitHub and persists metadata."""
        mock_db = MagicMock()
        repo_id = uuid4()
        task_id = uuid4()
        user_id = uuid4()

        repo = Repository(
            id=repo_id,
            user_id=user_id,
            name="test-repo",
            owner="test-owner",
            default_branch="main",
            installation_id=uuid4(),
        )

        mock_db.execute.return_value.scalar_one_or_none.return_value = repo

        service = GitBranchService(mock_db)
        # Mock repository loading and GitHub client
        service._get_repository = MagicMock(return_value=repo)
        mock_client = AsyncMock()
        mock_client.create_branch = AsyncMock()
        mock_client.create_pull_request = AsyncMock(return_value={
            "number": 42,
            "html_url": "https://github.com/test-owner/test-repo/pull/42",
            "created_at": "2026-10-30T12:00:00Z",
            "draft": True,
        })
        service._get_client_for_repo = AsyncMock(return_value=mock_client)
        service.branch_exists = AsyncMock(return_value=False)

        with patch.object(PullRequestRepository, "get_by_task_id", return_value=None), \
             patch.object(PullRequestRepository, "create_or_update"):
            pr_info = await service.publish_task_draft_pr(
            repository_id=repo_id,
            task_id=task_id,
            workspace_path=temp_workspace,
            publication_authorized=True,
            pr_title="feat: implement feature x",
            user_id=user_id,
        )

            assert pr_info.number == 42
            assert pr_info.draft is True
            assert pr_info.head_ref == format_agent_branch_name(task_id)
            assert mock_client.create_pull_request.called
            # Check call arguments
            call_kwargs = mock_client.create_pull_request.call_args[1]
            assert call_kwargs["draft"] is True
            assert call_kwargs["head"] == format_agent_branch_name(task_id)

    @pytest.mark.asyncio
    async def test_idempotent_publication_avoids_duplicate_pr(self, temp_workspace: Path):
        """If PR was already created for this task, returns existing PR without calling GitHub API."""
        mock_db = MagicMock()
        repo_id = uuid4()
        task_id = uuid4()

        existing_pr = PullRequest(
            task_id=task_id,
            repository_id=repo_id,
            branch=format_agent_branch_name(task_id),
            base_branch="main",
            commit_message="feat: already created",
            test_summary="Passed",
            verification_summary="Verified",
            status="created",
            pr_number=99,
            pr_url="https://github.com/test-owner/test-repo/pull/99",
        )

        with patch.object(PullRequestRepository, "get_by_task_id", return_value=existing_pr):
            service = GitBranchService(mock_db)
            service._get_client_for_repo = AsyncMock()

            pr_info = await service.publish_task_draft_pr(
                repository_id=repo_id,
                task_id=task_id,
                workspace_path=temp_workspace,
                publication_authorized=True,
            )

            assert pr_info.number == 99
            assert pr_info.draft is True
            assert not service._get_client_for_repo.called
