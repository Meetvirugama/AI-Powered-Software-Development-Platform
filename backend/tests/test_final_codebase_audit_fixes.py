"""Final Post-Week-3 Codebase Deep-Sweep & Security Audit Regression Suite.

Verifies fixes for:
1. BUG-FINAL-01: RestrictedTestRunner resolves `pytest` via `[sys.executable, "-m", "pytest"]`
   and prepends workspace_path to PYTHONPATH so isolated workspace modules take precedence
   over the host platform's `PYTHONPATH=backend`.
2. VULN-FINAL-02: TaskExecutionOrchestrator (Step 8) and GitHub source task routes strictly
   block path traversal (`../`), protected system directories (`/etc`, `/usr`), and host
   platform repository targeting (`_REPO_ROOT`, `_REPO_ROOT/backend`, `_REPO_ROOT/frontend`).
3. VULN-FINAL-03: RateLimitMiddleware rules cover all Week 3 Day 3-7 GitHub source task
   mutation routes (`/source/task-branch/isolate`, `/source/task-branch/validate-base`,
   `/source/task-workspace/tests`, `/source/task-workspace/repair`, `/source/task/verify`,
   `/source/task/publish-pr`, `/source/task/recover`, `/source/task/cleanup`,
   `/source/task/execute-pipeline`).
4. BUG-FINAL-04: BoundedRepairManager awaits `git add` before spawning `git commit` and
   guards against unsafe workspace paths and option-flag target file names.
5. BUG-FINAL-05: Zero PytestCollectionWarnings on `TestCounts`, `TestRunnerRequest`,
   `TestRunnerResponse`, `TestGenerationResponse`, and `TestGenerationServiceProtocol`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai.interfaces import TestGenerationServiceProtocol
from app.core.errors import APIError, ErrorCode
from app.core.rate_limit import _rules
from app.integrations.github.schemas import TestRunnerRequest, TestRunnerResponse
from app.models.repository import Repository
from app.schemas.analysis import TestGenerationResponse
from app.services.git_branch import _REPO_ROOT
from app.services.repair_loop import BoundedRepairManager
from app.services.task_orchestrator import TaskExecutionOrchestrator
from app.services.test_runner import RestrictedTestRunner, TestCounts


def test_pytest_collection_flags_disabled_on_schema_and_protocol_classes() -> None:
    """Verify __test__ = False is set on non-test classes starting with 'Test'."""
    assert getattr(TestCounts, "__test__", None) is False
    assert getattr(TestRunnerRequest, "__test__", None) is False
    assert getattr(TestRunnerResponse, "__test__", None) is False
    assert getattr(TestGenerationResponse, "__test__", None) is False
    assert getattr(TestGenerationServiceProtocol, "__test__", None) is False


@pytest.mark.asyncio
async def test_restricted_test_runner_pytest_resolution_and_pythonpath_isolation(tmp_path: Path) -> None:
    """Verify RestrictedTestRunner runs `pytest` via sys.executable and imports workspace `app.py` over `backend/app`."""
    ws = tmp_path / "isolated_ws"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Agent"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@test.local"], cwd=ws, check=True, capture_output=True)

    # Create a workspace module named `app.py` (which would collide with `backend/app` if PYTHONPATH wasn't isolated)
    (ws / "app.py").write_text("def compute_value(x: int) -> int:\n    return x * 3\n", encoding="utf-8")
    (ws / "test_app.py").write_text(
        "from app import compute_value\n\n"
        "def test_compute_value():\n"
        "    assert compute_value(7) == 21\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=ws, check=True, capture_output=True)

    runner = RestrictedTestRunner(default_timeout=20.0)
    res = await runner.run_tests(workspace_path=ws, command="pytest")
    assert res.status == "PASSED"
    assert res.exit_code == 0
    assert res.test_counts.passed == 1
    assert not res.is_infrastructure_error


@pytest.mark.asyncio
async def test_restricted_test_runner_rejects_host_repo_and_system_paths() -> None:
    """Verify RestrictedTestRunner refuses to execute against host platform repo or /etc."""
    runner = RestrictedTestRunner()

    for forbidden_path in (_REPO_ROOT, _REPO_ROOT / "backend", Path("/etc")):
        with pytest.raises(APIError) as exc_info:
            await runner.run_tests(workspace_path=forbidden_path, command="pytest")
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == ErrorCode.INVALID_REQUEST


@pytest.mark.asyncio
async def test_task_orchestrator_blocks_path_traversal_target_file(tmp_path: Path) -> None:
    """Verify TaskExecutionOrchestrator rejects path traversal in target_file before touching disk."""
    orchestrator = TaskExecutionOrchestrator(MagicMock())

    for malicious_target in ("../../outside.py", "/etc/passwd", "../escape.py"):
        with pytest.raises(APIError) as exc_info:
            await orchestrator.execute_task_pipeline(
                repository_id=uuid4(),
                task_id=uuid4(),
                user_id=uuid4(),
                has_approved_plan=True,
                publication_authorized=False,
                base_revision="main",
                target_file=malicious_target,
                new_content="malicious",
                commit_message="fix: attempt escape",
                workspace_path=tmp_path / "ws",
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == ErrorCode.INVALID_REQUEST


@pytest.mark.asyncio
async def test_bounded_repair_manager_commits_staged_file_deterministically(tmp_path: Path) -> None:
    """Verify BoundedRepairManager awaits `git add` so the repaired file is committed to HEAD."""
    ws = tmp_path / "repair_ws"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Agent"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@test.local"], cwd=ws, check=True, capture_output=True)

    (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (ws / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "broken calc"], cwd=ws, check=True, capture_output=True)

    manager = BoundedRepairManager()
    rec = await manager.execute_repair_attempt(
        task_id=uuid4(),
        workspace_path=ws,
        diagnosis="Fix subtraction bug in add()",
        target_file="calc.py",
        new_content="def add(a, b):\n    return a + b\n",
        test_command="pytest",
    )
    assert rec.success is True
    assert rec.previous_revision != rec.new_revision

    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ws,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status_proc.stdout.strip() == ""


@pytest.mark.parametrize(
    "endpoint_suffix",
    [
        "task-branch/isolate",
        "task-branch/validate-base",
        "task-workspace/tests",
        "task-workspace/repair",
        "task/verify",
        "task/publish-pr",
        "task/recover",
        "task/cleanup",
        "task/execute-pipeline",
    ],
)
def test_rate_limit_rules_cover_all_week3_github_source_task_endpoints(endpoint_suffix: str) -> None:
    """Verify every Week 3 Day 3-7 GitHub source task POST route is covered by RateLimitMiddleware."""
    repo_id = uuid4()
    path = f"/api/v1/repositories/{repo_id}/source/{endpoint_suffix}"
    matching = [r for r in _rules("/api/v1") if "POST" in r.methods and r.path_pattern.match(path)]
    assert len(matching) == 1
    assert matching[0].name == "repo_source_task_ops"
    assert matching[0].limit == 20
    assert matching[0].window_seconds == 60
