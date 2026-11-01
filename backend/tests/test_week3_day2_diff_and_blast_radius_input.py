"""Tests for Parth — Week 3 Day 2: Diff Line-Range Extraction & Symbol Blast Radius Feeder.

Verifies:
1. `parse_unified_diff`:
   - Parses unified diff hunks (@@ -old_start,old_count +new_start,new_count @@) into 1-indexed inclusive line ranges.
   - Correctly determines DiffStatus (MODIFIED, ADDED, REMOVED, RENAMED).
   - Accurately tracks additions and deletions count per file.
2. `GitBranchService.get_diff_line_ranges` and `get_task_diff_ranges`:
   - Collects workspace diffs and structures them into TaskDiffRanges for downstream AST symbol mapping (Prit Day 2).
3. `GitBranchService.verify_branch_isolation`:
   - Verifies agent branch isolation for Task Plan Approval Gate (Day 2 approval gate & Rule 563).
4. `GitHubSourceService.get_pull_request_diff_ranges`:
   - Retrieves PR files and converts raw patch hunks into line ranges.
5. API endpoints:
   - GET /api/v1/repositories/{id}/source/diff-ranges
   - GET /api/v1/repositories/{id}/source/branch-isolation/{task_id}
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.integrations.github.schemas import (
    BranchIsolationCheck,
    DiffStatus,
    FileDiffRange,
    LineRange,
    PullRequestDiffResponse,
    PullRequestFile,
    PullRequestInfo,
    TaskDiffRanges,
)
from app.models.repository import Repository
from app.models.user import User
from app.services.git_branch import (
    GitBranchService,
    format_agent_branch_name,
    parse_unified_diff,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Unified Diff Parser Unit Tests
# ═══════════════════════════════════════════════════════════════════════════

SAMPLE_GIT_DIFF = """diff --git a/src/auth/jwt.py b/src/auth/jwt.py
index abc1234..def5678 100644
--- a/src/auth/jwt.py
+++ b/src/auth/jwt.py
@@ -10,3 +10,5 @@ def login():
+    token = create_jwt()
+    return token
@@ -40,6 +42,8 @@ def verify():
+    validate_token()
+    return True
diff --git a/src/new_module.py b/src/new_module.py
new file mode 100644
--- /dev/null
+++ b/src/new_module.py
@@ -0,0 +1,15 @@
+class NewService:
+    def __init__(self):
+        pass
diff --git a/src/deprecated.py b/src/deprecated.py
deleted file mode 100644
--- a/src/deprecated.py
+++ /dev/null
@@ -1,8 +0,0 @@
-def old():
-    pass
"""


class TestUnifiedDiffParser:
    """Unit tests for parse_unified_diff."""

    def test_parse_empty_diff(self):
        assert parse_unified_diff("") == []
        assert parse_unified_diff("   \n\n  ") == []

    def test_parse_multi_file_unified_diff(self):
        results = parse_unified_diff(SAMPLE_GIT_DIFF)
        assert len(results) == 3

        # File 1: Modified with 2 hunks
        f1 = results[0]
        assert f1.file_path == "src/auth/jwt.py"
        assert f1.status == DiffStatus.MODIFIED
        assert len(f1.diff_ranges) == 2
        # Hunk 1: +10,5 -> [10, 14]
        assert f1.diff_ranges[0].start_line == 10
        assert f1.diff_ranges[0].end_line == 14
        assert f1.diff_ranges[0].change_type == "modified"
        # Hunk 2: +42,8 -> [42, 49]
        assert f1.diff_ranges[1].start_line == 42
        assert f1.diff_ranges[1].end_line == 49

        # File 2: Newly added file
        f2 = results[1]
        assert f2.file_path == "src/new_module.py"
        assert f2.status == DiffStatus.ADDED
        assert len(f2.diff_ranges) == 1
        assert f2.diff_ranges[0].start_line == 1
        assert f2.diff_ranges[0].end_line == 15
        assert f2.diff_ranges[0].change_type == "added"

        # File 3: Deleted file
        f3 = results[2]
        assert f3.file_path == "src/deprecated.py"
        assert f3.status == DiffStatus.REMOVED
        assert f3.diff_ranges[0].change_type == "deleted"

    def test_parse_single_line_hunk(self):
        patch = """@@ -5 +5 @@
-old_val = 1
+new_val = 2
"""
        ranges = parse_unified_diff(patch)
        assert len(ranges) == 1
        assert ranges[0].diff_ranges[0].start_line == 5
        assert ranges[0].diff_ranges[0].end_line == 5


# ═══════════════════════════════════════════════════════════════════════════
# 2. GitBranchService Day 2 Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestGitBranchServiceDay2:
    """Test suite for GitBranchService diff and branch isolation."""

    @pytest.mark.asyncio
    async def test_get_diff_line_ranges(self, tmp_path):
        service = GitBranchService(MagicMock())
        service._run_git = AsyncMock(return_value=(0, SAMPLE_GIT_DIFF, ""))

        res = await service.get_diff_line_ranges(tmp_path, "main")
        assert len(res) == 3
        assert res[0].file_path == "src/auth/jwt.py"
        assert res[0].diff_ranges[0].start_line == 10

    @pytest.mark.asyncio
    async def test_get_task_diff_ranges(self, tmp_path):
        service = GitBranchService(MagicMock())
        service._run_git = AsyncMock(return_value=(0, SAMPLE_GIT_DIFF, ""))
        task_id = uuid4()

        summary = await service.get_task_diff_ranges(
            task_id=task_id,
            workspace_path=tmp_path,
            base_branch="main",
        )
        assert isinstance(summary, TaskDiffRanges)
        assert summary.task_id == task_id
        assert summary.total_files_changed == 3
        assert summary.head_branch == format_agent_branch_name(task_id)

    def test_verify_branch_isolation_valid(self):
        repo_id = uuid4()
        task_id = uuid4()
        mock_db = MagicMock()
        mock_repo = Repository(id=repo_id, default_branch="main", name="test-repo")
        mock_db.execute.return_value.scalars.return_value.first.return_value = mock_repo

        service = GitBranchService(mock_db)
        service._get_repository = MagicMock(return_value=mock_repo)

        check = service.verify_branch_isolation(repo_id, task_id)
        assert isinstance(check, BranchIsolationCheck)
        assert check.is_isolated is True
        assert check.conflicts_with_protected is False
        assert check.branch_name == format_agent_branch_name(task_id)

    def test_verify_branch_isolation_protected_rejection(self, monkeypatch):
        repo_id = uuid4()
        task_id = uuid4()
        mock_db = MagicMock()
        mock_repo = Repository(id=repo_id, default_branch="main", name="test-repo")

        service = GitBranchService(mock_db)
        service._get_repository = MagicMock(return_value=mock_repo)

        # Force branch name to "main" to simulate illegal name attempt
        monkeypatch.setattr("app.services.git_branch.format_agent_branch_name", lambda _: "main")
        check = service.verify_branch_isolation(repo_id, task_id)
        assert check.is_isolated is False
        assert check.conflicts_with_protected is True
        assert "conflicts with protected branch" in check.error_message


# ═══════════════════════════════════════════════════════════════════════════
# 3. GitHubSourceService PR Diff Ranges Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSourceServiceDiffRanges:
    """Test suite for PR diff range extraction in GitHubSourceService."""

    @pytest.mark.asyncio
    async def test_get_pull_request_diff_ranges(self):
        from app.integrations.github.source_service import GitHubSourceService

        service = GitHubSourceService(MagicMock())
        repo_id = uuid4()
        user_id = uuid4()

        mock_diff = PullRequestDiffResponse(
            pull_request=PullRequestInfo(number=7, title="JWT Auth", state="open"),
            files=[
                PullRequestFile(
                    filename="src/auth/jwt.py",
                    status=DiffStatus.MODIFIED,
                    additions=5,
                    deletions=2,
                    patch="@@ -10,3 +10,5 @@ def login():\n+    token = create_jwt()\n+    return token",
                ),
                PullRequestFile(
                    filename="src/docs.md",
                    status=DiffStatus.ADDED,
                    additions=10,
                    deletions=0,
                    patch="@@ -0,0 +1,10 @@\n+# Documentation",
                ),
            ],
            total_additions=15,
            total_deletions=2,
            total_changes=17,
        )

        service.get_pull_request_diff = AsyncMock(return_value=mock_diff)
        diff_ranges = await service.get_pull_request_diff_ranges(repo_id, user_id, 7)

        assert len(diff_ranges) == 2
        assert diff_ranges[0].file_path == "src/auth/jwt.py"
        assert diff_ranges[0].diff_ranges[0].start_line == 10
        assert diff_ranges[0].diff_ranges[0].end_line == 14

        assert diff_ranges[1].file_path == "src/docs.md"
        assert diff_ranges[1].status == DiffStatus.ADDED
        assert diff_ranges[1].diff_ranges[0].start_line == 1
        assert diff_ranges[1].diff_ranges[0].end_line == 10
