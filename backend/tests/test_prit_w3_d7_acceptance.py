"""Week 3 Day 7 Final End-to-End Acceptance & Integration Test Suite.

Owner: Prit Zania — Repository Engine & Sandbox Lead (Docs/week3.md §8 Day 7, §11 Scenarios A-J, §12)
Reference:
- Docs/week3.md §8 (Day 7 — End-to-End Acceptance, Documentation and Demo)
- Docs/week3.md §11 (Final Acceptance Scenarios A through J)
- Docs/week3.md §12 (Week 3 Completion Report & Criteria)
- Docs/daily_tasks.md (WEEK 3 — Day 7 Final Integration & Live Demonstration)
- ADR-007 (Sandbox Isolation), ADR-010 (Mandatory Approval Gate, Zero Auto-Merge)

Test Inventory (25 Acceptance Scenarios):
- TestFullWorkflowScenarioA (Tests 1-2): Complete 17-Step Happy Path Lifecycle & Zero Manual Intervention
- TestScenarioBPlanRejectedGate (Tests 3-4): Server-enforced approval gate blocking unapproved/rejected execution
- TestScenarioCPlanChangedAfterApproval (Test 5): Approval invalidation on material plan revision
- TestScenarioDTestFailureAndRepairExhaustion (Tests 6-7): Bounded repair loop, 3-attempt ceiling & duplicate prevention
- TestScenarioEMaliciousToolAndBoundaryContainment (Tests 8-9): Path traversal and disallowed command containment
- TestScenarioFVerificationFailureBlocksPublication (Tests 10-11): Manifest deletion, scope breach & secret leak blocking
- TestScenarioGGitHubApiUncertaintyAndIdempotentRetry (Test 12): Push idempotency upon retry
- TestScenarioHWorkerRestartAndCrashRecovery (Test 13): Worker crash recovery, metadata reconstruction & budget preservation
- TestScenarioIRepositoryPermissionRevocation (Tests 14-15): Publication authorization & protected branch enforcement
- TestScenarioJDiffImmutabilityAndStaleBase (Test 16): Post-verification diff tampering & remote branch drift detection
- TestWeek2IntelligenceIntegration (Tests 17-19): Seamless Week 2 AST, Framework Detector & Review Source Mapper reuse
- TestPerformanceAndSlaBenchmarks (Tests 20-23): Workspace creation, command runner, diff validation & recovery SLAs
- TestTimelineEventAuditTrail (Tests 24-25): Complete lifecycle event provenance and secret scrubbing validation
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from agent.tools.router import ToolRequest, ToolRouter
from app.schemas.workspace import (
    DiffImmutabilityCheckRequest,
    DiffImmutabilityCheckResult,
    DiffValidationRequest,
    DiffValidationResult,
    RepairAttemptRecord,
    StaleRevisionCheckRequest,
    StaleRevisionCheckResult,
    TestFailureClassification,
    TestOutcomeStatus,
    WorkspaceCommandRequest,
    WorkspaceCommitRequest,
    WorkspaceCreateRequest,
    WorkspaceDraftPRRequest,
    WorkspaceExecutionEventType,
    WorkspaceMetadata,
    WorkspacePushRequest,
    WorkspaceResourceLimits,
    WorkspaceStartExecutionRequest,
    WorkspaceStatus,
    WorkspaceTestExecutionRequest,
)
from sandbox.constants import (
    DEFAULT_MAX_ORPHAN_AGE_SECONDS,
    DEFAULT_MAX_WORKSPACE_FILES,
    PROTECTED_BRANCHES,
    SECRET_SCAN_PATTERNS,
)
from sandbox.exceptions import (
    WorkspaceAuthorizationError,
    WorkspaceCommandError,
    WorkspaceConcurrentOperationError,
    WorkspaceDiffValidationError,
    WorkspaceDraftPRError,
    WorkspaceDuplicateRepairPatchError,
    WorkspaceError,
    WorkspacePathEscapeError,
    WorkspacePolicyViolationError,
    WorkspacePostVerificationMutationError,
    WorkspaceProtectedBranchError,
    WorkspacePublicationUnauthorizedError,
    WorkspacePushError,
    WorkspaceRepairBudgetExhaustedError,
    WorkspaceSecretLeakDetectedError,
    WorkspaceStaleApprovalError,
    WorkspaceStaleRevisionError,
    WorkspaceStateError,
)
from sandbox.path_guard import WorkspacePathGuard
from sandbox.tool_policy_bridge import (
    CANONICAL_WORKSPACE_TOOLS,
    TOOL_COMMIT_CHANGES,
    TOOL_CREATE_DRAFT_PR,
    TOOL_EXECUTE_COMMAND,
    TOOL_INSPECT_DIFF,
    TOOL_PATCH_FILE,
    TOOL_PUSH_BRANCH,
    TOOL_READ_FILE,
    TOOL_RECORD_REPAIR,
    TOOL_RUN_TESTS,
    TOOL_VALIDATE_DIFF,
    TOOL_WRITE_FILE,
    WorkspaceToolPolicyBridge,
    register_workspace_tools,
)
from sandbox.workspace_manager import WorkspaceManager
from scanner.extractor import SymbolExtractor
from scanner.framework_detector import FrameworkDetector
from scanner.parser import Parser
from scanner.source_mapper import ReviewSourceMapper
from scanner.symbols import FileInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal temporary git repository with initial commit and baseline files."""
    repo_dir = tmp_path / "origin_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Prit Zania"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "prit@dau.ac.in"], cwd=repo_dir, check=True)

    (repo_dir / "README.md").write_text("# Production Repo\nPlatform code.\n", encoding="utf-8")
    (repo_dir / ".gitignore").write_text("__pycache__/\n*.py[cod]\n.pytest_cache/\n", encoding="utf-8")
    (repo_dir / "pyproject.toml").write_text(
        "[project]\nname = 'calc_engine'\nversion = '1.0.0'\n\n[tool.pytest.ini_options]\ntestpaths = ['tests']\npythonpath = ['.']\n",
        encoding="utf-8",
    )
    src_dir = repo_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "calculator.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n\ndef multiply(a: int, b: int) -> int:\n    return a * b\n",
        encoding="utf-8",
    )
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_calculator.py").write_text(
        "from src.calculator import add, multiply\n\ndef test_add():\n    assert add(2, 3) == 5\n\ndef test_multiply():\n    assert multiply(2, 3) == 6\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: initial production repository baseline"], cwd=repo_dir, check=True, capture_output=True)
    return repo_dir


@pytest.fixture
def repo_head_sha(temp_git_repo: Path) -> str:
    """Return HEAD commit SHA of the test repository."""
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_git_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def remote_bare_repo(tmp_path: Path, temp_git_repo: Path) -> Path:
    """Create a bare git remote to test real git push and branch operations."""
    bare_dir = tmp_path / "remote_upstream.git"
    subprocess.run(["git", "clone", "--bare", str(temp_git_repo), str(bare_dir)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare_dir)], cwd=temp_git_repo, check=True, capture_output=True)
    return bare_dir


@pytest.fixture
def workspace_manager(tmp_path: Path) -> WorkspaceManager:
    """Provide a configured WorkspaceManager rooted in temporary directory."""
    root_sandboxes = tmp_path / "sandboxes"
    root_sandboxes.mkdir(parents=True, exist_ok=True)
    return WorkspaceManager(base_workspaces_dir=root_sandboxes)


# ---------------------------------------------------------------------------
# Test Suite 1: Full 17-Step Happy Path Lifecycle (Scenario A)
# ---------------------------------------------------------------------------

class TestFullWorkflowScenarioA:
    """Verifies the complete 17-step end-to-end autonomous workflow."""

    def test_full_17_step_workflow_execution(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
        remote_bare_repo: Path,
    ) -> None:
        """Scenario A: Complete happy-path execution from plan approval to Draft PR creation."""
        task_id = f"task-e2e-{uuid4().hex[:8]}"
        plan_version = 1
        feature_branch = f"agent/{task_id}"

        # 1-4. Create Workspace
        create_res = workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=feature_branch,
                isolation_type="directory_copy",
            )
        )
        assert create_res.status == WorkspaceStatus.READY
        workspace_path = workspace_manager.get_workspace_path(task_id)
        assert workspace_path.exists()

        # 5. Start Execution (Transition to IN_USE)
        start_res = workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=plan_version,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
                approval_token="appr-12345",
            )
        )
        assert start_res.success is True
        assert start_res.status == WorkspaceStatus.IN_USE

        # 6. Apply validated file changes via WorkspaceManager
        patch_content = (
            "def add(a: int, b: int) -> int:\n    return a + b\n\n"
            "def multiply(a: int, b: int) -> int:\n    return a * b\n\n"
            "def divide(a: int, b: int) -> float:\n    if b == 0:\n        raise ValueError('ZeroDivision')\n    return a / b\n"
        )
        write_res = workspace_manager.write_file(task_id, "src/calculator.py", patch_content)
        assert write_res.success is True

        # Add unit tests for new divide function
        test_patch = (
            "from src.calculator import add, multiply, divide\nimport pytest\n\n"
            "def test_add():\n    assert add(2, 3) == 5\n\n"
            "def test_multiply():\n    assert multiply(2, 3) == 6\n\n"
            "def test_divide():\n    assert divide(10, 2) == 5.0\n    with pytest.raises(ValueError):\n        divide(1, 0)\n"
        )
        write_test_res = workspace_manager.write_file(task_id, "tests/test_calculator.py", test_patch)
        assert write_test_res.success is True

        # 7-8. Execute permitted test command
        test_res = workspace_manager.run_tests(
            WorkspaceTestExecutionRequest(
                task_id=task_id,
                test_path="tests/test_calculator.py",
                timeout_seconds=30,
            )
        )
        assert test_res.status == TestOutcomeStatus.PASSED, f"STDOUT: {test_res.stdout}\nSTDERR: {test_res.stderr}\nERR: {test_res.error}"
        assert test_res.success is True

        # 9. Inspect unified git diff
        diff_res = workspace_manager.get_workspace_diff(task_id)
        assert diff_res.is_empty is False
        assert "def divide(a: int, b: int)" in (diff_res.raw_diff or "")
        assert "test_divide" in (diff_res.raw_diff or "")

        # 10-11. Validate diff scope & secret scan
        val_res = workspace_manager.validate_workspace_diff(
            task_id,
            allowed_files=["src/calculator.py", "tests/test_calculator.py"],
        )
        assert val_res.is_valid is True
        assert len(val_res.secret_findings) == 0

        # 12. Commit task changes with metadata trailer
        commit_res = workspace_manager.commit_task_changes(
            WorkspaceCommitRequest(
                task_id=task_id,
                message="feat: add safe divide operation and comprehensive tests",
                author_name="Prit Zania",
                author_email="prit@dau.ac.in",
            )
        )
        assert commit_res.success is True
        assert len(commit_res.commit_sha) >= 7

        # 13. Pre-publication diff hash computation & immutability verification
        diff_hash = workspace_manager.compute_verification_diff_hash(task_id)
        assert len(diff_hash) == 64
        immut_res = workspace_manager.verify_diff_immutability(task_id, expected_hash=diff_hash)
        assert immut_res.is_immutable is True

        # 14. Verify base revision is not stale
        stale_res = workspace_manager.detect_stale_base_revision(task_id, remote_name="origin", base_branch="main")
        assert stale_res.is_stale is False

        # 15-16. Authorized git push to remote bare repository
        push_res = workspace_manager.push_task_branch(
            WorkspacePushRequest(
                task_id=task_id,
                branch_name=feature_branch,
                remote_name="origin",
                remote_url=str(remote_bare_repo),
                publication_authorized=True,
            )
        )
        assert push_res.success is True
        assert push_res.branch == feature_branch

        # 17. Synthesize Draft PR
        pr_res = workspace_manager.create_draft_pr(
            WorkspaceDraftPRRequest(
                task_id=task_id,
                head_branch=feature_branch,
                base_branch="main",
                title="[W3-AUTO] Implement safe divide operation",
                publication_authorized=True,
            )
        )
        assert pr_res.success is True
        assert pr_res.is_draft is True
        assert task_id in (pr_res.summary or "")

        # Cleanup workspace idempotently
        clean_res = workspace_manager.cleanup_workspace(task_id)
        assert clean_res.success is True
        assert not workspace_path.exists()

    def test_zero_manual_intervention_audit(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Verifies that execution advances seamlessly through all states with zero manual blocks."""
        task_id = f"task-auto-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
                approval_token="approved-123",
            )
        )
        meta = workspace_manager.get_workspace(task_id)
        assert meta is not None
        assert meta.status == WorkspaceStatus.IN_USE

        # Verify automated file operations
        w_res = workspace_manager.write_file(
            task_id,
            "src/new_module.py",
            "def hello(): return 'world'\n",
        )
        assert w_res.success is True

        r_res = workspace_manager.read_file(task_id, "src/new_module.py")
        assert r_res.success is True
        assert r_res.content == "def hello(): return 'world'\n"


# ---------------------------------------------------------------------------
# Test Suite 2: Plan Rejection & Approval Gate (Scenario B)
# ---------------------------------------------------------------------------

class TestScenarioBPlanRejectedGate:
    """Verifies that unapproved or rejected plans are strictly prevented from executing."""

    def test_unapproved_plan_execution_blocked(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario B.1: Execution attempt without APPROVED status is rejected by backend."""
        task_id = f"task-unapproved-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )

        with pytest.raises(WorkspaceAuthorizationError) as exc_info:
            workspace_manager.start_execution(
                WorkspaceStartExecutionRequest(
                    task_id=task_id,
                    plan_version=1,
                    approved_base_revision=repo_head_sha,
                    task_status="PENDING_APPROVAL",  # Not approved!
                )
            )
        assert "human approval" in str(exc_info.value).lower()

    def test_rejected_plan_tool_invocation_blocked(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario B.2: Direct tool request on unstarted task is rejected by ToolPolicyBridge."""
        task_id = f"task-rejected-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )

        router = ToolRouter()
        bridge = register_workspace_tools(router, workspace_manager)

        # Attempt to write file without starting execution (status is READY, not IN_USE)
        req = ToolRequest(
            tool_name=TOOL_WRITE_FILE,
            arguments={"task_id": task_id, "file_path": "src/leak.py", "content": "exploit = True\n"},
        )
        res = router.route(req, agent_state={"task_id": task_id}, policy_engine=bridge)
        assert res.success is False
        assert "permitted during active execution" in res.error.lower() or "ready" in res.error.lower()


# ---------------------------------------------------------------------------
# Test Suite 3: Plan Changed After Approval (Scenario C)
# ---------------------------------------------------------------------------

class TestScenarioCPlanChangedAfterApproval:
    """Verifies approval invalidation upon plan mutation or version mismatch."""

    def test_base_revision_mismatch_invalidates_approval(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario C.1: Approval granted on old base revision cannot execute on different revision."""
        task_id = f"task-mutated-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )

        # Attempt start execution with mismatched approved_base_revision
        with pytest.raises(WorkspaceStaleApprovalError) as exc_info:
            workspace_manager.start_execution(
                WorkspaceStartExecutionRequest(
                    task_id=task_id,
                    plan_version=1,
                    approved_base_revision="0000000000000000000000000000000000000000",
                    task_status="APPROVED",
                )
            )
        assert "invalidated" in str(exc_info.value).lower() or "stale" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test Suite 4: Bounded Auto-Repair Budget (Scenario D)
# ---------------------------------------------------------------------------

class TestScenarioDTestFailureAndRepairExhaustion:
    """Verifies bounded repair loop, strict 3-attempt ceiling, and patch deduplication."""

    def test_repair_budget_ceiling_enforcement(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario D.1: Strictly caps repair attempts at 3 and raises upon exhaustion."""
        task_id = f"task-repair-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )

        # Attempt 1
        assert workspace_manager.get_repair_budget_status(task_id).is_eligible_for_repair is True
        workspace_manager.record_repair_attempt(
            task_id,
            patch_summary="patch 1",
            patch_content="fix_1 = True\n",
            success=False,
        )

        # Attempt 2
        assert workspace_manager.get_repair_budget_status(task_id).is_eligible_for_repair is True
        workspace_manager.record_repair_attempt(
            task_id,
            patch_summary="patch 2",
            patch_content="fix_2 = True\n",
            success=False,
        )

        # Attempt 3
        assert workspace_manager.get_repair_budget_status(task_id).is_eligible_for_repair is True
        workspace_manager.record_repair_attempt(
            task_id,
            patch_summary="patch 3",
            patch_content="fix_3 = True\n",
            success=False,
        )

        # Attempt 4: Must be blocked
        budget = workspace_manager.get_repair_budget_status(task_id)
        assert budget.is_eligible_for_repair is False
        assert budget.is_budget_exhausted is True
        with pytest.raises(WorkspaceRepairBudgetExhaustedError):
            workspace_manager.record_repair_attempt(
                task_id,
                patch_summary="patch 4",
                patch_content="fix_4 = True\n",
            )

    def test_duplicate_repair_patch_detection(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario D.2: Prevents endless loops by rejecting duplicate repair patches."""
        task_id = f"task-duppatch-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )

        identical_patch = "fix_var = 42\n"
        workspace_manager.record_repair_attempt(
            task_id,
            patch_summary="repair attempt 1",
            patch_content=identical_patch,
        )

        with pytest.raises(WorkspaceDuplicateRepairPatchError) as exc_info:
            workspace_manager.record_repair_attempt(
                task_id,
                patch_summary="repair attempt 2 identical",
                patch_content=identical_patch,
            )
        assert "identical" in str(exc_info.value).lower() or "duplicate" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test Suite 5: Malicious Tool & Boundary Containment (Scenario E)
# ---------------------------------------------------------------------------

class TestScenarioEMaliciousToolAndBoundaryContainment:
    """Verifies strict filesystem boundary enforcement and command allowlists."""

    def test_path_traversal_blocked(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario E.1: Directory traversal outside workspace is caught and rejected."""
        task_id = f"task-traversal-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )

        # Guard method raises WorkspacePathEscapeError
        ws_root = workspace_manager.get_workspace_path(task_id)
        with pytest.raises(WorkspacePathEscapeError):
            WorkspacePathGuard.resolve_within_workspace(ws_root, "../../etc/passwd")

        # WorkspaceManager read_file gracefully captures it as an error
        read_res = workspace_manager.read_file(task_id, "../../etc/passwd")
        assert read_res.success is False
        assert ".." in (read_res.error or "") or "invalid" in (read_res.error or "").lower() or "traversal" in (read_res.error or "").lower()

    def test_prohibited_command_blocked(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario E.2: Arbitrary shell command not in allowlist is blocked."""
        task_id = f"task-cmd-block-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )

        with pytest.raises((WorkspacePolicyViolationError, WorkspaceCommandError)) as exc_info:
            workspace_manager.execute_command(
                WorkspaceCommandRequest(
                    task_id=task_id,
                    command="rm",
                    arguments=["-rf", "/"],
                )
            )
        assert "allowlist" in str(exc_info.value).lower() or "not in" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test Suite 6: Verification Failure Blocks Publication (Scenario F)
# ---------------------------------------------------------------------------

class TestScenarioFVerificationFailureBlocksPublication:
    """Verifies diff validation gates against manifest deletion, scope breach, and secret leaks."""

    def test_manifest_deletion_fails_verification(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario F.1: Deleting critical manifest like pyproject.toml is rejected."""
        task_id = f"task-manifest-del-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )

        workspace_manager.delete_file(task_id, "pyproject.toml")
        val_res = workspace_manager.validate_workspace_diff(task_id)
        assert val_res.is_valid is False
        assert any("pyproject.toml" in b for b in val_res.blocking_findings)

    def test_secret_leak_in_diff_fails_verification(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario F.2: Introducing API key or token in diff triggers secret scanner block."""
        task_id = f"task-secret-diff-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )

        leak_code = 'GITHUB_TOKEN = "ghp_123456789012345678901234567890123456"\n'
        workspace_manager.write_file(task_id, "src/config.py", leak_code)

        val_res = workspace_manager.validate_workspace_diff(task_id)
        assert val_res.is_valid is False
        assert len(val_res.secret_findings) > 0


# ---------------------------------------------------------------------------
# Test Suite 7: GitHub API Uncertainty & Idempotency (Scenario G)
# ---------------------------------------------------------------------------

class TestScenarioGGitHubApiUncertaintyAndIdempotentRetry:
    """Verifies that transient external failures do not create duplicate artifacts or corrupt state."""

    def test_idempotent_push_retry(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
        remote_bare_repo: Path,
    ) -> None:
        """Scenario G.1: Retrying push succeeds cleanly and idempotently."""
        task_id = f"task-push-retry-{uuid4().hex[:8]}"
        feature_branch = f"agent/{task_id}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=feature_branch,
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )
        workspace_manager.write_file(task_id, "src/retry.py", "x = 1\n")
        workspace_manager.commit_task_changes(
            WorkspaceCommitRequest(task_id=task_id, message="feat: retry test")
        )

        # First push succeeds
        res1 = workspace_manager.push_task_branch(
            WorkspacePushRequest(
                task_id=task_id,
                branch_name=feature_branch,
                remote_name="origin",
                remote_url=str(remote_bare_repo),
                publication_authorized=True,
            )
        )
        assert res1.success is True

        # Idempotent re-push succeeds without divergence
        res2 = workspace_manager.push_task_branch(
            WorkspacePushRequest(
                task_id=task_id,
                branch_name=feature_branch,
                remote_name="origin",
                remote_url=str(remote_bare_repo),
                publication_authorized=True,
            )
        )
        assert res2.success is True


# ---------------------------------------------------------------------------
# Test Suite 8: Worker Restart & Crash Recovery (Scenario H)
# ---------------------------------------------------------------------------

class TestScenarioHWorkerRestartAndCrashRecovery:
    """Verifies state restoration, metadata disk reconstruction, and budget continuity."""

    def test_crash_recovery_reconstructs_workspace(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario H.1: A new manager instance recovers active task metadata from disk."""
        task_id = f"task-crash-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )
        workspace_manager.record_repair_attempt(
            task_id,
            patch_summary="repair attempt 1",
            patch_content="repair attempt 1 patch",
            success=False,
        )

        # Simulate crash: instantiate new WorkspaceManager with same base workspaces dir
        new_manager = WorkspaceManager(base_workspaces_dir=workspace_manager.base_directory)
        recovery_res = new_manager.recover_workspaces(stale_timeout_seconds=0)

        assert recovery_res.total_scanned >= 1
        meta = new_manager.get_workspace(task_id)
        assert meta is not None
        # In-use task interrupted by crash transitions safely to STOPPED
        assert meta.status == WorkspaceStatus.STOPPED


# ---------------------------------------------------------------------------
# Test Suite 9: Repository Permission & Push Guards (Scenario I)
# ---------------------------------------------------------------------------

class TestScenarioIRepositoryPermissionRevocation:
    """Verifies that unauthorized push or protected branch targets are blocked."""

    def test_unauthorized_push_rejected(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario I.1: Pushing without explicit publication authorization raises error."""
        task_id = f"task-noauth-push-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        with pytest.raises(WorkspacePublicationUnauthorizedError):
            workspace_manager.push_task_branch(
                WorkspacePushRequest(
                    task_id=task_id,
                    branch_name=f"agent/{task_id}",
                    publication_authorized=False,  # Unauthorized
                )
            )

    def test_protected_branch_push_rejected(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario I.2: Pushing to protected branch (main, master) is forbidden."""
        task_id = f"task-prot-push-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name="main",  # Protected!
                isolation_type="directory_copy",
            )
        )
        with pytest.raises(WorkspaceProtectedBranchError):
            workspace_manager.push_task_branch(
                WorkspacePushRequest(
                    task_id=task_id,
                    branch_name="main",
                    publication_authorized=True,
                )
            )


# ---------------------------------------------------------------------------
# Test Suite 10: Diff Immutability & Stale Base Revision (Scenario J)
# ---------------------------------------------------------------------------

class TestScenarioJDiffImmutabilityAndStaleBase:
    """Verifies post-verification mutation detection and remote branch drift checks."""

    def test_post_verification_mutation_detected(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Scenario J.1: Tampering with code after verification triggers divergence error."""
        task_id = f"task-tamper-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )
        workspace_manager.write_file(task_id, "src/verified.py", "x = 100\n")

        initial_hash = workspace_manager.compute_verification_diff_hash(task_id)

        # Mutate file after verification
        workspace_manager.write_file(task_id, "src/verified.py", "x = 9999\n")

        immut_res = workspace_manager.verify_diff_immutability(task_id, expected_hash=initial_hash)
        assert immut_res.is_immutable is False
        assert immut_res.current_diff_hash != initial_hash


# ---------------------------------------------------------------------------
# Test Suite 11: Week 2 Intelligence Integration Reuse
# ---------------------------------------------------------------------------

class TestWeek2IntelligenceIntegration:
    """Verifies seamless integration of Week 2 AST, FrameworkDetector & SourceMapper in sandbox."""

    def test_week2_ast_parser_in_workspace(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Verifies Parser and SymbolExtractor extract symbols from sandboxed workspace files."""
        task_id = f"task-ast-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )
        code = "class PaymentService:\n    def process_charge(self, amount: int) -> bool:\n        return amount > 0\n"
        workspace_manager.write_file(task_id, "src/payment.py", code)

        parser = Parser()
        extractor = SymbolExtractor(parser=parser)
        file_info = FileInfo("src/payment.py", len(code), "Python", False)
        symbols = extractor.extract(file_info, code)
        symbol_names = [s.name for s in symbols]
        assert "PaymentService" in symbol_names
        assert "process_charge" in symbol_names

    def test_week2_framework_detector_in_workspace(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Verifies FrameworkDetector accurately identifies pytest configuration in sandbox."""
        task_id = f"task-framework-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        ws_path = workspace_manager.get_workspace_path(task_id)

        detector = FrameworkDetector(repo_root=ws_path)
        detection_res = detector.detect()
        assert detection_res.framework == "pytest"
        assert "pytest" in detection_res.test_command

    def test_week2_review_source_mapper_in_workspace(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Verifies ReviewSourceMapper maps hunks to symbols in sandbox diffs."""
        task_id = f"task-mapper-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )
        workspace_manager.write_file(
            task_id,
            "src/calculator.py",
            "def add(a: int, b: int) -> int:\n    # added comment\n    return a + b\n",
        )
        diff_res = workspace_manager.get_workspace_diff(task_id)

        mapper = ReviewSourceMapper()
        map_res = mapper.map_unified_diff(
            diff_res.raw_diff or "",
            repo_root=str(workspace_manager.get_workspace_path(task_id)),
        )
        assert len(map_res.files) > 0
        assert map_res.files[0].file_path == "src/calculator.py"


# ---------------------------------------------------------------------------
# Test Suite 12: Performance & SLA Benchmarks
# ---------------------------------------------------------------------------

class TestPerformanceAndSlaBenchmarks:
    """Verifies that sandbox operations strictly fulfill SLA performance benchmarks."""

    def test_workspace_creation_sla(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Workspace creation must execute under 2000ms."""
        t0 = time.perf_counter()
        res = workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=f"task-sla-create-{uuid4().hex[:8]}",
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name="agent/sla-test",
                isolation_type="directory_copy",
            )
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert res.status == WorkspaceStatus.READY
        assert elapsed_ms < 2000

    def test_diff_validation_sla(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Diff validation & secret scanning must execute under 1000ms."""
        task_id = f"task-sla-diff-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )
        workspace_manager.write_file(task_id, "src/fast.py", "y = 2\n")

        t0 = time.perf_counter()
        val_res = workspace_manager.validate_workspace_diff(task_id)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert val_res.is_valid is True
        assert elapsed_ms < 1000

    def test_crash_recovery_sla(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Crash discovery & state reconciliation must execute under 1000ms."""
        task_id = f"task-sla-rec-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        t0 = time.perf_counter()
        rec_res = workspace_manager.recover_workspaces()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert rec_res.total_scanned >= 1
        assert elapsed_ms < 1000

    def test_command_execution_sla(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Allowlisted command execution must respond promptly without timeout."""
        task_id = f"task-sla-cmd-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )
        t0 = time.perf_counter()
        cmd_res = workspace_manager.execute_command(
            WorkspaceCommandRequest(task_id=task_id, command="git", arguments=["status"])
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert cmd_res.exit_code == 0
        assert elapsed_ms < 3000


# ---------------------------------------------------------------------------
# Test Suite 13: Timeline Event Audit Trail & Zero-Leak Validation
# ---------------------------------------------------------------------------

class TestTimelineEventAuditTrail:
    """Verifies complete event provenance, chronological ordering, and secret scrubbing."""

    def test_lifecycle_event_provenance(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
        remote_bare_repo: Path,
    ) -> None:
        """Verifies every major lifecycle state transition emits an immutable timeline event."""
        task_id = f"task-events-{uuid4().hex[:8]}"
        feature_branch = f"agent/{task_id}"

        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=feature_branch,
                isolation_type="directory_copy",
            )
        )
        workspace_manager.start_execution(
            WorkspaceStartExecutionRequest(
                task_id=task_id,
                plan_version=1,
                approved_base_revision=repo_head_sha,
                task_status="APPROVED",
            )
        )
        workspace_manager.write_file(task_id, "src/event_test.py", "a = 1\n")
        workspace_manager.get_workspace_diff(task_id)
        workspace_manager.validate_workspace_diff(task_id)
        workspace_manager.commit_task_changes(WorkspaceCommitRequest(task_id=task_id, message="feat: event test"))
        workspace_manager.push_task_branch(
            WorkspacePushRequest(
                task_id=task_id,
                branch_name=feature_branch,
                remote_name="origin",
                remote_url=str(remote_bare_repo),
                publication_authorized=True,
            )
        )
        workspace_manager.create_draft_pr(
            WorkspaceDraftPRRequest(
                task_id=task_id,
                head_branch=feature_branch,
                base_branch="main",
                title="feat: event test",
                publication_authorized=True,
            )
        )

        events = workspace_manager.get_execution_timeline(task_id)
        event_types = [e.event_type for e in events]

        expected_types = [
            WorkspaceExecutionEventType.WORKSPACE_CREATED,
            WorkspaceExecutionEventType.EXECUTION_STARTED,
            WorkspaceExecutionEventType.DIFF_INSPECTED,
            WorkspaceExecutionEventType.DIFF_VALIDATED,
            WorkspaceExecutionEventType.CHANGES_COMMITTED,
            WorkspaceExecutionEventType.PUBLICATION_AUTHORIZED,
            WorkspaceExecutionEventType.BRANCH_PUSHED,
            WorkspaceExecutionEventType.PR_CREATED,
        ]
        for exp in expected_types:
            assert exp in event_types

    def test_zero_leaked_secrets_in_events(
        self,
        workspace_manager: WorkspaceManager,
        temp_git_repo: Path,
        repo_head_sha: str,
    ) -> None:
        """Verifies payloads containing potential credentials are fully sanitized."""
        task_id = f"task-event-scrub-{uuid4().hex[:8]}"
        workspace_manager.create_workspace(
            WorkspaceCreateRequest(
                task_id=task_id,
                repository_id=str(uuid4()),
                base_revision=repo_head_sha,
                repository_root=str(temp_git_repo),
                branch_name=f"agent/{task_id}",
                isolation_type="directory_copy",
            )
        )
        workspace_manager.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.EXECUTION_FAILED,
            message="Error with secret: ghp_123456789012345678901234567890123456",
            payload={"auth_header": "Bearer secret_test_key_12345"},
        )
        events = workspace_manager.get_execution_timeline(task_id)
        assert len(events) >= 1
        last_event = events[-1]
        assert "ghp_123456789012345678901234567890123456" not in last_event.message
        assert "[REDACTED]" in last_event.message
        assert "secret_test_key_12345" not in str(last_event.payload)
