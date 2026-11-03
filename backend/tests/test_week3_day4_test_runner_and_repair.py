"""Comprehensive tests for Week 3 Day 4: Restricted Test Execution & Bounded Auto-Fix.

Validates:
- Command allowlist enforcement (pytest, unittest, npm test allowed; arbitrary shell rejected).
- Execution timeout killing and bounded output limits.
- Classification between test failures and infrastructure errors.
- Secret redaction and log sanitization.
- Bounded repair loop with strict 3-attempt ceiling.
- Confinement of workspace patches (no path traversal).
- Integration with GitBranchService revision tracking and API endpoints.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

os.environ["JWT_SECRET"] = "test-jwt-secret-for-week3-day4-runner-tests-12345"

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.security import create_access_token
from app.integrations.github.schemas import (
    RepairExecutionRequest,
    RepairExecutionResponse,
    TestRunnerRequest,
    TestRunnerResponse,
    WorkspaceStatusResponse,
)
from app.main import app
from app.models.repository import Repository
from app.models.user import User
from app.services.git_branch import GitBranchService
from app.services.repair_loop import (
    MAX_TASK_REPAIR_ATTEMPTS,
    BoundedRepairManager,
    RepairEligibility,
)
from app.services.test_runner import (
    CommandPolicyValidator,
    RestrictedExecutionResult,
    RestrictedTestRunner,
    TestCounts,
)

TestRunnerRequest.__test__ = False
TestRunnerResponse.__test__ = False
TestCounts.__test__ = False


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary initialized Git repository workspace with standard tests."""
    ws = tmp_path / "test_workspace"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@test.local"], cwd=ws, check=True, capture_output=True)

    # Initial passing test file using unittest
    init_file = ws / "test_sample.py"
    init_file.write_text(
        "import unittest\n\n"
        "class SampleTestCase(unittest.TestCase):\n"
        "    def test_ok(self):\n"
        "        self.assertTrue(True)\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=ws, check=True, capture_output=True)
    return ws


# ===========================================================================
# 1. Command Allowlist & Policy Validation Tests
# ===========================================================================

class TestCommandPolicyValidation:
    def test_permitted_commands_pass(self):
        """Allowlisted commands with valid arguments are accepted."""
        assert CommandPolicyValidator.validate_command("pytest") == ["pytest"]
        assert CommandPolicyValidator.validate_command("pytest tests/ -v") == ["pytest", "tests/", "-v"]
        assert CommandPolicyValidator.validate_command("python -m unittest discover") == ["python", "-m", "unittest", "discover"]
        assert CommandPolicyValidator.validate_command("npm test") == ["npm", "test"]
        assert CommandPolicyValidator.validate_command("cargo test --lib") == ["cargo", "test", "--lib"]

    def test_arbitrary_shell_commands_rejected(self):
        """Disallowed commands like rm, curl, bash, powershell are rejected."""
        disallowed = [
            "rm -rf /",
            "curl https://malicious.com",
            "bash -c 'echo pwned'",
            "powershell -Command Get-Process",
            "cat /etc/passwd",
        ]
        for cmd in disallowed:
            with pytest.raises(APIError) as exc_info:
                CommandPolicyValidator.validate_command(cmd)
            assert exc_info.value.status_code == 400
            assert exc_info.value.code == ErrorCode.COMMAND_NOT_ALLOWED

    def test_shell_metacharacters_rejected(self):
        """Shell injection characters like ;, |, &, >, <, ` are strictly blocked."""
        injections = [
            "pytest; rm -rf /",
            "pytest && echo hack",
            "pytest | grep fail",
            "pytest > output.txt",
            "pytest `whoami`",
            "pytest $(id)",
        ]
        for cmd in injections:
            with pytest.raises(APIError) as exc_info:
                CommandPolicyValidator.validate_command(cmd)
            assert exc_info.value.status_code == 400
            assert exc_info.value.code == ErrorCode.COMMAND_NOT_ALLOWED

    def test_path_traversal_in_arguments_rejected(self):
        """Path traversal arguments are blocked."""
        traversal_cmds = [
            "pytest ../../../etc/passwd",
            "pytest ..\\test.py",
            "pytest C:\\Windows\\System32",
        ]
        for cmd in traversal_cmds:
            with pytest.raises(APIError) as exc_info:
                CommandPolicyValidator.validate_command(cmd)
            assert exc_info.value.status_code == 400
            assert exc_info.value.code == ErrorCode.COMMAND_NOT_ALLOWED


# ===========================================================================
# 2. Restricted Test Runner Execution Tests
# ===========================================================================

class TestRestrictedTestRunner:
    @pytest.mark.asyncio
    async def test_run_passing_test(self, temp_workspace: Path):
        """Running a passing test command inside workspace succeeds with PASSED status."""
        runner = RestrictedTestRunner(default_timeout=15.0)
        result = await runner.run_tests(
            workspace_path=temp_workspace,
            command="python -m unittest discover -s . -p test_sample.py",
        )
        assert result.status == "PASSED"
        assert result.exit_code == 0
        assert not result.timed_out
        assert not result.is_infrastructure_error
        assert result.workspace_revision is not None

    @pytest.mark.asyncio
    async def test_run_failing_test(self, temp_workspace: Path):
        """Failing test assertions result in FAILED status with parsed counts."""
        fail_file = temp_workspace / "test_fail.py"
        fail_file.write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_err(self): self.assertEqual(1, 2)\n",
            encoding="utf-8",
        )
        runner = RestrictedTestRunner(default_timeout=15.0)
        result = await runner.run_tests(
            workspace_path=temp_workspace,
            command="python -m unittest discover -s . -p test_fail.py",
        )
        assert result.status == "FAILED"
        assert result.exit_code != 0
        assert result.test_counts.failed >= 1

    @pytest.mark.asyncio
    async def test_execution_timeout_kills_process(self, temp_workspace: Path):
        """Commands exceeding timeout are killed and return TIMEOUT status."""
        slow_file = temp_workspace / "test_slow.py"
        slow_file.write_text(
            "import time\nimport unittest\nclass T(unittest.TestCase):\n    def test_slow(self): time.sleep(10)\n",
            encoding="utf-8",
        )
        runner = RestrictedTestRunner(default_timeout=1.0)
        result = await runner.run_tests(
            workspace_path=temp_workspace,
            command="python -m unittest discover -s . -p test_slow.py",
            timeout_seconds=1.0,
        )
        assert result.status == "TIMEOUT"
        assert result.timed_out is True
        assert "timed out" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_infrastructure_error_classification(self, temp_workspace: Path):
        """Syntax errors or missing test modules are classified as INFRASTRUCTURE_ERROR."""
        bad_syntax = temp_workspace / "test_broken.py"
        bad_syntax.write_text("def broken syntax in python ???", encoding="utf-8")

        runner = RestrictedTestRunner(default_timeout=10.0)
        result = await runner.run_tests(
            workspace_path=temp_workspace,
            command="python -m unittest discover -s . -p test_broken.py",
        )
        assert result.status == "INFRASTRUCTURE_ERROR"
        assert result.is_infrastructure_error is True

    @pytest.mark.asyncio
    async def test_secret_redaction_in_output(self, temp_workspace: Path):
        """Tokens or secrets printed in test logs are redacted."""
        secret_file = temp_workspace / "test_secret.py"
        secret_file.write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_s(self):\n        print('github_pat_11ABCD12345678901234567890')\n",
            encoding="utf-8",
        )
        runner = RestrictedTestRunner(default_timeout=10.0)
        result = await runner.run_tests(
            workspace_path=temp_workspace,
            command="python -m unittest discover -s . -p test_secret.py",
        )
        assert "github_pat_11ABCD12345678901234567890" not in result.stdout
        assert "[REDACTED" in result.stdout


# ===========================================================================
# 3. Bounded Self-Repair Loop Tests
# ===========================================================================

class TestBoundedRepairLoop:
    def test_repair_eligibility_rules(self):
        """Repair eligibility respects ceilings, security stops, and infra failures."""
        manager = BoundedRepairManager()
        task_id = uuid4()

        # 1. Normal failure with budget is eligible
        elig = manager.evaluate_eligibility(task_id, test_status="FAILED", explicit_attempts_used=0)
        assert elig.is_eligible is True
        assert elig.attempts_remaining == 3

        # 2. Passed test is not eligible for repair
        elig = manager.evaluate_eligibility(task_id, test_status="PASSED", explicit_attempts_used=0)
        assert elig.is_eligible is False
        assert elig.stop_workflow is False

        # 3. Security violation immediately stops workflow
        elig = manager.evaluate_eligibility(task_id, test_status="FAILED", has_security_violation=True)
        assert elig.is_eligible is False
        assert elig.stop_workflow is True

        # 4. Infrastructure error stops automated repair
        elig = manager.evaluate_eligibility(task_id, test_status="INFRASTRUCTURE_ERROR", is_infrastructure_error=True)
        assert elig.is_eligible is False
        assert elig.stop_workflow is True

        # 5. Budget exhausted after 3 attempts
        elig = manager.evaluate_eligibility(task_id, test_status="FAILED", explicit_attempts_used=3)
        assert elig.is_eligible is False
        assert elig.attempts_remaining == 0
        assert elig.stop_workflow is True

    @pytest.mark.asyncio
    async def test_patch_path_traversal_prevention(self, temp_workspace: Path):
        """Repair manager rejects path traversal targets."""
        manager = BoundedRepairManager()
        with pytest.raises(APIError) as exc_info:
            await manager.apply_workspace_patch(
                workspace_path=temp_workspace,
                target_file="../../outside.py",
                new_content="print('hacked')",
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_full_repair_cycle_and_budget_exhaustion(self, temp_workspace: Path):
        """Attempt 1, 2, 3 run and increment budget; attempt 4 is blocked."""
        manager = BoundedRepairManager()
        task_id = uuid4()

        test_file = temp_workspace / "test_target.py"
        test_file.write_text("import unittest\nclass T(unittest.TestCase):\n    def test_x(self): self.fail()\n")

        # Initial commit of failing test
        subprocess.run(["git", "add", "."], cwd=temp_workspace, check=True)
        subprocess.run(["git", "commit", "-m", "add failing test"], cwd=temp_workspace, check=True)

        # Attempt 1: still failing
        rec1 = await manager.execute_repair_attempt(
            task_id=task_id,
            workspace_path=temp_workspace,
            diagnosis="Assertion failure in test_x",
            target_file="test_target.py",
            new_content="import unittest\nclass T(unittest.TestCase):\n    def test_x(self): self.fail()\n",
            test_command="python -m unittest discover -s . -p test_target.py",
        )
        assert rec1.attempt_number == 1
        assert rec1.success is False
        assert manager.get_attempts_used(task_id) == 1

        # Attempt 2: still failing
        rec2 = await manager.execute_repair_attempt(
            task_id=task_id,
            workspace_path=temp_workspace,
            diagnosis="Second attempt",
            target_file="test_target.py",
            new_content="import unittest\nclass T(unittest.TestCase):\n    def test_x(self): self.fail()\n",
            test_command="python -m unittest discover -s . -p test_target.py",
        )
        assert rec2.attempt_number == 2
        assert manager.get_attempts_used(task_id) == 2

        # Attempt 3: fix it!
        rec3 = await manager.execute_repair_attempt(
            task_id=task_id,
            workspace_path=temp_workspace,
            diagnosis="Fix assertion",
            target_file="test_target.py",
            new_content="import unittest\nclass T(unittest.TestCase):\n    def test_x(self): self.assertTrue(True)\n",
            test_command="python -m unittest discover -s . -p test_target.py",
        )
        assert rec3.attempt_number == 3
        assert rec3.success is True
        assert rec3.test_result.status == "PASSED"
        assert manager.get_attempts_used(task_id) == 3

        # Attempt 4: strictly rejected because budget exhausted
        with pytest.raises(APIError) as exc_info:
            await manager.execute_repair_attempt(
                task_id=task_id,
                workspace_path=temp_workspace,
                diagnosis="Exceeded attempt",
                target_file="test_target.py",
                new_content="import unittest",
                test_command="python -m unittest discover -s . -p test_target.py",
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == ErrorCode.RETRY_BUDGET_EXHAUSTED


# ===========================================================================
# 4. GitBranchService Day 4 Integration Tests
# ===========================================================================

class TestGitBranchWorkspaceStatus:
    @pytest.mark.asyncio
    async def test_get_workspace_revision_and_status(self, temp_workspace: Path):
        """GitBranchService correctly inspects workspace git revision and clean status."""
        service = GitBranchService(MagicMock())
        rev = await service.get_workspace_revision(temp_workspace)
        assert rev is not None
        assert len(rev) == 40

        status = await service.get_workspace_status(temp_workspace)
        assert status["is_clean"] is True
        assert status["revision"] == rev
        assert "master" in status["branch"] or "main" in status["branch"]

        # Modify a file
        (temp_workspace / "test_sample.py").write_text("modified", encoding="utf-8")
        status_dirty = await service.get_workspace_status(temp_workspace)
        assert status_dirty["is_clean"] is False
        assert "test_sample.py" in status_dirty["modified_files"]


# ===========================================================================
# 5. API Endpoint Tests
# ===========================================================================

class TestDay4Endpoints:
    @pytest.fixture
    def client_and_repo(self, temp_workspace: Path):
        user_id = uuid4()
        repo_id = uuid4()
        mock_db = MagicMock()

        user = User(
            id=user_id,
            login="lead",
            github_id="gh-lead-12345",
            email="lead@ai-platform.local",
        )
        repo = Repository(
            id=repo_id,
            user_id=user_id,
            name="test-repo",
            owner="test-owner",
            default_branch="main",
            installation_id=uuid4(),
        )

        def mock_execute(stmt):
            res = MagicMock()
            res.scalar_one_or_none.return_value = repo
            return res

        mock_db.execute = mock_execute
        mock_db.get.return_value = repo

        app.dependency_overrides[get_db] = lambda: mock_db
        test_client = TestClient(app)

        from app.core.config import get_settings
        get_settings.cache_clear()
        
        with patch("app.core.security.get_settings") as mock_sec_settings, \
             patch("app.core.auth.get_settings") as mock_auth_settings, \
             patch("app.core.auth.get_redis") as mock_redis:
            
            mock_s = MagicMock()
            mock_s.jwt_secret = "test-jwt-secret-key-12345"
            mock_s.access_token_expire_seconds = 3600
            mock_s.jwt_expire_minutes = 60
            mock_s.jwt_algorithm = "HS256"
            mock_sec_settings.return_value = mock_s
            mock_auth_settings.return_value = mock_s
            mock_redis.return_value.exists.return_value = False

            token, _ = create_access_token(str(user_id))
            auth_headers = {"Authorization": f"Bearer {token}"}

            yield test_client, repo_id, temp_workspace, auth_headers
            app.dependency_overrides.clear()

    def test_run_tests_endpoint(self, client_and_repo):
        """POST /{repository_id}/source/task-workspace/tests executes tests."""
        client, repo_id, workspace_path, auth_headers = client_and_repo
        task_id = str(uuid4())

        resp = client.post(
            f"/api/v1/repositories/{repo_id}/source/task-workspace/tests",
            json={
                "task_id": task_id,
                "command": "python -m unittest discover -s . -p test_sample.py",
                "timeout_seconds": 15.0,
                "workspace_path": str(workspace_path),
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == task_id
        assert data["status"] == "PASSED"
        assert data["exit_code"] == 0

    def test_workspace_status_endpoint(self, client_and_repo):
        """GET /{repository_id}/source/task-workspace/status/{task_id} returns git status."""
        client, repo_id, workspace_path, auth_headers = client_and_repo
        task_id = str(uuid4())

        resp = client.get(
            f"/api/v1/repositories/{repo_id}/source/task-workspace/status/{task_id}?workspace_path={workspace_path}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == task_id
        assert data["is_clean"] is True
        assert len(data["revision"]) == 40
