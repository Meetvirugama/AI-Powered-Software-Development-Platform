"""Execution-and-Filter Pipeline for Test Generation Verification.

Owner: Antigravity Test Engineering Team
Reference: task.md §4 (Execution-Verified Test Generation), §4.2 (5-Stage Pipeline)

Pipeline Stages:
Stage 1: Static Validation (Syntax, imports, protected-file guards, safety policy)
Stage 2: Sandbox Execution (Isolated temporary workspace provisioned via WorkspaceManager)
Stage 3: Stability Validation (3 consecutive runs to guarantee non-flakiness)
Stage 4: Coverage Validation (Baseline vs post-gen coverage delta and attribution)
Stage 5: Final Classification:
  - VERIFIED: All static, execution, 3/3 stability, and coverage attribution checks pass.
  - UNVERIFIED: Statically valid, but fails execution, is flaky (2/3), or adds zero coverage.
  - REJECTED: Safety policy violation, protected file overwrite, or dangerous tokens.
  - EXECUTION_ERROR: Sandbox or infrastructure failure prevented reliable execution.
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from app.core.secret_redaction import redact
from app.schemas.analysis import (
    CoverageReport,
    IterationReport,
    IterationRound,
    StabilityReport,
    TestGenerationResult,
    TestVerificationStatus,
)
from app.schemas.workspace import (
    TestOutcomeStatus,
    WorkspaceCreateRequest,
    WorkspaceIsolationType,
    WorkspaceTestExecutionRequest,
    WorkspaceTestExecutionResult,
)
from app.services.test_coverage_service import TargetCoverageData, TestCoverageService
from app.services.test_iteration_service import TestIterationOrchestrator
from app.services.test_stability_service import MAX_STABILITY_RUNS, TestStabilityValidator
from sandbox.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)


class TestExecutionVerifier:
    """Coordinates sandbox execution, stability runs, and coverage attribution."""

    __test__ = False

    def __init__(
        self,
        workspace_manager: WorkspaceManager | None = None,
        stability_validator: TestStabilityValidator | None = None,
        coverage_service: TestCoverageService | None = None,
        iteration_orchestrator: TestIterationOrchestrator | None = None,
    ) -> None:
        self._workspace_manager = workspace_manager or WorkspaceManager()
        self._stability_validator = stability_validator or TestStabilityValidator()
        self._coverage_service = coverage_service or TestCoverageService(
            command_runner=self._workspace_manager.command_runner
        )
        self._iteration_orchestrator = iteration_orchestrator or TestIterationOrchestrator()

    def verify_generated_test(
        self,
        *,
        result: TestGenerationResult,
        target_path: str,
        target_source_code: str,
        repository_id: str,
        base_revision: str | None = None,
        repository_root: Path | None = None,
        existing_files: dict[str, str] | None = None,
        timeout_seconds: int = 45,
    ) -> TestGenerationResult:
        """Run the complete 5-stage execution and verification pipeline."""
        reasons: list[str] = []
        raw_logs: list[str] = []

        # -------------------------------------------------------------------
        # Stage 1: Static Validation Check
        # -------------------------------------------------------------------
        if not result.syntax_valid:
            reasons.append(
                f"Static validation failed: {'; '.join(result.validation_errors) or 'Syntax error'}"
            )
            return result.model_copy(
                update={
                    "verification_status": "UNVERIFIED",
                    "verification_reasons": reasons,
                    "execution_status": "NOT_EXECUTED",
                    "iteration_report": IterationReport(
                        total_rounds=1,
                        rounds=[],
                        stopping_reason="Static validation failed; execution skipped.",
                        final_coverage_achieved=None,
                    ),
                }
            )

        task_id = f"test-verify-{uuid4().hex[:10]}"
        ws_meta = None

        try:
            # ---------------------------------------------------------------
            # Stage 2: Sandbox Provisioning
            # ---------------------------------------------------------------
            effective_revision = (
                base_revision
                if (base_revision and len(base_revision) in (7, 40) and all(c in "0123456789abcdefABCDEF" for c in base_revision))
                else "0123456789abcdef0123456789abcdef01234567"
            )
            try:
                ws_meta = self._workspace_manager.create_workspace(
                    WorkspaceCreateRequest(
                        task_id=task_id,
                        repository_id=repository_id,
                        base_revision=effective_revision,
                        repository_root=str(repository_root) if repository_root else None,
                        isolation_type="directory_copy",
                    )
                )
            except Exception as ws_err:  # noqa: BLE001
                logger.error(f"Sandbox provisioning failed for task '{task_id}': {ws_err}")
                reasons.append(f"Infrastructure error: Unable to provision isolated sandbox workspace: {ws_err}")
                return result.model_copy(
                    update={
                        "verification_status": "EXECUTION_ERROR",
                        "verification_reasons": reasons,
                        "execution_status": "INFRASTRUCTURE_ERROR",
                        "iteration_report": IterationReport(
                            total_rounds=1,
                            rounds=[],
                            stopping_reason=f"Infrastructure error: {ws_err}",
                            final_coverage_achieved=None,
                        ),
                    }
                )

            ws_root = Path(ws_meta.workspace_path)

            # Populate workspace files
            # 1. Write target source file
            target_full_path = ws_root / target_path
            target_full_path.parent.mkdir(parents=True, exist_ok=True)
            target_full_path.write_text(target_source_code, encoding="utf-8")

            # 2. Write existing mock or dependency files if provided
            if existing_files:
                for rel_p, content in existing_files.items():
                    fp = ws_root / rel_p
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_text(content, encoding="utf-8")

            # ---------------------------------------------------------------
            # Stage 4a: Baseline Coverage Measurement
            # ---------------------------------------------------------------
            baseline_cov = self._coverage_service.measure_coverage(
                workspace_root=ws_root,
                target_file=target_path,
                framework=result.detected_framework,
                test_path=None,
            )

            # Write generated test code to proposed_test_path
            test_full_path = ws_root / result.proposed_test_path
            test_full_path.parent.mkdir(parents=True, exist_ok=True)
            test_full_path.write_text(result.test_content, encoding="utf-8")

            # ---------------------------------------------------------------
            # Stage 3: Stability Validation (3 consecutive runs)
            # ---------------------------------------------------------------
            stability_report: StabilityReport = self._stability_validator.validate_with_sandbox_test_runner(
                test_runner=self._workspace_manager.test_runner,
                workspace_root=ws_root,
                test_path=result.proposed_test_path,
                framework=result.detected_framework,
                task_id=task_id,
                timeout_seconds=timeout_seconds,
            )

            # Record raw output from first run
            exec_summary: dict[str, Any] = {
                "total_runs": stability_report.total_runs,
                "passed_runs": stability_report.passed_runs,
                "classification": stability_report.classification,
                "is_stable": stability_report.is_stable,
            }

            for r in stability_report.runs:
                raw_logs.append(
                    f"Run {r.run_number}: {'PASSED' if r.passed else 'FAILED'} (exit={r.exit_code}, {r.duration_seconds}s)"
                )
                if r.error_message:
                    raw_logs.append(f"  Error: {r.error_message}")

            # ---------------------------------------------------------------
            # Stage 4b: Post-Generation Coverage Measurement
            # ---------------------------------------------------------------
            post_gen_cov = self._coverage_service.measure_coverage(
                workspace_root=ws_root,
                target_file=target_path,
                framework=result.detected_framework,
                test_path=result.proposed_test_path,
            )

            cov_report: CoverageReport = self._coverage_service.calculate_coverage_gain(
                baseline=baseline_cov,
                post_generation=post_gen_cov,
                target_file=target_path,
            )

            # ---------------------------------------------------------------
            # Stage 5: Final Classification
            # ---------------------------------------------------------------
            execution_attempted = True
            first_run = stability_report.runs[0] if stability_report.runs else None
            execution_status = "PASSED" if (first_run and first_run.passed) else "FAILED"

            if stability_report.classification == "STABLE":
                # Check coverage attribution
                if cov_report.collection_status == "SUCCESS":
                    if cov_report.coverage_attributable_to_generated_tests:
                        final_status: TestVerificationStatus = "VERIFIED"
                        reasons.append("Static validation passed, 3/3 stability runs passed, and coverage gained.")
                    else:
                        final_status = "UNVERIFIED"
                        reasons.append("Test executed cleanly across 3 runs, but produced 0% coverage gain on target file.")
                elif cov_report.collection_status == "NOT_CONFIGURED":
                    final_status = "UNVERIFIED"
                    reasons.append(
                        "Static validation and 3/3 stability runs passed, but coverage could not be measured (coverage tool not configured)."
                    )
                else:
                    final_status = "UNVERIFIED"
                    reasons.append(f"Coverage collection failed: {'; '.join(cov_report.warnings)}")
            elif stability_report.classification == "UNSTABLE":
                final_status = "UNVERIFIED"
                reasons.append(
                    f"Test exhibited flakiness: passed {stability_report.passed_runs}/{stability_report.total_runs} stability runs."
                )
            else:
                final_status = "UNVERIFIED"
                reasons.append(
                    f"Test execution failed ({stability_report.passed_runs}/{stability_report.total_runs} passed). "
                    f"First run error: {first_run.error_message if first_run else 'Execution error'}"
                )

            uncovered = getattr(post_gen_cov, "uncovered_lines", [])
            cov_val = cov_report.final_line_coverage if cov_report else None
            prev_cov = cov_report.baseline_line_coverage if cov_report else None
            should_cont, stop_reason = self._iteration_orchestrator.should_continue_iteration(
                current_round=1,
                prev_coverage=prev_cov,
                new_coverage=cov_val,
                uncovered_lines=uncovered,
            )
            iter_report = IterationReport(
                total_rounds=1,
                rounds=[
                    IterationRound(
                        round_number=1,
                        tests_added=len(result.covered_scenarios),
                        line_coverage_after=cov_val,
                    )
                ],
                stopping_reason=stop_reason,
                final_coverage_achieved=cov_val,
            )

            return result.model_copy(
                update={
                    "verification_status": final_status,
                    "verification_reasons": reasons,
                    "stability_report": stability_report,
                    "coverage_report": cov_report,
                    "iteration_report": iter_report,
                    "execution_attempted": execution_attempted,
                    "execution_status": execution_status,
                    "execution_summary": exec_summary,
                    "raw_execution_output": redact("\n".join(raw_logs)),
                }
            )

        finally:
            # Safe cleanup of temporary workspace
            if ws_meta:
                try:
                    self._workspace_manager.cleanup_workspace(task_id, force=True)
                except Exception as clean_err:  # noqa: BLE001
                    logger.warning(f"Failed to clean up workspace for task '{task_id}': {clean_err}")
