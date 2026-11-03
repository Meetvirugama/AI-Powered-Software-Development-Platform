"""Comprehensive Verification Suite for Meet's Week 3 Deliverables across All Days.

Owner: Meet (Week 3 Days 1–6 Complete Verification Suite)
Reference: Docs/daily_tasks.md (lines 605, 618, 630, 639, 649, 660) & Docs/week3.md §6, §8

Test Matrix:
- Day 1: IssueToTaskAdapter (untrusted boundary fencing, path extraction, finding-to-issue formatting)
- Day 2: TaskPlanner (plan generation, fallback schema synthesis, DAG topological ordering)
- Day 3: AgentExecutionLoop (dependency resolution, safe file writes/reads, anti-cyclic loop detection)
- Day 4: BoundedRepairLoop (failure diagnosis, patch validation, 3-attempt task budget ceiling, duplicate patch rejection)
- Day 5: RequirementToCodeVerifier (diff comparison, forbidden file constraints, out-of-scope warnings, PR summary)
- Day 6: RetrievalLatencyOptimizer (P95 < 400ms target, caching, concurrent retrieval) & AgentTokenBudgetManager (estimation, ceiling enforcement)
"""

import os
import shutil
import tempfile
import time
import uuid
from unittest.mock import MagicMock

import pytest

from ai.services.agent_execution_loop import (
    ActionFingerprint,
    AgentExecutionLoop,
    LoopDetectedError,
    LoopDetector,
    StepExecutionStatus,
)
from ai.services.bounded_repair_loop import (
    BoundedRepairLoop,
    BoundedRepairOutcome,
    MAX_TASK_REPAIR_ATTEMPTS,
)
from ai.services.issue_task_adapter import (
    IssueToTaskAdapter,
    extract_safe_repo_paths,
    fence_untrusted_issue_data,
    format_issue_from_finding,
)
from ai.services.requirement_verifier import (
    RequirementComplianceItem,
    RequirementToCodeVerifier,
    RequirementVerificationResult,
)
from ai.services.retrieval_optimizer import (
    AgentTokenBudgetManager,
    LRUQueryCache,
    RetrievalLatencyOptimizer,
    TokenBudgetExhaustedError,
)
from ai.services.task_planner import TaskPlanner
from app.schemas.plan import PlanStep, StructuredPlan
from app.schemas.repair import (
    DiagnosedFailure,
    FailureCategory,
    PatchValidationResult,
    RepairPatchPayload,
    TestFrameworkName,
    TracebackDiagnosisResult,
)
from app.schemas.task import (
    TaskConstraint,
    TaskRequirement,
    TaskSourceReference,
)
from app.schemas.planner_context import FileDiffRange, TaskDiffRanges
from app.schemas.verification import FindingSeverity, VerificationOverallStatus
from app.schemas.workspace import (
    RepairAttemptRecord,
    TestOutcomeStatus,
    WorkspaceCreateRequest,
    WorkspaceDiffResult,
    WorkspaceFileReadRequest,
    WorkspaceFileWriteRequest,
    WorkspaceStatus,
    WorkspaceTestExecutionResult,
)
from sandbox.workspace_manager import WorkspaceManager


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_workspace_dir():
    """Create disposable root directory for sandbox workspace manager."""
    temp_dir = tempfile.mkdtemp(prefix="test_meet_w3_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def workspace_mgr(temp_workspace_dir):
    """Provide clean WorkspaceManager pointing to temporary directory."""
    return WorkspaceManager(base_workspaces_dir=temp_workspace_dir)


@pytest.fixture
def initialized_task_workspace(workspace_mgr):
    """Create a workspace in READY/IN_USE state for task execution."""
    task_id = str(uuid.uuid4())
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid.uuid4()),
        base_revision="0123456789abcdef0123456789abcdef01234567",
    )
    workspace_mgr.create_workspace(req)
    # Transition to READY
    workspace_mgr.transition_state(task_id, WorkspaceStatus.READY)
    return task_id


# ============================================================================
# DAY 1: Issue-to-Task Context Adapter Tests
# ============================================================================

class TestDay1IssueTaskAdapter:
    """Tests for Meet's Week 3 Day 1 Issue-to-Task adapter."""

    def test_fence_untrusted_issue_data_random_token_and_secrets(self):
        """Verify randomized delimiter fencing and secret redaction."""
        untrusted = "Fix vulnerability in src/auth.py with token ghp_123456789012345678901234567890123456"
        fenced1 = fence_untrusted_issue_data(untrusted)
        fenced2 = fence_untrusted_issue_data(untrusted)

        assert "ghp_123456789012345678901234567890123456" not in fenced1
        assert "[REDACTED]" in fenced1
        assert "<<<ISSUE_DATA_" in fenced1
        assert "<<<END_ISSUE_DATA_" in fenced1
        # Random tokens must be distinct
        assert fenced1 != fenced2

    def test_extract_safe_repo_paths_drops_traversals_and_forbidden(self):
        """Verify path extraction drops path traversal attempts and forbidden files."""
        text = "Please update `src/main.py`, `../../etc/passwd`, and `.env`."
        paths = extract_safe_repo_paths(text, forbidden_files=[".env"])
        assert "src/main.py" in paths
        assert "../../etc/passwd" not in paths
        assert ".env" not in paths

    def test_format_issue_from_finding(self):
        """Verify finding formatting produces clean markdown title, body, and labels."""
        finding = {
            "id": "find-123",
            "title": "SQL Injection in Search Query",
            "description": "User input interpolated directly into SQL string.",
            "severity": "HIGH",
            "category": "security",
            "file_path": "backend/app/search.py",
            "line_start": 42,
            "line_end": 45,
            "rule_id": "security/sql-injection",
        }
        title, body, labels = format_issue_from_finding(finding)
        assert "SQL Injection in Search Query" in title
        assert "backend/app/search.py" in body
        assert "ai-finding" in labels
        assert "security" in labels
        assert "severity:high" in labels


# ============================================================================
# DAY 2: TaskPlanner & DAG Validation Tests
# ============================================================================

class TestDay2TaskPlanner:
    """Tests for Meet's Week 3 Day 2 TaskPlanner."""

    def test_planner_fallback_creates_valid_structured_plan(self):
        """Verify TaskPlanner fallback synthesis constructs a safe, minimal DAG plan."""
        import uuid
        from app.models.task import AgentTask

        task = AgentTask(
            id=uuid.uuid4(),
            title="Fix null dereference in parser",
            description="Null pointer exception when visiting empty AST nodes.",
            requirements=[{"id": "r1", "target_files": ["src/parser.py"]}],
            constraints=[{"forbidden_files": [".env"]}],
        )
        ctx = {
            "language": "python",
            "test_command": "pytest",
            "target_files": ["src/parser.py"],
            "repo_files": [],
            "relevant_symbols": [],
            "forbidden_lower": {".env"},
        }
        planner = TaskPlanner()
        plan = planner._build_deterministic_plan(task, ctx)
        assert plan.summary != ""
        assert len(plan.steps) >= 2
        assert any("src/parser.py" in step.expected_files for step in plan.steps)
        assert ".env" not in plan.expected_files

    def test_planner_topological_step_order(self):
        """Verify plan step dependencies resolve in topological order."""
        s1 = PlanStep(step_id="step-1", description="Inspect parser", action_type="inspect", expected_files=["src/parser.py"])
        s2 = PlanStep(step_id="step-2", description="Edit parser", action_type="edit", expected_files=["src/parser.py"], dependencies=["step-1"])
        s3 = PlanStep(step_id="step-3", description="Run tests", action_type="test", expected_files=["tests/test_parser.py"], dependencies=["step-2"])

        loop = AgentExecutionLoop(workspace_manager=MagicMock())
        ordered = loop._resolve_step_dependencies([s3, s1, s2])
        ids = [s.step_id for s in ordered]
        assert ids == ["step-1", "step-2", "step-3"]


# ============================================================================
# DAY 3: Agent Execution Loop with Anti-Cyclic Loop Detection Tests
# ============================================================================

class TestDay3AgentExecutionLoop:
    """Tests for Meet's Week 3 Day 3 AgentExecutionLoop & LoopDetector."""

    def test_execution_loop_happy_path(self, workspace_mgr, initialized_task_workspace):
        """Verify successful plan execution through write, read, and command steps."""
        task_id = initialized_task_workspace
        loop = AgentExecutionLoop(workspace_manager=workspace_mgr)

        plan = [
            PlanStep(step_id="step-1", description="Write helper", action_type="create", expected_files=["src/helper.py"]),
            PlanStep(step_id="step-2", description="Inspect helper", action_type="inspect", expected_files=["src/helper.py"], dependencies=["step-1"]),
        ]

        result = loop.execute_plan(
            task_id=task_id,
            plan=plan,
            step_payloads={"step-1": {"content": "def helper(): return 42\n"}},
        )

        assert result.status == StepExecutionStatus.COMPLETED
        assert len(result.steps_executed) == 2
        assert result.loop_detected is False

        # Verify file exists in workspace
        meta = workspace_mgr.get_workspace(task_id)
        assert os.path.exists(os.path.join(meta.workspace_path, "src/helper.py"))

    def test_loop_detector_identifies_repeating_cycles(self):
        """Verify LoopDetector identifies immediate repeats and oscillating 2-cycles."""
        detector = LoopDetector(max_cycle_repetitions=2, max_cycle_window=3)

        fp_a = ActionFingerprint(step_id="step-1", action_type="edit", target_files=("a.py",), payload_hash="hash1")
        fp_b = ActionFingerprint(step_id="step-2", action_type="edit", target_files=("b.py",), payload_hash="hash2")

        # No cycle yet
        is_loop, _ = detector.record_and_check(fp_a)
        assert is_loop is False
        is_loop, _ = detector.record_and_check(fp_b)
        assert is_loop is False

        # Repeat A -> B -> A -> B (2-cycle)
        is_loop, _ = detector.record_and_check(fp_a)
        assert is_loop is False
        is_loop, cycle_len = detector.record_and_check(fp_b)
        assert is_loop is True
        assert cycle_len == 2

    def test_execution_loop_aborts_on_loop_detection(self, workspace_mgr, initialized_task_workspace):
        """Verify AgentExecutionLoop safely halts and emits telemetry when cyclic execution occurs."""
        task_id = initialized_task_workspace
        # Set max_cycle_repetitions=1 to trigger on immediate identical action
        loop = AgentExecutionLoop(workspace_manager=workspace_mgr, max_cycle_repetitions=1)

        # Duplicate identical steps
        plan = [
            PlanStep(step_id="step-1", description="Edit file", action_type="edit", expected_files=["src/loop.py"]),
            PlanStep(step_id="step-1", description="Edit file", action_type="edit", expected_files=["src/loop.py"]),
        ]

        result = loop.execute_plan(
            task_id=task_id,
            plan=plan,
            step_payloads={"step-1": {"content": "same content"}},
        )

        assert result.status == StepExecutionStatus.LOOP_DETECTED
        assert result.loop_detected is True
        assert "Repetitive execution cycle detected" in (result.error_message or "")


# ============================================================================
# DAY 4: Bounded Self-Repair Loop Tests
# ============================================================================

class TestDay4BoundedRepairLoop:
    """Tests for Meet's Week 3 Day 4 BoundedSelfRepairLoop."""

    def test_repair_succeeds_on_passing_initial_tests(self, workspace_mgr, initialized_task_workspace):
        """Verify repair loop returns immediately when tests pass initially without using repair budget."""
        task_id = initialized_task_workspace
        test_runner = MagicMock()
        test_runner.run_tests.return_value = WorkspaceTestExecutionResult(
            task_id=task_id,
            success=True,
            command="pytest",
            exit_code=0,
            stdout="1 passed in 0.05s",
            stderr="",
            duration_ms=50.0,
            status=TestOutcomeStatus.PASSED,
            passed_count=1,
            failed_count=0,
        )

        repair = BoundedRepairLoop(workspace_manager=workspace_mgr, test_runner=test_runner)
        outcome = repair.run_repair_cycle(task_id=task_id)

        assert outcome.success is True
        assert outcome.attempts_used == 0
        assert outcome.budget_exhausted is False
        assert outcome.final_test_status == TestOutcomeStatus.PASSED

    def test_repair_recovers_on_second_attempt(self, workspace_mgr, initialized_task_workspace):
        """Verify repair loop diagnoses failure, applies valid patch, and succeeds on retest."""
        task_id = initialized_task_workspace
        meta = workspace_mgr.get_workspace(task_id)

        test_runner = MagicMock()
        # 1st run fails, 2nd run passes
        fail_res = WorkspaceTestExecutionResult(
            task_id=task_id,
            success=False,
            command="pytest",
            exit_code=1,
            stdout="FAILED tests/test_calc.py::test_add - AssertionError: assert 1 == 2",
            stderr="",
            duration_ms=100.0,
            status=TestOutcomeStatus.FAILED,
            passed_count=0,
            failed_count=1,
        )
        pass_res = WorkspaceTestExecutionResult(
            task_id=task_id,
            success=True,
            command="pytest",
            exit_code=0,
            stdout="1 passed in 0.05s",
            stderr="",
            duration_ms=50.0,
            status=TestOutcomeStatus.PASSED,
            passed_count=1,
            failed_count=0,
        )
        test_runner.run_tests.side_effect = [fail_res, pass_res]

        repair = BoundedRepairLoop(workspace_manager=workspace_mgr, test_runner=test_runner)
        outcome = repair.run_repair_cycle(task_id=task_id)

        assert outcome.success is True
        assert outcome.attempts_used == 1
        assert len(outcome.repair_records) == 1
        assert outcome.repair_records[0].success is True

    def test_repair_stops_at_hard_three_attempt_ceiling(self, workspace_mgr, initialized_task_workspace):
        """Verify repair loop respects MAX_TASK_REPAIR_ATTEMPTS=3 and marks budget exhausted."""
        task_id = initialized_task_workspace
        test_runner = MagicMock()
        # Always fail
        fail_res = WorkspaceTestExecutionResult(
            task_id=task_id,
            success=False,
            command="pytest",
            exit_code=1,
            stdout="FAILED tests/test_calc.py::test_add - AssertionError: assert 1 == 2",
            stderr="",
            duration_ms=80.0,
            status=TestOutcomeStatus.FAILED,
            passed_count=0,
            failed_count=1,
        )
        test_runner.run_tests.return_value = fail_res

        repair = BoundedRepairLoop(workspace_manager=workspace_mgr, test_runner=test_runner)
        outcome = repair.run_repair_cycle(task_id=task_id)

        assert outcome.success is False
        assert outcome.attempts_used == MAX_TASK_REPAIR_ATTEMPTS
        assert outcome.budget_exhausted is True
        assert outcome.final_test_status == TestOutcomeStatus.FAILED
        assert "exhausted maximum budget of 3 attempts" in (outcome.error_message or "")


# ============================================================================
# DAY 5: Requirement-to-Code Verification Tests
# ============================================================================

class TestDay5RequirementVerifier:
    """Tests for Meet's Week 3 Day 5 RequirementToCodeVerifier."""

    def test_verification_passes_when_requirements_and_plan_match_diff(self):
        """Verify PASS status when all requirements are satisfied with no constraint violations."""
        verifier = RequirementToCodeVerifier()
        reqs = [
            TaskRequirement(id="req-1", description="Implement auth helper", category="functional", target_files=["src/auth.py"], acceptance_criteria=["Token generated"]),
        ]
        plan = StructuredPlan(
            summary="Add auth helper",
            problem_statement="Need token helper",
            expected_files_to_modify=["src/auth.py"],
            steps=[
                PlanStep(
                    step_id="step_1",
                    title="Implement auth helper",
                    description="Implement token generation helper",
                    action_type="modify",
                    expected_files=["src/auth.py"],
                )
            ],
        )
        test_task_id = uuid.uuid4()
        diff = TaskDiffRanges(
            task_id=test_task_id,
            files=[FileDiffRange(file_path="src/auth.py", status="modified", additions=10, deletions=2)],
            total_files_changed=1,
            total_additions=10,
            total_deletions=2,
        )

        result = verifier.verify_requirements_against_diff(
            task_id=str(test_task_id),
            requirements=reqs,
            constraints=[],
            original_plan=plan,
            final_diff=diff,
        )

        assert result.overall_status == "PASS"
        assert result.alignment_score == 1.0
        assert "req-1" in result.satisfied_requirements
        assert len(result.unmet_requirements) == 0
        assert len(result.constraint_violations) == 0
        assert "## Automated Task Verification Report" in result.summary_markdown

    def test_verification_fails_on_forbidden_file_modification(self):
        """Verify immediate FAIL status when a constraint-forbidden file is touched in diff."""
        verifier = RequirementToCodeVerifier()
        reqs = [
            TaskRequirement(id="req-1", description="Update parser", category="functional", target_files=["src/parser.py"], acceptance_criteria=[]),
        ]
        constraints = [
            TaskConstraint(id="cst-1", description="Protect core grammar", constraint_type="protected_file", forbidden_files=[".env", "grammar.py"], forbidden_packages=[]),
        ]
        plan = StructuredPlan(
            summary="Plan",
            problem_statement="P",
            expected_files_to_modify=["src/parser.py"],
            steps=[
                PlanStep(
                    step_id="step_1",
                    title="Update parser",
                    description="Update parser code",
                    action_type="modify",
                    expected_files=["src/parser.py"],
                )
            ],
        )
        test_task_id_2 = uuid.uuid4()
        diff = TaskDiffRanges(
            task_id=test_task_id_2,
            files=[
                FileDiffRange(file_path="src/parser.py", status="modified", additions=5, deletions=1),
                FileDiffRange(file_path="grammar.py", status="modified", additions=2, deletions=0),
            ],
            total_files_changed=2,
            total_additions=7,
            total_deletions=1,
        )

        result = verifier.verify_requirements_against_diff(
            task_id=str(test_task_id_2),
            requirements=reqs,
            constraints=constraints,
            original_plan=plan,
            final_diff=diff,
        )

        assert result.overall_status == "FAIL"
        assert len(result.constraint_violations) == 1
        assert any(f.blocking for f in result.findings)


# ============================================================================
# DAY 6: Retrieval Latency Optimizer & Agent Token Budget Tests
# ============================================================================

class TestDay6RetrievalAndTokenBudget:
    """Tests for Meet's Week 3 Day 6 RetrievalLatencyOptimizer & AgentTokenBudgetManager."""

    def test_retrieval_optimizer_meets_p95_target_and_caches(self):
        """Verify latency tracking accurately reports P95 < 400ms target and cache speedup."""
        optimizer = RetrievalLatencyOptimizer(target_p95_ms=400.0)

        def mock_retrieval(query: str):
            time.sleep(0.01)  # 10ms synthetic latency
            return {"query": query, "chunks": ["chunk1", "chunk2"]}

        # 1st call: miss (cold)
        res1, d1 = optimizer.execute_optimized_retrieval("search auth", mock_retrieval)
        assert d1 >= 10.0
        assert res1["query"] == "search auth"

        # 2nd call: hit (warm)
        res2, d2 = optimizer.execute_optimized_retrieval("search auth", mock_retrieval)
        assert d2 < 2.0  # Cache hit is sub-millisecond

        stats = optimizer.cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1

        percentiles = optimizer.get_latency_percentiles()
        assert percentiles.sample_count == 2
        assert percentiles.p95_ms < 400.0
        assert percentiles.target_met is True

    def test_retrieval_concurrent_search_reduces_latency(self):
        """Verify concurrent execution runs vector and lexical searches in parallel."""
        optimizer = RetrievalLatencyOptimizer()

        def slow_vector(q: str):
            time.sleep(0.02)  # 20ms
            return ["vec-1"]

        def slow_lexical(q: str):
            time.sleep(0.02)  # 20ms
            return ["lex-1"]

        res, duration_ms = optimizer.execute_concurrent_search("test query", slow_vector, slow_lexical)
        assert res["vector"] == ["vec-1"]
        assert res["lexical"] == ["lex-1"]
        # Serial would be >= 40ms; concurrent runs around ~25ms
        assert duration_ms < 35.0

    def test_token_budget_manager_bounds_and_enforces_ceiling(self):
        """Verify AgentTokenBudgetManager estimates, consumes, and raises on ceiling breach."""
        mgr = AgentTokenBudgetManager(max_budget_tokens=1000, max_step_tokens=200)

        # Estimation
        est = mgr.estimate_tokens("Hello world! " * 10)
        assert est > 0

        # Valid consumption
        rec1 = mgr.consume("plan_synthesis", 300)
        assert mgr.tokens_used == 300
        assert mgr.tokens_remaining == 700
        assert mgr.is_exhausted is False

        # Truncation
        long_text = "A" * 2000
        truncated = mgr.truncate_to_budget(long_text, max_allowed_tokens=50)
        assert len(truncated) < len(long_text)
        assert "[TRUNCATED DUE TO TOKEN BUDGET]" in truncated

        # Exhaustion ceiling
        with pytest.raises(TokenBudgetExhaustedError) as exc_info:
            mgr.consume("oversized_step", 800)  # 300 + 800 = 1100 > 1000
        assert "Token budget exhausted" in str(exc_info.value)
