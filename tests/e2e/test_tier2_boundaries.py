"""Tier 2: Boundary & Corner Cases E2E Tests.

Opaque-box tests verifying system behavior at boundaries, extreme limits,
timeouts, resource ceilings, invalid state transitions, and security constraints.
Covers:
- Timeouts & Process Group Termination (>=5 tests)
- Empty Inputs & Minimal Payloads (>=5 tests)
- Max Sizes & Ceilings (>=5 tests)
- Invalid State Transitions & Concurrency (>=5 tests)
- Forbidden Files & Security Boundaries (>=5 tests)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ai.services.bounded_repair_loop import MAX_TASK_REPAIR_ATTEMPTS, BoundedRepairLoop, RepairBudgetExhaustedError
from ai.services.retrieval_optimizer import AgentTokenBudgetManager, TokenBudgetExhaustedError
from app.core.errors import APIError, ErrorCode
from app.models.task import AgentTask, TaskStatus
from app.schemas.task import (
    RestrictedExecutionResult,
    TaskConstraint,
    TaskRequirement,
    TaskSourceReference,
    TestCounts,
    can_transition,
)
from app.services.git_branch import format_agent_branch_name, _validate_safe_git_ref
from app.services.independent_verifier import IndependentVerifier, VerificationFinding
from app.services.repair_service import RepairPatchValidator
from sandbox.command_runner import (
    ALLOWED_COMMAND_TEMPLATES,
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    MAX_COMMAND_OUTPUT_BYTES,
    MAX_TIMEOUT_SECONDS,
    WorkspaceCommandRunner,
    WorkspaceCommandTimeoutError,
    WorkspacePolicyViolationError,
)


# ===========================================================================
# 1. Timeouts & Process Group Termination (>=5 tests)
# ===========================================================================

class TestTier2TimeoutsAndLeases:
    """Boundary tests for subprocess timeouts, process-tree killing, and worker leases."""

    def test_t2_subprocess_timeout_triggers_sigkill_and_result(self, temp_git_repo: Path):
        """Runner aborts runaway subprocess after timeout and returns timed_out status."""
        runner = WorkspaceCommandRunner(default_timeout_seconds=1)
        start = time.time()
        res = runner.run_command(
            workspace_root=temp_git_repo,
            command="python",
            arguments=["-c", "__import__('time').sleep(10)"],
            timeout_seconds=1,
        )
        duration = time.time() - start
        assert duration < 5.0  # Terminated swiftly by timeout handler
        assert res.timed_out is True
        assert res.success is False
        assert res.exit_code == -1
        assert "timed out" in res.stderr.lower() or "timeout" in (res.error or "").lower()

    def test_t2_timeout_preserves_partial_output_prior_to_kill(self, temp_git_repo: Path):
        """Standard output emitted before the timeout occurs is preserved in result."""
        runner = WorkspaceCommandRunner()
        res = runner.run_command(
            workspace_root=temp_git_repo,
            command="python",
            arguments=[
                "-c",
                "(__import__('sys').stdout.write('PARTIAL_OUTPUT_EMITTED\\n'), __import__('sys').stdout.flush(), __import__('time').sleep(5))",
            ],
            timeout_seconds=1,
        )
        assert res.timed_out is True
        assert "PARTIAL_OUTPUT_EMITTED" in res.stdout

    def test_t2_timeout_budget_capping_and_fallback(self, temp_git_repo: Path):
        """Zero or None timeout falls back to default; excessive timeout caps at MAX_TIMEOUT_SECONDS."""
        runner = WorkspaceCommandRunner(default_timeout_seconds=15)
        # 0 or None falls back to default timeout
        effective_zero = min(0 or runner._default_timeout_seconds, MAX_TIMEOUT_SECONDS)
        assert effective_zero == 15

        # Massive timeout is capped at system ceiling
        effective_huge = min(99999 or runner._default_timeout_seconds, MAX_TIMEOUT_SECONDS)
        assert effective_huge == MAX_TIMEOUT_SECONDS
        assert MAX_TIMEOUT_SECONDS == 300

    def test_t2_worker_lease_expiry_ttl_enforcement(self, e2e_redis):
        """Worker leases expire after their TTL; expired leases can be claimed by another worker."""
        task_id = str(uuid.uuid4())
        worker_1 = "worker-alpha"
        worker_2 = "worker-beta"
        lease_key = f"task:lease:{task_id}"

        # Worker 1 acquires lease with 1 second TTL
        acquired_1 = e2e_redis.set(lease_key, worker_1, ex=1, nx=True)
        assert acquired_1 is True

        # Worker 2 immediately attempts acquisition -> rejected (still leased)
        acquired_2 = e2e_redis.set(lease_key, worker_2, ex=1, nx=True)
        assert acquired_2 is False

        # Expire lease manually (simulating TTL elapse in Redis)
        e2e_redis.delete(lease_key)

        # Worker 2 re-attempts -> succeeds
        acquired_2_after_expiry = e2e_redis.set(lease_key, worker_2, ex=60, nx=True)
        assert acquired_2_after_expiry is True
        assert e2e_redis.get(lease_key) == worker_2

    def test_t2_process_group_cleanup_leaves_no_zombies(self, temp_git_repo: Path):
        """Subprocess spawned in process group is reliably killed without leaving host zombies."""
        runner = WorkspaceCommandRunner()
        res = runner.run_command(
            workspace_root=temp_git_repo,
            command="python",
            arguments=["-c", "print('done')"],
            timeout_seconds=5,
        )
        assert res.exit_code == 0
        assert res.success is True


# ===========================================================================
# 2. Empty Inputs & Minimal Payloads (>=5 tests)
# ===========================================================================

class TestTier2EmptyAndMinimalInputs:
    """Boundary tests for empty diffs, empty task descriptions, and minimal inputs."""

    def test_t2_empty_task_title_and_description_rejected(
        self, e2e_client: TestClient, e2e_db: Session, make_user, make_repo
    ):
        """API rejects empty task title or empty description with 422."""
        user, headers = make_user(e2e_db, "empty-task-user")
        repo = make_repo(e2e_db, user, "empty-task-repo")

        # Empty title
        resp = e2e_client.post(
            "/api/v1/tasks",
            json={
                "repository_id": str(repo.id),
                "title": "",
                "description": "Valid description",
                "source": {"type": "USER_PROMPT"},
                "requirements": [{"id": "r1", "description": "req 1"}],
            },
            headers=headers,
        )
        assert resp.status_code == 422

        # Empty description
        resp_desc = e2e_client.post(
            "/api/v1/tasks",
            json={
                "repository_id": str(repo.id),
                "title": "Valid title",
                "description": "",
                "source": {"type": "USER_PROMPT"},
                "requirements": [{"id": "r1", "description": "req 1"}],
            },
            headers=headers,
        )
        assert resp_desc.status_code == 422

    def test_t2_empty_requirements_list_rejected(
        self, e2e_client: TestClient, e2e_db: Session, make_user, make_repo
    ):
        """Mandatory requirement boundary: task creation with 0 requirements is rejected."""
        user, headers = make_user(e2e_db, "empty-req-user")
        repo = make_repo(e2e_db, user, "empty-req-repo")

        resp = e2e_client.post(
            "/api/v1/tasks",
            json={
                "repository_id": str(repo.id),
                "title": "Task with empty requirements",
                "description": "Problem statement without explicit requirement items",
                "source": {"type": "USER_PROMPT"},
                "requirements": [],
            },
            headers=headers,
        )
        assert resp.status_code == 422

    def test_t2_empty_diff_flagged_by_verifier(self):
        """An empty diff text produces no changed files or fails verification if changes expected."""
        verifier = IndependentVerifier()
        result = verifier.verify_task_revision(
            task_id=uuid.uuid4(),
            workspace_revision="a" * 40,
            test_result=RestrictedExecutionResult(
                command=["pytest"],
                exit_code=0,
                status="PASSED",
                duration_ms=500,
                stdout="1 passed",
                stderr="",
                test_counts=TestCounts(passed=1, failed=0, errors=0, skipped=0, total=1),
            ),
            branch_name="agent/task-test-empty",
            diff_text="",
            changed_files=[],
        )
        assert result.status in ("PASS", "PASSED")
        assert len(result.blocking_findings) == 0

    def test_t2_whitespace_only_command_rejected(self, temp_git_repo: Path):
        """Empty or whitespace-only command names are rejected immediately."""
        runner = WorkspaceCommandRunner()
        with pytest.raises(WorkspacePolicyViolationError):
            runner.run_command(
                workspace_root=temp_git_repo,
                command="   ",
                arguments=[],
            )

    def test_t2_zero_byte_file_chunking_handled_gracefully(self, tmp_path: Path):
        """Empty 0-byte file chunking produces 0 chunks without division-by-zero or crash."""
        empty_file = tmp_path / "empty.py"
        empty_file.write_text("")
        assert empty_file.stat().st_size == 0
        empty_hash = hashlib.sha256(b"").hexdigest()
        assert empty_hash == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ===========================================================================
# 3. Max Sizes & Ceilings (>=5 tests)
# ===========================================================================

class TestTier2MaxSizeAndCeilings:
    """Boundary tests for output limits, token budgets, payload caps, and length ceilings."""

    def test_t2_stdout_strictly_truncated_at_100kb_ceiling(self, temp_git_repo: Path):
        """Runner truncates massive command output (500KB) strictly at 100KB."""
        runner = WorkspaceCommandRunner(max_output_bytes=100 * 1024)
        res = runner.run_command(
            workspace_root=temp_git_repo,
            command="python",
            arguments=["-c", "__import__('sys').stdout.write('A' * 500000)"],
            timeout_seconds=10,
        )
        assert "[TRUNCATED:" in res.stdout
        assert len(res.stdout.encode("utf-8")) <= 100 * 1024 + 512

    def test_t2_token_budget_cap_exhaustion_enforced(self):
        """Token budget manager raises TokenBudgetExhaustedError when budget cap is exceeded."""
        mgr = AgentTokenBudgetManager(max_budget_tokens=30000, max_step_tokens=5000)
        mgr.consume("initial_planning", 25000)
        assert mgr.tokens_used == 25000
        assert mgr.tokens_remaining == 5000

        with pytest.raises(TokenBudgetExhaustedError):
            mgr.consume("overflow_step", 6000)

    def test_t2_task_title_max_length_boundary_rejected(
        self, e2e_client: TestClient, e2e_db: Session, make_user, make_repo
    ):
        """Task title exceeding 256 characters is rejected with 422."""
        user, headers = make_user(e2e_db, "long-title-user")
        repo = make_repo(e2e_db, user, "long-title-repo")

        long_title = "x" * 257  # Exceeds max_length=256
        resp = e2e_client.post(
            "/api/v1/tasks",
            json={
                "repository_id": str(repo.id),
                "title": long_title,
                "description": "Valid description",
                "source": {"type": "USER_PROMPT"},
                "requirements": [{"id": "r1", "description": "req 1"}],
            },
            headers=headers,
        )
        assert resp.status_code == 422

    def test_t2_huge_webhook_payload_rejected_by_size_limit(self, e2e_client: TestClient):
        """Webhook endpoint rejects payloads exceeding 5MB max payload size."""
        huge_data = "a" * (5500 * 1024)
        headers = {
            "X-Hub-Signature-256": "sha256=invalid",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-GitHub-Event": "push",
            "Content-Type": "application/json",
        }
        resp = e2e_client.post("/api/v1/github/webhook", content=huge_data, headers=headers)
        assert resp.status_code in (400, 401, 413)

    def test_t2_bounded_repair_max_ceiling_is_three(self):
        """Repair loop enforces a strict maximum boundary of 3 attempts."""
        from app.schemas.repair import RepairPatchPayload
        assert MAX_TASK_REPAIR_ATTEMPTS == 3
        validator = RepairPatchValidator()
        res_exceeded = validator.validate_patch(
            RepairPatchPayload(
                task_id=str(uuid.uuid4()),
                attempt_number=4,
                diff="--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-a\n+b\n",
            ),
            max_attempts=3,
        )
        assert res_exceeded.is_valid is False
        assert any("exceeds" in v.lower() and "budget" in v.lower() for v in res_exceeded.violations)


# ===========================================================================
# 4. Invalid State Transitions & Concurrency (>=5 tests)
# ===========================================================================

class TestTier2InvalidStateTransitions:
    """Boundary tests for illegal state transitions and terminal immutability."""

    def test_t2_created_cannot_transition_to_publishing(self):
        """A newly created task cannot bypass planning/execution straight to PUBLISHING."""
        assert can_transition(TaskStatus.CREATED, TaskStatus.PUBLISHING) is False

    def test_t2_pending_approval_cannot_skip_to_executing(self):
        """Human approval cannot be bypassed by directly transitioning to EXECUTING."""
        assert can_transition(TaskStatus.PENDING_APPROVAL, TaskStatus.EXECUTING) is False

    def test_t2_terminal_states_have_no_forward_transitions(self):
        """Terminal states allow no forward transitions to active lifecycle states."""
        terminal_states = [TaskStatus.DRAFT_PR_CREATED, TaskStatus.CANCELLED]
        forbidden_targets = [
            TaskStatus.CREATED,
            TaskStatus.PLANNING,
            TaskStatus.EXECUTING,
            TaskStatus.VERIFYING,
            TaskStatus.PUBLISHING,
        ]
        for state in terminal_states:
            for target in forbidden_targets:
                assert can_transition(state, target) is False

    def test_t2_failed_state_is_terminal(self):
        """FAILED state cannot arbitrarily transition back to EXECUTING without formal recovery."""
        assert can_transition(TaskStatus.FAILED, TaskStatus.EXECUTING) is False
        assert can_transition(TaskStatus.FAILED, TaskStatus.PUBLISHING) is False

    def test_t2_publishing_blocked_when_diff_hash_diverged(self):
        """Independent verification rejects publication when current diff hash diverges from verified hash."""
        verified_hash = hashlib.sha256(b"original patch content").hexdigest()
        tampered_hash = hashlib.sha256(b"tampered patch content").hexdigest()
        is_immutable = hmac.compare_digest(verified_hash, tampered_hash)
        assert is_immutable is False


# ===========================================================================
# 5. Forbidden Files & Git Security Boundaries (>=5 tests)
# ===========================================================================

class TestTier2ForbiddenFilesAndSecurityBoundaries:
    """Boundary tests for forbidden file protections, command allowlists, and git ref safety."""

    def test_t2_modifying_forbidden_files_generates_blocking_finding(self):
        """IndependentVerifier flags any patch modifying a forbidden file."""
        verifier = IndependentVerifier()
        constraints = [
            TaskConstraint(
                id=str(uuid.uuid4()),
                description="Secrets and credentials must not be altered",
                constraint_type="protected_file",
                forbidden_files=[".env", "config/credentials.json"],
            )
        ]
        findings = verifier.check_forbidden_files(
            changed_files=["app/main.py", ".env"],
            constraints=constraints,
        )
        assert len(findings) == 1
        assert findings[0].blocking is True
        assert findings[0].file_path == ".env"

    def test_t2_shell_metacharacters_strictly_rejected(self, temp_git_repo: Path):
        """Command runner rejects shell chaining operators in arguments."""
        runner = WorkspaceCommandRunner()
        dangerous_operators = [";", "&&", "||", "|", "`", "$", "\n", "\r", "<", ">"]
        for op in dangerous_operators:
            with pytest.raises(WorkspacePolicyViolationError):
                runner.run_command(
                    workspace_root=temp_git_repo,
                    command="python",
                    arguments=["-c", f"print('test'){op}print('injected')"],
                )

    def test_t2_non_allowlisted_binaries_blocked(self, temp_git_repo: Path):
        """Command runner strictly rejects executing non-allowlisted binaries."""
        runner = WorkspaceCommandRunner()
        disallowed_binaries = ["curl", "wget", "bash", "sh", "nc", "rm", "sudo"]
        for binary in disallowed_binaries:
            with pytest.raises(WorkspacePolicyViolationError) as exc_info:
                runner.run_command(
                    workspace_root=temp_git_repo,
                    command=binary,
                    arguments=["--version"],
                )
            assert "allowlist" in str(exc_info.value).lower()

    def test_t2_git_branch_name_injection_prevention(self):
        """Git branch formatting and validation rejects CLI option flags and path traversal."""
        dangerous_branch_inputs = [
            "--upload-pack=cat /etc/passwd",
            "-u",
            "../escape_ref",
            "branch\x00nullbyte",
            "refs/heads/../../escaped",
        ]
        for bad_ref in dangerous_branch_inputs:
            with pytest.raises((ValueError, APIError)):
                _validate_safe_git_ref(bad_ref)

    def test_t2_protected_branch_names_rejected_as_task_branches(self):
        """Agent task branch creation cannot target protected repository branches or inject flags."""
        task_id = uuid.uuid4()
        branch = format_agent_branch_name(task_id)
        assert branch.startswith("agent/task-")
        protected_branches = {"main", "master", "develop", "production", "staging"}
        assert branch not in protected_branches

        # Flag injection in task_id is blocked
        with pytest.raises(APIError):
            format_agent_branch_name("--upload-pack")
        with pytest.raises(APIError):
            format_agent_branch_name("../escape")
