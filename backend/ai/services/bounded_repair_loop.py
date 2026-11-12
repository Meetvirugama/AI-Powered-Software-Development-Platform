"""Bounded Self-Repair Loop & Failure Healing Orchestrator.

Owner: Meet (Week 3 Day 4: Bounded self-repair loop: collect failures -> targeted patch -> re-test -> max 3 repair attempts)
Reference: Docs/week3.md §6 F35 & §8 Day 4.

Key Responsibilities:
1. Coordinates failure diagnosis with Dev's FailureTracebackAnalyzer.
2. Generates targeted code patches for diagnosed failures (or applies deterministic repair patches).
3. Validates patches with Dev's RepairPatchValidator:
   - Hard task-level budget ceiling of 3 attempts.
   - Rejection of identical repeat patches (anti-cycling).
   - Forbidden file & security constraint guards.
4. Executes test suites via WorkspaceTestRunner and records chronological timeline events.
5. Halts safely when repair budget is exhausted, preventing runaway test loops.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.schemas.repair import (
    DiagnosedFailure,
    FailureCategory,
    FailureClassification,
    PatchValidationResult,
    RepairPatchPayload,
    TestFrameworkName,
    TracebackDiagnosisResult,
)
from app.schemas.workspace import (
    RepairAttemptRecord,
    TestOutcomeStatus,
    WorkspaceExecutionEventType,
    WorkspaceFileWriteRequest,
)

if TYPE_CHECKING:
    from ai.services.edit_synthesizer import EditSynthesizer
    from app.services.repair_service import (
        FailureTracebackAnalyzer,
        RepairPatchValidator,
    )
from ai.services.llm_repair_synthesizer import LLMRepairSynthesizer
from sandbox.exceptions import WorkspaceError
from sandbox.test_runner import WorkspaceTestRunner

if TYPE_CHECKING:
    from sandbox.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)

MAX_TASK_REPAIR_ATTEMPTS: int = 3


@dataclass
class BoundedRepairOutcome:
    """Telemetry outcome of a bounded self-repair session."""

    task_id: str
    success: bool
    attempts_used: int
    max_attempts: int = MAX_TASK_REPAIR_ATTEMPTS
    budget_exhausted: bool = False
    repair_records: list[RepairAttemptRecord] = field(default_factory=list)
    diagnosed_failures: list[DiagnosedFailure] = field(default_factory=list)
    final_test_status: TestOutcomeStatus = TestOutcomeStatus.FAILED
    final_output_summary: str = ""
    error_message: str | None = None
    duration_ms: float = 0.0


class BoundedRepairLoop:
    """Orchestrates test failure diagnosis, targeted patch validation, and re-testing with a hard 3-attempt ceiling."""

    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        test_runner: WorkspaceTestRunner | None = None,
        traceback_analyzer: FailureTracebackAnalyzer | None = None,
        patch_validator: RepairPatchValidator | None = None,
        repair_synthesizer: LLMRepairSynthesizer | None = None,
        edit_synthesizer: EditSynthesizer | None = None,
        llm_gateway: Any = None,
        *,
        max_repair_attempts: int = MAX_TASK_REPAIR_ATTEMPTS,
        allow_test_edits: bool = False,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.test_runner = test_runner or WorkspaceTestRunner()
        if traceback_analyzer is None or patch_validator is None:
            from app.services.repair_service import (
                FailureTracebackAnalyzer as DefaultAnalyzer,
            )
            from app.services.repair_service import (
                RepairPatchValidator as DefaultValidator,
            )
            self.traceback_analyzer = traceback_analyzer or DefaultAnalyzer()
            self.patch_validator = patch_validator or DefaultValidator()
        else:
            self.traceback_analyzer = traceback_analyzer
            self.patch_validator = patch_validator

        self.repair_synthesizer = repair_synthesizer or LLMRepairSynthesizer(
            edit_synthesizer=edit_synthesizer,
            llm_gateway=llm_gateway,
            workspace_manager=workspace_manager,
        )
        self.max_repair_attempts = max_repair_attempts
        self.allow_test_edits = allow_test_edits

    def run_repair_cycle(
        self,
        task_id: str,
        *,
        framework: TestFrameworkName = "pytest",
        test_path: str | None = None,
        patch_synthesizer: Any = None,
        forbidden_files: Sequence[str] | None = None,
        allowed_files: Sequence[str] | None = None,
        allow_test_edits: bool = False,
        plan_scope_files: Sequence[str] | None = None,
    ) -> BoundedRepairOutcome:
        """Run bounded repair loop until tests pass or 3-attempt ceiling is reached."""
        start_time = datetime.now(UTC)
        meta = self.workspace_manager.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'. Cannot run repair loop.")

        workspace_path = meta.workspace_path
        if not workspace_path:
            raise WorkspaceError(f"Workspace path not initialized for task '{task_id}'.")

        effective_allow_test_edits = allow_test_edits or self.allow_test_edits
        effective_allowed_files = list(allowed_files or plan_scope_files or []) or None

        # Initial test execution
        initial_run = self._run_tests(
            workspace_path=workspace_path,
            test_path=test_path,
            framework=framework,
            task_id=task_id,
        )

        passed_count = getattr(initial_run, "passed_count", getattr(initial_run, "tests_passed", 0))
        failed_count = getattr(initial_run, "failed_count", getattr(initial_run, "tests_failed", 0))

        if initial_run.status == TestOutcomeStatus.PASSED:
            total_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return BoundedRepairOutcome(
                task_id=task_id,
                success=True,
                attempts_used=0,
                final_test_status=TestOutcomeStatus.PASSED,
                final_output_summary=f"Tests passed on initial run ({passed_count} passed).",
                duration_ms=total_ms,
            )

        # Diagnose initial failures
        raw_output = f"{initial_run.stdout}\n{initial_run.stderr}"
        diagnosis: TracebackDiagnosisResult = self._diagnose_failures(
            raw_output, framework=framework
        )

        repair_records: list[RepairAttemptRecord] = []
        previous_hashes: list[str] = []
        current_attempts = getattr(meta, "repair_attempts_used", 0)

        primary_category: FailureCategory | str = (
            diagnosis.failures[0].category if diagnosis.failures else "TEST_FAILURE"
        )
        cat_val = primary_category.value if hasattr(primary_category, "value") else str(primary_category)

        self.workspace_manager.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.TESTS_FAILED,
            message=(
                f"Initial tests failed ({failed_count} failed, status={initial_run.status.value}). "
                f"Diagnosed {len(diagnosis.failures)} failures. Starting bounded repair loop."
            ),
            payload={
                "tests_failed": failed_count,
                "failure_category": cat_val,
                "diagnosed_count": len(diagnosis.failures),
            },
        )

        # Check if failure is an unrecoverable environment error
        is_infra = (
            diagnosis.has_infrastructure_failure
            or not diagnosis.can_attempt_repair
            or getattr(diagnosis, "primary_classification", "") == "infra"
        )
        if is_infra:
            total_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            err_msg = f"Non-repairable infrastructure failure: {diagnosis.summary}"
            return BoundedRepairOutcome(
                task_id=task_id,
                success=False,
                attempts_used=current_attempts,
                budget_exhausted=False,
                diagnosed_failures=diagnosis.failures,
                final_test_status=initial_run.status,
                final_output_summary=raw_output[:500],
                error_message=err_msg,
                duration_ms=total_ms,
            )

        # Bounded repair attempts
        while current_attempts < self.max_repair_attempts:
            current_attempts += 1
            attempt_start = datetime.now(UTC)

            self.workspace_manager.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.REPAIR_ATTEMPT_STARTED,
                message=f"Starting repair attempt {current_attempts} of {self.max_repair_attempts}.",
                payload={"attempt_number": current_attempts},
            )

            # 1. Synthesize targeted patch with LLMRepairSynthesizer & Reflexion memory
            patch_payload = self._synthesize_patch(
                task_id=task_id,
                attempt_number=current_attempts,
                diagnosis=diagnosis,
                patch_synthesizer=patch_synthesizer,
                previous_hashes=previous_hashes,
                repair_history=repair_records,
                allowed_files=effective_allowed_files,
                forbidden_files=forbidden_files,
                allow_test_edits=effective_allow_test_edits,
            )

            # 2. Validate patch with Dev's RepairPatchValidator (with Anti-Reward Hacking Gate)
            validation: PatchValidationResult = self.patch_validator.validate_patch(
                patch_payload,
                allowed_files=effective_allowed_files,
                forbidden_files=list(forbidden_files) if forbidden_files else None,
                max_attempts=self.max_repair_attempts,
                allow_test_edits=effective_allow_test_edits,
            )

            if not validation.is_valid:
                reasons = (
                    list(validation.violations)
                    if getattr(validation, "violations", None)
                    else list(getattr(validation, "rejection_reasons", None) or [])
                )
                if not reasons and getattr(validation, "rejection_reason", None):
                    reasons = [str(validation.rejection_reason)]
                err_summary = "; ".join(reasons) or "Patch validation failed."
                logger.warning(
                    "repair_patch_rejected",
                    extra={"task_id": task_id, "attempt": current_attempts, "reasons": reasons},
                )
                self.workspace_manager.record_timeline_event(
                    task_id=task_id,
                    event_type=WorkspaceExecutionEventType.EXECUTION_FAILED,
                    message=f"Repair patch rejected on attempt {current_attempts}: {err_summary}",
                    payload={"reasons": reasons},
                )
                repair_records.append(
                    RepairAttemptRecord(
                        task_id=task_id,
                        attempt_number=current_attempts,
                        timestamp=attempt_start.isoformat(),
                        patch_summary=f"Rejected: {err_summary}",
                        patch_hash=validation.patch_hash,
                        test_status_before=initial_run.status,
                        test_status_after=TestOutcomeStatus.FAILED,
                        success=False,
                    )
                )
                continue

            # Record patch hash to prevent identical repeats
            if validation.patch_hash:
                previous_hashes.append(validation.patch_hash)

            # 3. Apply patch in workspace
            self._apply_patch_files(task_id, patch_payload)

            # Update workspace repair attempt metadata if supported
            if hasattr(self.workspace_manager, "increment_repair_attempts"):
                self.workspace_manager.increment_repair_attempts(task_id)

            # 4. Re-run tests
            retest_run = self._run_tests(
                workspace_path=workspace_path,
                test_path=test_path,
                framework=framework,
                task_id=task_id,
            )

            retest_output = f"{retest_run.stdout}\n{retest_run.stderr}"
            is_success = retest_run.status == TestOutcomeStatus.PASSED
            retest_passed = getattr(retest_run, "passed_count", getattr(retest_run, "tests_passed", 0))
            retest_failed = getattr(retest_run, "failed_count", getattr(retest_run, "tests_failed", 0))

            record = RepairAttemptRecord(
                task_id=task_id,
                attempt_number=current_attempts,
                timestamp=attempt_start.isoformat(),
                patch_summary=patch_payload.explanation,
                patch_hash=validation.patch_hash,
                test_status_before=initial_run.status,
                test_status_after=retest_run.status,
                success=is_success,
            )
            repair_records.append(record)

            self.workspace_manager.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.REPAIR_ATTEMPT_COMPLETED,
                message=(
                    f"Repair attempt {current_attempts} completed with status {retest_run.status.value} "
                    f"({retest_passed} passed, {retest_failed} failed)."
                ),
                payload={
                    "attempt_number": current_attempts,
                    "status": retest_run.status.value,
                    "passed": retest_passed,
                    "failed": retest_failed,
                    "success": is_success,
                },
            )

            if is_success:
                total_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
                return BoundedRepairOutcome(
                    task_id=task_id,
                    success=True,
                    attempts_used=current_attempts,
                    budget_exhausted=False,
                    repair_records=repair_records,
                    diagnosed_failures=diagnosis.failures,
                    final_test_status=TestOutcomeStatus.PASSED,
                    final_output_summary=f"Repaired successfully on attempt {current_attempts}.",
                    duration_ms=total_ms,
                )

            # Re-diagnose for next attempt
            diagnosis = self._diagnose_failures(retest_output, framework=framework)

        # Budget exhausted
        total_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
        msg = f"Bounded self-repair exhausted maximum budget of {self.max_repair_attempts} attempts without passing all tests."
        logger.warning("repair_budget_exhausted", extra={"task_id": task_id, "attempts": current_attempts})

        self.workspace_manager.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.REPAIR_BUDGET_EXHAUSTED,
            message=msg,
            payload={"attempts_used": current_attempts, "max_attempts": self.max_repair_attempts},
        )

        return BoundedRepairOutcome(
            task_id=task_id,
            success=False,
            attempts_used=current_attempts,
            budget_exhausted=True,
            repair_records=repair_records,
            diagnosed_failures=diagnosis.failures,
            final_test_status=TestOutcomeStatus.FAILED,
            final_output_summary=msg,
            error_message=msg,
            duration_ms=total_ms,
        )

    def _synthesize_patch(
        self,
        task_id: str,
        attempt_number: int,
        diagnosis: TracebackDiagnosisResult,
        patch_synthesizer: Any = None,
        previous_hashes: Sequence[str] | None = None,
        repair_history: Sequence[RepairAttemptRecord] | None = None,
        allowed_files: Sequence[str] | None = None,
        forbidden_files: Sequence[str] | None = None,
        allow_test_edits: bool = False,
    ) -> RepairPatchPayload:
        """Synthesize a repair patch payload using LLMRepairSynthesizer or custom callback."""
        if callable(patch_synthesizer):
            res = patch_synthesizer(task_id, attempt_number, diagnosis)
            if isinstance(res, RepairPatchPayload):
                if previous_hashes and not res.previous_patch_hashes:
                    res.previous_patch_hashes = list(previous_hashes)
                return res

        # Autonomous LLM / EditSynthesizer driven repair synthesis (Issue #205 / F24)
        return self.repair_synthesizer.synthesize_repair(
            task_id=task_id,
            attempt_number=attempt_number,
            diagnosis=diagnosis,
            workspace_manager=self.workspace_manager,
            repair_history=repair_history,
            previous_hashes=previous_hashes,
            allowed_files=allowed_files,
            forbidden_files=forbidden_files,
            allow_test_edits=allow_test_edits or self.allow_test_edits,
        )

    @staticmethod
    def _extract_patched_content(existing_content: str, diff_text: str, target_file: str, explanation: str) -> str:
        """Apply unified diff hunks or reconstructed content to existing file content."""
        if not diff_text.strip():
            return existing_content or f"# Repaired content for {target_file}\n# Patch: {explanation}\n"

        # 1. Hunk-based replacement for standard multi-line unified diffs
        hunks = re.split(r"(?m)^@@\s+-[0-9,]+\s+\+[0-9,]+\s+@@", diff_text)
        if len(hunks) > 1 and existing_content:
            content = existing_content
            applied_any = False
            for hunk in hunks[1:]:
                lines = hunk.splitlines()
                removed = [line[1:] for line in lines if line.startswith("-") and not line.startswith("---")]
                added = [line[1:] for line in lines if line.startswith("+") and not line.startswith("+++")]
                if removed:
                    rem_block = "\n".join(removed)
                    add_block = "\n".join(added)
                    if rem_block in content:
                        content = content.replace(rem_block, add_block, 1)
                        applied_any = True
            if applied_any:
                return content

        # 2. Sequential removed vs added line application
        removed_lines: list[str] = []
        added_lines: list[str] = []
        for raw_line in diff_text.splitlines():
            if raw_line.startswith(("---", "+++", "@@")):
                continue
            if raw_line.startswith("-"):
                removed_lines.append(raw_line[1:])
            elif raw_line.startswith("+"):
                added_lines.append(raw_line[1:])

        if existing_content and removed_lines:
            removed_block = "\n".join(removed_lines)
            added_block = "\n".join(added_lines)
            if removed_block in existing_content:
                return existing_content.replace(removed_block, added_block, 1)

        if existing_content and added_lines and not removed_lines:
            return existing_content.rstrip("\n") + "\n" + "\n".join(added_lines) + "\n"

        if added_lines:
            # Reconstruct from non-removed diff lines
            reconstructed: list[str] = []
            for raw_line in diff_text.splitlines():
                if raw_line.startswith(("---", "+++", "@@", "-")):
                    continue
                if raw_line.startswith(("+", " ")):
                    reconstructed.append(raw_line[1:])
            if reconstructed:
                return "\n".join(reconstructed) + "\n"

        return f"# Repaired content for {target_file}\n# Patch: {explanation}\n"

    def _apply_patch_files(self, task_id: str, patch_payload: RepairPatchPayload) -> None:
        """Apply patch to workspace target files safely."""
        meta = self.workspace_manager.get_workspace(task_id)
        if not meta or not meta.workspace_path:
            raise WorkspaceError(f"Cannot apply patch: workspace missing for '{task_id}'")

        target_files = list(patch_payload.target_files or [])
        if not target_files:
            # Extract from diff header if target_files was omitted
            for match in re.finditer(r"^\+\+\+\s+(?:b/)?([^\s\t\r\n]+)", patch_payload.diff, re.MULTILINE):
                path = match.group(1).strip()
                if path and path != "/dev/null" and path not in target_files:
                    target_files.append(path)

        for target_file in target_files:
            existing_content = ""
            if hasattr(self.workspace_manager, "read_file"):
                try:
                    read_res = self.workspace_manager.read_file(task_id=task_id, file_path=target_file)
                    if getattr(read_res, "success", False):
                        existing_content = getattr(read_res, "content", "") or ""
                except Exception as exc:  # noqa: BLE001
                    logger.debug("workspace_read_for_patch_error", extra={"error": str(exc), "file": target_file})
                    existing_content = ""

            content = self._extract_patched_content(
                existing_content=existing_content,
                diff_text=patch_payload.diff,
                target_file=target_file,
                explanation=patch_payload.explanation,
            )

            if hasattr(self.workspace_manager, "write_file"):
                self.workspace_manager.write_file(
                    task_id=task_id,
                    file_path=target_file,
                    content=content,
                    create_parents=True,
                )
            elif hasattr(self.workspace_manager, "safe_write_file"):
                req = WorkspaceFileWriteRequest(
                    task_id=task_id,
                    file_path=target_file,
                    content=content,
                    create_directories=True,
                )
                self.workspace_manager.safe_write_file(req)

    def _run_tests(
        self,
        *,
        workspace_path: str,
        test_path: str | None,
        framework: str,
        task_id: str,
    ) -> Any:
        """Safely execute tests with test_runner, adapting across WorkspaceTestRunner and mock signatures."""
        try:
            return self.test_runner.run_tests(
                workspace_path=workspace_path,
                test_path=test_path,
                framework="pytest" if framework == "pytest" else "jest",
            )
        except TypeError:
            from pathlib import Path

            from app.schemas.workspace import WorkspaceTestExecutionRequest

            req = WorkspaceTestExecutionRequest(
                task_id=task_id,
                framework=framework,
                test_path=test_path,
            )
            return self.test_runner.run_tests(
                workspace_root=Path(workspace_path),
                request=req,
            )

    def _diagnose_failures(self, raw_output: str, framework: str) -> TracebackDiagnosisResult:
        """Safely invoke diagnosis across FailureTracebackAnalyzer or duck-typed analyzer."""
        if hasattr(self.traceback_analyzer, "diagnose"):
            return self.traceback_analyzer.diagnose(raw_output, framework=framework)
        return self.traceback_analyzer.analyze_traceback(raw_output, framework=framework)


__all__ = [
    "MAX_TASK_REPAIR_ATTEMPTS",
    "BoundedRepairLoop",
    "BoundedRepairOutcome",
    "LLMRepairSynthesizer",
]
