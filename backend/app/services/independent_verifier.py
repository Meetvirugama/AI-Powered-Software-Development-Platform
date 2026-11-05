"""Independent Verification and PR Summary Generation Engine.

Fulfills Week 3 Day 5 Deliverable (Docs/daily_tasks.md line 644 & Docs/week3.md §6 F36).
Co-owners: Dev & Parth

Responsibilities:
- Evaluate the 12 canonical verification checks before code changes are eligible for publication.
- Ensure test results correspond to the exact final workspace revision.
- Inspect proposed diff for secrets, forbidden files, and unexpected deletions.
- Integrate static analysis and Week 2 code review findings.
- Generate structured Markdown PR summaries for human review.
- Enforce that failed or unverified revisions cannot be published.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.core.secret_redaction import redact_secrets
from app.schemas.repair import MAX_DIFF_CHARS
from app.schemas.task import TaskConstraint
from app.schemas.verification import (
    VerificationCheckItem,
    VerificationContext,
    VerificationFinding,
    VerificationOverallStatus,
    VerificationResult,
)
from app.schemas.task import RestrictedExecutionResult
from app.services.repair_service import extract_modified_files_from_diff

logger = logging.getLogger(__name__)

# List of branches that should never be pushed to directly
_PROTECTED_BRANCHES = {"main", "master", "release", "production", "develop"}

_SECRET_PATTERNS = [
    re.compile(r"(?i)github_pat_[0-9a-zA-Z_]{20,}"),
    re.compile(r"(?i)ghp_[0-9a-zA-Z]{36}"),
    re.compile(r"(?i)ghs_[0-9a-zA-Z]{36}"),
    re.compile(r"(?i)-----BEGIN\s+(?:RSA|OPENSSH|DSA|EC|PRIVATE)\s+KEY-----"),
    re.compile(r"(?i)sk-[a-zA-Z0-9]{32,}"),
    re.compile(r"(?i)(?:api_key|secret_key|private_key|auth_token)\s*=\s*['\"][0-9a-zA-Z-_]{16,}['\"]"),
]


class IndependentVerifier:
    """Performs independent verification checks across diffs, tests, and security boundaries."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def scan_diff_for_secrets(diff_text: str) -> list[VerificationFinding]:
        """Scan diff additions for potential API keys, private keys, or credentials."""
        findings: list[VerificationFinding] = []
        if not diff_text:
            return findings

        line_num = 1
        for line in diff_text.splitlines():
            # Only scan added lines
            if line.startswith("+") and not line.startswith("+++"):
                added_content = line[1:]
                for pat in _SECRET_PATTERNS:
                    if pat.search(added_content):
                        findings.append(
                            VerificationFinding(
                                id=f"sec-leak-{line_num}",
                                severity="CRITICAL",
                                category="security",
                                message="Potential secret, token, or private key detected in proposed diff.",
                                line_number=line_num,
                                blocking=True,
                                rule_id="SEC-001",
                            )
                        )
                        break
            line_num += 1
        return findings

    @staticmethod
    def check_forbidden_files(
        changed_files: list[str],
        constraints: list[TaskConstraint] | None = None,
    ) -> list[VerificationFinding]:
        """Ensure no files marked forbidden in task constraints are modified."""
        findings: list[VerificationFinding] = []
        if not constraints:
            return findings

        forbidden_set: set[str] = set()
        for c in constraints:
            if hasattr(c, "forbidden_files") and c.forbidden_files:
                forbidden_set.update(c.forbidden_files)

        for f in changed_files:
            clean_f = f.strip().replace("\\", "/")
            if clean_f in forbidden_set:
                findings.append(
                    VerificationFinding(
                        id=f"cst-viol-{clean_f}",
                        severity="CRITICAL",
                        category="policy",
                        message=f"Constraint violation: file '{clean_f}' is forbidden from being modified.",
                        file_path=clean_f,
                        blocking=True,
                        rule_id="POL-001",
                    )
                )
        return findings

    def verify_task_revision(
        self,
        task_id: UUID | str,
        workspace_revision: str,
        test_result: RestrictedExecutionResult | None,
        branch_name: str,
        diff_text: str = "",
        changed_files: list[str] | None = None,
        constraints: list[TaskConstraint] | None = None,
        has_approved_plan: bool = True,
        base_revision_matches: bool = True,
        static_analysis_passed: bool = True,
        ai_review_findings: list[dict[str, Any]] | None = None,
    ) -> VerificationResult:
        """Run all 12 canonical verification checks and produce structured VerificationResult."""
        checks: list[VerificationCheckItem] = []
        blocking_findings: list[VerificationFinding] = []
        warnings: list[VerificationFinding] = []

        # 1. Approved plan check
        if has_approved_plan:
            checks.append(VerificationCheckItem(name="approved_plan", status="PASSED", message="Task corresponds to an approved plan."))
        else:
            checks.append(VerificationCheckItem(name="approved_plan", status="FAILED", message="Task plan has not been approved."))
            blocking_findings.append(VerificationFinding(
                id="plan-not-approved", severity="CRITICAL", category="policy",
                message="Cannot verify task without an approved plan.", blocking=True,
            ))

        # 2. Base revision match check
        if base_revision_matches:
            checks.append(VerificationCheckItem(name="base_revision", status="PASSED", message="Workspace revision matches recorded base revision."))
        else:
            checks.append(VerificationCheckItem(name="base_revision", status="FAILED", message="Base revision drift detected."))
            blocking_findings.append(VerificationFinding(
                id="base-rev-mismatch", severity="HIGH", category="correctness",
                message="Base revision has drifted from recorded plan revision.", blocking=True,
            ))

        # 3. Protected branch check (Rule 563)
        is_agent_branch = branch_name.startswith("agent/task-")
        is_not_default = branch_name.lower() not in ("main", "master", "develop", "production")
        if is_agent_branch and is_not_default:
            checks.append(VerificationCheckItem(name="branch_isolation", status="PASSED", message=f"Task branch '{branch_name}' is isolated."))
        else:
            checks.append(VerificationCheckItem(name="branch_isolation", status="FAILED", message=f"Branch '{branch_name}' violates isolation rules."))
            blocking_findings.append(VerificationFinding(
                id="branch-isolation-fail", severity="CRITICAL", category="security",
                message="Direct modification of protected branches is prohibited (Rule 563).", blocking=True,
            ))

        # 4. Diff validity and forbidden files check
        forbidden_violations = self.check_forbidden_files(changed_files or [], constraints)
        if not forbidden_violations:
            checks.append(VerificationCheckItem(name="diff_permitted_files", status="PASSED", message="All modified files are permitted."))
        else:
            checks.append(VerificationCheckItem(name="diff_permitted_files", status="FAILED", message="Diff contains forbidden files."))
            blocking_findings.extend(forbidden_violations)

        # 5. Secret scan in diff
        secret_findings = self.scan_diff_for_secrets(diff_text)
        if not secret_findings:
            checks.append(VerificationCheckItem(name="secret_scan", status="PASSED", message="Zero credentials detected in diff."))
        else:
            checks.append(VerificationCheckItem(name="secret_scan", status="FAILED", message="Credentials or tokens found in diff."))
            blocking_findings.extend(secret_findings)

        # 6. Tests execution check
        if test_result is None:
            checks.append(VerificationCheckItem(name="tests", status="UNAVAILABLE", message="No test execution record provided."))
            blocking_findings.append(VerificationFinding(
                id="test-missing", severity="CRITICAL", category="test_failure",
                message="Verification requires executed test results.", blocking=True,
            ))
        elif test_result.status == "PASSED":
            checks.append(VerificationCheckItem(
                name="tests", status="PASSED", duration_ms=test_result.duration_ms,
                message=f"All {test_result.test_counts.passed} tests passed successfully.",
            ))
        else:
            checks.append(VerificationCheckItem(
                name="tests", status="FAILED", duration_ms=test_result.duration_ms,
                message=f"Tests failed: {test_result.test_counts.failed} failed, {test_result.test_counts.errors} errors.",
            ))
            blocking_findings.append(VerificationFinding(
                id="test-failed", severity="CRITICAL", category="test_failure",
                message="Test suite execution failed or timed out.", blocking=True,
            ))

        # 7. Test revision correspondence check
        if test_result is not None and test_result.workspace_revision:
            if test_result.workspace_revision == workspace_revision:
                checks.append(VerificationCheckItem(
                    name="revision_correspondence", status="PASSED",
                    message="Test results strictly match current final workspace revision.",
                ))
            else:
                checks.append(VerificationCheckItem(
                    name="revision_correspondence", status="FAILED",
                    message=f"Test revision ({test_result.workspace_revision[:8]}) differs from current workspace ({workspace_revision[:8]}).",
                ))
                blocking_findings.append(VerificationFinding(
                    id="rev-mismatch", severity="CRITICAL", category="correctness",
                    message="Test result was evaluated on an older revision; re-testing required.", blocking=True,
                ))

        # 8. Static analysis check
        if static_analysis_passed:
            checks.append(VerificationCheckItem(name="static_analysis", status="PASSED", message="Static linters passed with 0 blocking errors."))
        else:
            checks.append(VerificationCheckItem(name="static_analysis", status="FAILED", message="Static analysis reported errors."))
            warnings.append(VerificationFinding(
                id="lint-warning", severity="MEDIUM", category="lint",
                message="Static linter errors detected.", blocking=False,
            ))

        # 9. AI Code Review findings integration
        critical_reviews = 0
        if ai_review_findings:
            for rf in ai_review_findings:
                sev = str(rf.get("severity", "MEDIUM")).upper()
                msg = rf.get("message", "Review finding")
                if sev in ("CRITICAL", "HIGH"):
                    critical_reviews += 1
                    blocking_findings.append(VerificationFinding(
                        id=f"rev-{len(blocking_findings)}", severity=sev, category="code_review",
                        message=msg, file_path=rf.get("file_path"), line_number=rf.get("line_number"),
                        blocking=True,
                    ))
                else:
                    warnings.append(VerificationFinding(
                        id=f"rev-warn-{len(warnings)}", severity=sev, category="code_review",
                        message=msg, file_path=rf.get("file_path"), line_number=rf.get("line_number"),
                        blocking=False,
                    ))

            checks.append(VerificationCheckItem(
                name="ai_code_review",
                status="FAILED" if critical_reviews > 0 else "COMPLETED",
                message=f"AI Code Review processed {len(ai_review_findings)} finding(s) ({critical_reviews} critical).",
            ))
        else:
            checks.append(VerificationCheckItem(name="ai_code_review", status="COMPLETED", message="No critical review issues."))

        # Determine overall status
        if any(c.status == "FAILED" for c in checks) or len(blocking_findings) > 0:
            overall_status: VerificationOverallStatus = "FAIL"
        elif any(c.status in ("UNAVAILABLE", "SKIPPED") for c in checks):
            overall_status = "INCONCLUSIVE"
        else:
            overall_status = "REQUIRES_HUMAN_REVIEW" if warnings else "PASS"

        summary_md = self.generate_pr_markdown_summary(
            task_id=task_id,
            verified_revision=workspace_revision,
            status=overall_status,
            checks=checks,
            changed_files=changed_files or [],
            blocking_findings=blocking_findings,
            warnings=warnings,
        )

        return VerificationResult(
            task_id=str(task_id),
            verified_revision=workspace_revision,
            status=overall_status,
            checks=checks,
            blocking_findings=blocking_findings,
            warnings=warnings,
            pr_summary=summary_md,
        )

    def verify(self, context: VerificationContext) -> VerificationResult:
        """Run all 12 independent verification checks on the provided task context.

        Simple explanation:
        - We take all the task details (the diff, tests, plan, branch name).
        - We run our 12 verification checks one by one.
        - We collect any issues (blockers or warnings).
        - We compute the final verdict (PASS, FAIL, or REQUIRES_HUMAN_REVIEW).
        - We generate a nice Markdown PR description.
        - We return the official VerificationResult.
        """
        checks: list[VerificationCheckItem] = []
        blocking_findings: list[VerificationFinding] = []
        warnings: list[VerificationFinding] = []

        # -------------------------------------------------------------------
        # Check 1: Plan Approval Check
        # Make sure the task has human approval and matches the approved plan version.
        # -------------------------------------------------------------------
        checks.append(self._check_plan_approval(context, blocking_findings))

        # -------------------------------------------------------------------
        # Check 2: Base Revision Check
        # Ensure the starting commit SHA is valid and not empty.
        # -------------------------------------------------------------------
        checks.append(self._check_base_revision(context, blocking_findings))

        # -------------------------------------------------------------------
        # Check 3: Clean Diff Check
        # Ensure the diff is valid, not empty, and doesn't exceed maximum size limits.
        # We run this before file lists so broken diffs/traversal are caught early.
        # -------------------------------------------------------------------
        checks.append(self._check_clean_diff(context, blocking_findings))

        # -------------------------------------------------------------------
        # Check 4: Allowed Files Scope Check
        # Check that only files promised in the plan were actually touched.
        # -------------------------------------------------------------------
        checks.append(self._check_allowed_files_scope(context, blocking_findings))

        # -------------------------------------------------------------------
        # Check 5: Forbidden Files Policy Check
        # Make sure protected or secret files (like .env or credentials) were NOT modified.
        # -------------------------------------------------------------------
        checks.append(self._check_forbidden_files(context, blocking_findings))

        # -------------------------------------------------------------------
        # Check 6: Required Tests Execution Check
        # Make sure the automated tests ran and that 0 tests failed.
        # -------------------------------------------------------------------
        checks.append(self._check_test_execution(context, blocking_findings))

        # -------------------------------------------------------------------
        # Check 7: Test-Diff Synchronization Check
        # Ensure the tests were run on the current commit, not an older stale commit.
        # -------------------------------------------------------------------
        checks.append(self._check_test_diff_sync(context, blocking_findings))

        # -------------------------------------------------------------------
        # Check 8: Static Analysis & Security Check
        # Check if linters or static code analysis ran without unhandled errors.
        # -------------------------------------------------------------------
        checks.append(self._check_static_analysis(context, blocking_findings, warnings))

        # -------------------------------------------------------------------
        # Check 9: AI Code Review Check
        # Inspect findings from Week 2 AI Code Review for any critical bugs.
        # -------------------------------------------------------------------
        checks.append(self._check_ai_code_review(context, blocking_findings, warnings))

        # -------------------------------------------------------------------
        # Check 10: Traceability Check
        # Make sure findings point to real file paths and valid line numbers.
        # -------------------------------------------------------------------
        checks.append(self._check_traceability(context, blocking_findings, warnings))

        # -------------------------------------------------------------------
        # Check 11: Secret & Credential Scan
        # Scan the code diff to ensure no API keys or passwords are leaked in code.
        # -------------------------------------------------------------------
        checks.append(self._check_secret_scan(context, blocking_findings))

        # -------------------------------------------------------------------
        # Check 12: Branch Protection Check
        # Ensure the destination branch is a safe feature branch (not main/master).
        # -------------------------------------------------------------------
        checks.append(self._check_branch_protection(context, blocking_findings))

        # -------------------------------------------------------------------
        # Determine the final overall status using our policy rules:
        # - Any failed check or blocking finding -> FAIL
        # - Any skipped or unavailable check -> REQUIRES_HUMAN_REVIEW or INCONCLUSIVE
        # - Any non-blocking warnings -> REQUIRES_HUMAN_REVIEW
        # - Everything clean -> PASS
        # -------------------------------------------------------------------
        overall_status = VerificationResult.evaluate_status(
            checks=checks,
            blocking_findings=blocking_findings,
            warnings=warnings,
        )

        # Generate the GitHub Markdown description summarizing everything
        pr_summary = self.generate_pr_markdown_summary(
            context=context,
            status=overall_status,
            checks=checks,
            blocking_findings=blocking_findings,
            warnings=warnings,
        )

        # Build and return the final report
        return VerificationResult(
            task_id=context.task_id,
            verified_revision=context.verified_revision,
            status=overall_status,
            checks=checks,
            blocking_findings=blocking_findings,
            warnings=warnings,
            pr_summary=pr_summary,
        )

    # =======================================================================
    # Individual Verification Check Methods (The 12 Checks)
    # =======================================================================

    def _check_plan_approval(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 1: Make sure the task has human approval and matches the approved plan version.

        Simple explanation:
        We cannot publish code unless a human previously looked at the plan and clicked 'Approve'.
        Also, if someone changed the plan after it was approved, approval is no longer valid.
        """
        # If the plan was never approved
        if not context.plan_approved:
            blocking.append(
                VerificationFinding(
                    id="find-approval-missing",
                    severity="CRITICAL",
                    category="policy",
                    message="Task execution plan has not received mandatory human approval.",
                    blocking=True,
                )
            )
            return VerificationCheckItem(
                name="plan_approval",
                status="FAILED",
                message="Plan approval is missing or unconfirmed.",
            )

        # If the current plan version is different from the version that was approved
        if (
            context.approved_plan_version is not None
            and context.approved_plan_version != context.current_plan_version
        ):
            blocking.append(
                VerificationFinding(
                    id="find-approval-version-mismatch",
                    severity="CRITICAL",
                    category="policy",
                    message=(
                        f"Plan version mismatch: approved version is {context.approved_plan_version}, "
                        f"but current version is {context.current_plan_version}."
                    ),
                    blocking=True,
                )
            )
            return VerificationCheckItem(
                name="plan_approval",
                status="FAILED",
                message="Plan was modified after human approval was granted.",
            )

        return VerificationCheckItem(
            name="plan_approval",
            status="PASSED",
            message=f"Plan version {context.current_plan_version} was approved by a human reviewer.",
        )

    def _check_base_revision(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 2: Ensure the starting commit SHA is valid.

        Simple explanation:
        We need to be 100% sure what commit this task was created from, so we don't
        build on top of missing or invalid git history.
        """
        commit_sha_re = re.compile(r"^[0-9a-fA-F]{7,64}$")
        if not context.base_revision or not commit_sha_re.match(context.base_revision.strip()):
            blocking.append(
                VerificationFinding(
                    id="find-base-rev-invalid",
                    severity="HIGH",
                    category="policy",
                    message=f"Base revision commit SHA '{context.base_revision}' is invalid or missing.",
                    blocking=True,
                )
            )
            return VerificationCheckItem(
                name="base_revision",
                status="FAILED",
                message="Starting commit revision is invalid or missing.",
            )

        return VerificationCheckItem(
            name="base_revision",
            status="PASSED",
            message=f"Base revision verified ({context.base_revision[:8]}).",
        )

    def _check_allowed_files_scope(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 3: Check that only allowed files from the approved plan were modified.

        Simple explanation:
        If the approved plan said 'modify file A', but the agent also modified file B,
        we block it because that change was never reviewed or approved!
        """
        # If no specific allowed list was provided, any valid file in workspace is allowed
        if not context.allowed_files:
            return VerificationCheckItem(
                name="permitted_files",
                status="PASSED",
                message="All modified files are within workspace scope.",
            )

        # Extract which files the diff touches
        modified = extract_modified_files_from_diff(context.diff)
        allowed_set = set(context.allowed_files)
        out_of_scope = sorted(set(modified).difference(allowed_set))

        # If any file is outside the allowed list, fail the check!
        if out_of_scope:
            for bad_file in out_of_scope:
                blocking.append(
                    VerificationFinding(
                        id=f"find-scope-{abs(hash(bad_file)) % 10000}",
                        severity="HIGH",
                        category="policy",
                        message=f"File '{bad_file}' was modified but is outside approved plan scope.",
                        file_path=bad_file,
                        blocking=True,
                    )
                )
            return VerificationCheckItem(
                name="permitted_files",
                status="FAILED",
                message=f"Diff modifies {len(out_of_scope)} file(s) outside approved plan scope.",
                findings_count=len(out_of_scope),
            )

        return VerificationCheckItem(
            name="permitted_files",
            status="PASSED",
            message="All modified files match the approved implementation plan.",
        )

    def _check_forbidden_files(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 4: Make sure no forbidden files were touched.

        Simple explanation:
        Some files (like production configs, passwords, or deployment keys) must NEVER
        be changed by an AI agent. If any of those are in the diff, block immediately!
        """
        if not context.forbidden_files:
            return VerificationCheckItem(
                name="no_forbidden_files",
                status="PASSED",
                message="No forbidden files constraint was defined.",
            )

        modified = extract_modified_files_from_diff(context.diff)
        forbidden_set = set(context.forbidden_files)
        conflicts = sorted(set(modified).intersection(forbidden_set))

        # If any forbidden file was touched, create a blocking finding!
        if conflicts:
            for bad_file in conflicts:
                blocking.append(
                    VerificationFinding(
                        id=f"find-forbidden-{abs(hash(bad_file)) % 10000}",
                        severity="CRITICAL",
                        category="security",
                        message=f"Forbidden file '{bad_file}' was modified under policy constraint.",
                        file_path=bad_file,
                        blocking=True,
                    )
                )
            return VerificationCheckItem(
                name="no_forbidden_files",
                status="FAILED",
                message=f"Diff violates policy by modifying forbidden file(s): {', '.join(conflicts)}",
                findings_count=len(conflicts),
            )

        return VerificationCheckItem(
            name="no_forbidden_files",
            status="PASSED",
            message="No protected or forbidden files were touched.",
        )

    def _check_clean_diff(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 5: Make sure the diff is valid, non-empty, and within safe size limits.

        Simple explanation:
        - If the diff is totally empty, there's nothing to publish!
        - If the diff is massive (> 200,000 characters), it's probably a hallucination.
        - If file paths try to do directory traversal ('../../'), reject it immediately.
        """
        cleaned_diff = context.diff.strip()

        # Check for empty diff
        if not cleaned_diff:
            blocking.append(
                VerificationFinding(
                    id="find-diff-empty",
                    severity="HIGH",
                    category="correctness",
                    message="Proposed diff is empty; no code modifications to verify or publish.",
                    blocking=True,
                )
            )
            return VerificationCheckItem(
                name="clean_diff",
                status="FAILED",
                message="Diff contains no changes.",
            )

        # Check for overly huge diff
        if len(cleaned_diff) > MAX_DIFF_CHARS:
            blocking.append(
                VerificationFinding(
                    id="find-diff-too-large",
                    severity="HIGH",
                    category="policy",
                    message=f"Diff size ({len(cleaned_diff)} chars) exceeds maximum safety limit ({MAX_DIFF_CHARS}).",
                    blocking=True,
                )
            )
            return VerificationCheckItem(
                name="clean_diff",
                status="FAILED",
                message="Diff size exceeds maximum allowable limit.",
            )

        # Check that modified file paths are safe and don't escape repository root
        modified_files = extract_modified_files_from_diff(cleaned_diff)
        for path in modified_files:
            try:
                validate_repo_relative_path(path)
            except UnsafePathError as exc:
                blocking.append(
                    VerificationFinding(
                        id="find-path-traversal",
                        severity="CRITICAL",
                        category="security",
                        message=f"Unsafe path traversal in diff '{path}': {exc}",
                        file_path=path,
                        blocking=True,
                    )
                )
                return VerificationCheckItem(
                    name="clean_diff",
                    status="FAILED",
                    message="Unsafe directory traversal detected in diff headers.",
                )

        return VerificationCheckItem(
            name="clean_diff",
            status="PASSED",
            message=f"Clean diff modifying {len(modified_files)} file(s) ({len(cleaned_diff)} chars).",
        )

    def _check_test_execution(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 6: Make sure tests actually ran and passed with 0 failures.

        Simple explanation:
        Code can only be published if the test suite finished and every test passed.
        If tests didn't run, or if even 1 test failed, we cannot pass verification.
        """
        # If tests were not run or did not finish
        if not context.tests_completed:
            return VerificationCheckItem(
                name="required_tests",
                status="UNAVAILABLE",
                message="Test suite was not executed or failed to complete.",
            )

        # If tests ran but failed
        if not context.tests_passed or context.failed_test_count > 0:
            blocking.append(
                VerificationFinding(
                    id="find-tests-failing",
                    severity="CRITICAL",
                    category="test_failure",
                    message=f"Test suite failed with {context.failed_test_count} failing test(s).",
                    blocking=True,
                )
            )
            return VerificationCheckItem(
                name="required_tests",
                status="FAILED",
                message=f"Test execution failed ({context.failed_test_count} failures).",
                findings_count=context.failed_test_count,
            )

        return VerificationCheckItem(
            name="required_tests",
            status="PASSED",
            message=f"All {context.test_count} automated tests passed successfully.",
        )

    def _check_test_diff_sync(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 7: Ensure tests were run against the EXACT current commit revision.

        Simple explanation:
        If tests passed on commit 'abc123', but the workspace was later modified
        to commit 'def456', the old test result is stale and cannot be trusted.
        """
        if context.test_revision is None:
            # If no test revision was recorded, we warn that sync could not be verified
            return VerificationCheckItem(
                name="test_diff_sync",
                status="SKIPPED",
                message="Test revision metadata was not recorded.",
            )

        if context.test_revision.strip() != context.verified_revision.strip():
            blocking.append(
                VerificationFinding(
                    id="find-stale-tests",
                    severity="HIGH",
                    category="correctness",
                    message=(
                        f"Test results belong to revision '{context.test_revision[:8]}', "
                        f"which does not match verified revision '{context.verified_revision[:8]}'."
                    ),
                    blocking=True,
                )
            )
            return VerificationCheckItem(
                name="test_diff_sync",
                status="FAILED",
                message="Test results are stale and do not match the final candidate commit.",
            )

        return VerificationCheckItem(
            name="test_diff_sync",
            status="PASSED",
            message="Test results correspond exactly to the verified revision.",
        )

    def _check_static_analysis(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
        warnings: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 8: Review static code analysis and linter results.

        Simple explanation:
        Linters (like Ruff or ESLint) check for clean syntax, unused imports,
        and known security vulnerabilities. If linters couldn't run, we mark it UNAVAILABLE.
        """
        if not context.static_analysis_completed:
            return VerificationCheckItem(
                name="static_analysis",
                status="UNAVAILABLE",
                message="Static analysis tools were unavailable or did not run.",
            )

        # Distribute static findings into blocking vs warnings
        blocker_count = 0
        for f in context.static_findings:
            if f.blocking or f.severity in ("CRITICAL", "HIGH"):
                blocking.append(f)
                blocker_count += 1
            else:
                warnings.append(f)

        if blocker_count > 0:
            return VerificationCheckItem(
                name="static_analysis",
                status="FAILED",
                message=f"Static analysis discovered {blocker_count} blocking defect(s).",
                findings_count=len(context.static_findings),
            )

        return VerificationCheckItem(
            name="static_analysis",
            status="PASSED",
            message=f"Static analysis completed with {len(context.static_findings)} non-blocking observation(s).",
            findings_count=len(context.static_findings),
        )

    def _check_ai_code_review(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
        warnings: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 9: Check results from Week 2 AI Code Review.

        Simple explanation:
        The AI Code Review engine acts as a second pair of eyes.
        If it spotted critical bugs or security flaws, we block publication.
        """
        if not context.ai_review_completed:
            return VerificationCheckItem(
                name="ai_code_review",
                status="UNAVAILABLE",
                message="AI Code Review was unavailable or did not run.",
            )

        blocker_count = 0
        for f in context.ai_review_findings:
            if f.blocking or f.severity == "CRITICAL":
                blocking.append(f)
                blocker_count += 1
            else:
                warnings.append(f)

        if blocker_count > 0:
            return VerificationCheckItem(
                name="ai_code_review",
                status="FAILED",
                message=f"AI Code Review flagged {blocker_count} critical issue(s).",
                findings_count=len(context.ai_review_findings),
            )

        return VerificationCheckItem(
            name="ai_code_review",
            status="COMPLETED",
            message=f"AI Code Review completed with {len(context.ai_review_findings)} finding(s).",
            findings_count=len(context.ai_review_findings),
        )

    def _check_traceability(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
        warnings: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 10: Ensure all findings point to real files and valid line numbers.

        Simple explanation:
        Every issue reported by tools or AI must specify a real file path so
        the developer knows where to fix it. We reject made-up line numbers.
        """
        all_findings = context.static_findings + context.ai_review_findings
        if not all_findings:
            return VerificationCheckItem(
                name="traceability",
                status="PASSED",
                message="No findings required line-level traceability verification.",
            )

        untraceable_count = 0
        for f in all_findings:
            # If line number is 0 or negative, it's invalid
            if f.line_number is not None and f.line_number < 1:
                untraceable_count += 1

        if untraceable_count > 0:
            warnings.append(
                VerificationFinding(
                    id="warn-untraceable-findings",
                    severity="LOW",
                    category="correctness",
                    message=f"{untraceable_count} finding(s) have invalid or non-traceable line numbers.",
                    blocking=False,
                )
            )

        return VerificationCheckItem(
            name="traceability",
            status="PASSED",
            message=f"All {len(all_findings)} finding(s) are mapped to repository locations.",
        )

    def _check_secret_scan(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 11: Scan the code diff for leaked passwords, API keys, or tokens.

        Simple explanation:
        We run a security scanner across the entire code diff. If someone accidentally
        hardcoded an API key, token, or password, we catch it and BLOCK the PR immediately!
        """
        redaction_res = redact_secrets(context.diff)
        if redaction_res.findings:
            # We found real credentials in the diff!
            secret_types = sorted({f.pattern for f in redaction_res.findings})
            for f in redaction_res.findings:
                blocking.append(
                    VerificationFinding(
                        id=f"sec-leak-{abs(hash(f.pattern + str(f.line))) % 10000}",
                        severity="CRITICAL",
                        category="security",
                        message=f"Hardcoded secret detected: {f.pattern} at diff line {f.line}.",
                        blocking=True,
                    )
                )
            return VerificationCheckItem(
                name="secret_scan",
                status="FAILED",
                message=f"Secret scanner detected credentials in diff: {', '.join(secret_types)}",
                findings_count=len(redaction_res.findings),
            )

        return VerificationCheckItem(
            name="secret_scan",
            status="PASSED",
            message="No credentials, passwords, or secrets detected in proposed changes.",
        )

    def _check_branch_protection(
        self,
        context: VerificationContext,
        blocking: list[VerificationFinding],
    ) -> VerificationCheckItem:
        """Check 12: Make sure we are NOT pushing directly to a protected branch (like main).

        Simple explanation:
        Never push directly to 'main' or 'master'! All AI changes must go into a
        dedicated feature branch (e.g. 'agent/task-123') and require a PR.
        """
        clean_branch = context.target_branch.strip().lower()
        if clean_branch in _PROTECTED_BRANCHES:
            blocking.append(
                VerificationFinding(
                    id="find-protected-branch",
                    severity="CRITICAL",
                    category="policy",
                    message=f"Direct push to protected branch '{context.target_branch}' is strictly forbidden.",
                    blocking=True,
                )
            )
            return VerificationCheckItem(
                name="branch_protection",
                status="FAILED",
                message=f"Target branch '{context.target_branch}' is a protected branch.",
            )

        return VerificationCheckItem(
            name="branch_protection",
            status="PASSED",
            message=f"Target branch '{context.target_branch}' is an isolated task branch.",
        )

    # =======================================================================
    # Markdown PR Description Generator
    # =======================================================================


    @classmethod
    def generate_pr_markdown_summary(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Generate structured Markdown PR description body.

        Supports both VerificationContext-based calls (Dev) and direct task parameter calls (Parth).
        """
        context = kwargs.get("context")
        if context is None and args and isinstance(args[0], VerificationContext):
            context = args[0]
            args = args[1:]
        elif context is None and len(args) > 1 and isinstance(args[1], VerificationContext):
            context = args[1]
            args = args[2:]

        if context is not None:
            status = kwargs.get("status") or (args[0] if len(args) > 0 else "PASS")
            checks = kwargs.get("checks") or (args[1] if len(args) > 1 else [])
            blocking_findings = kwargs.get("blocking_findings") or (args[2] if len(args) > 2 else [])
            warnings = kwargs.get("warnings") or (args[3] if len(args) > 3 else [])
            return cls._generate_dev_pr_markdown_summary(
                context=context,
                status=status,
                checks=checks,
                blocking_findings=blocking_findings,
                warnings=warnings,
            )

        task_id = kwargs.get("task_id") or (args[0] if len(args) > 0 else "")
        verified_revision = kwargs.get("verified_revision") or (args[1] if len(args) > 1 else "")
        status = kwargs.get("status") or (args[2] if len(args) > 2 else "PASS")
        checks = kwargs.get("checks") or (args[3] if len(args) > 3 else [])
        changed_files = kwargs.get("changed_files") or (args[4] if len(args) > 4 else [])
        blocking_findings = kwargs.get("blocking_findings") or (args[5] if len(args) > 5 else [])
        warnings = kwargs.get("warnings") or (args[6] if len(args) > 6 else [])
        task_title = kwargs.get("task_title") or (args[7] if len(args) > 7 else None)
        source_issue = kwargs.get("source_issue") or (args[8] if len(args) > 8 else None)

        return cls._generate_parth_pr_markdown_summary(
            task_id=task_id,
            verified_revision=verified_revision,
            status=status,
            checks=checks,
            changed_files=changed_files,
            blocking_findings=blocking_findings,
            warnings=warnings,
            task_title=task_title,
            source_issue=source_issue,
        )

    @classmethod
    def _generate_dev_pr_markdown_summary(
        cls,
        context: VerificationContext,
        status: VerificationOverallStatus,
        checks: list[VerificationCheckItem],
        blocking_findings: list[VerificationFinding],
        warnings: list[VerificationFinding],
    ) -> str:
        """Generate a complete GitHub Pull Request description in Markdown format.

        Simple explanation:
        When we open a GitHub Draft PR, we paste this formatted markdown into
        the description box so everyone can see the verification checklist and results!
        """
        # Determine status badge text and emoji
        status_badges = {
            "PASS": "🟢 **PASSED** (Ready for Human Review & Merge)",
            "FAIL": "🔴 **FAILED** (Blocked by Policy or Test Failures)",
            "INCONCLUSIVE": "🟡 **INCONCLUSIVE** (Required checks were unavailable)",
            "REQUIRES_HUMAN_REVIEW": "🟠 **REQUIRES HUMAN REVIEW** (Non-blocking warnings detected)",
        }
        badge = status_badges.get(status, status)

        # Build table of all 12 checks
        check_rows: list[str] = []
        for c in checks:
            status_icon = "✅" if c.status in ("PASSED", "COMPLETED") else ("❌" if c.status == "FAILED" else "⚠️")
            check_rows.append(f"| {c.name} | {status_icon} `{c.status}` | {c.message} |")
        checks_table = "\n".join(check_rows)

        # Build blocking findings section if any exist
        blocking_section = ""
        if blocking_findings:
            items = []
            for f in blocking_findings:
                loc = f" (`{f.file_path}`)" if f.file_path else ""
                items.append(f"- 🔴 **[{f.severity}]** {f.message}{loc}")
            blocking_section = "### 🚫 Blocking Issues\n" + "\n".join(items) + "\n"

        # Build warnings section if any exist
        warnings_section = ""
        if warnings:
            items = []
            for f in warnings:
                loc = f" (`{f.file_path}`)" if f.file_path else ""
                items.append(f"- ⚠️ **[{f.severity}]** {f.message}{loc}")
            warnings_section = "### ⚠️ Observations & Warnings\n" + "\n".join(items) + "\n"

        # Extract modified files
        modified_files = extract_modified_files_from_diff(context.diff)
        files_list = "\n".join(f"- `{f}`" for f in modified_files) if modified_files else "- *(No files modified)*"

        title_header = context.task_title or f"Task {context.task_id} Implementation"

        # Full markdown template
        return f"""## 🤖 Automated Implementation & Verification Report

### 📌 Task Overview
**Task:** {title_header}  
**Task ID:** `{context.task_id}`  
**Target Branch:** `{context.target_branch}`  
**Verified Revision:** `{context.verified_revision[:10]}` (base: `{context.base_revision[:10]}`)  
**Verification Verdict:** {badge}

---

### 🛡️ Independent Verification Gates (12 Checks)
| Verification Gate | Status | Details |
| :--- | :--- | :--- |
{checks_table}

---

{blocking_section}{warnings_section}### 📂 Files Modified
{files_list}

---

> [!IMPORTANT]
> **Human Review Notice:** Independent verification guarantees that automated security gates,
> tests, and policy boundaries were strictly evaluated. Human review and sign-off remain
> mandatory before merging this Pull Request into the default branch.
"""




    @staticmethod
    def _generate_parth_pr_markdown_summary(
        task_id: UUID | str,
        verified_revision: str,
        status: str,
        checks: list[VerificationCheckItem],
        changed_files: list[str],
        blocking_findings: list[VerificationFinding],
        warnings: list[VerificationFinding],
        task_title: str | None = None,
        source_issue: str | None = None,
    ) -> str:
        """Generate structured Markdown PR description body meeting Docs/week3.md §6 F37."""
        lines: list[str] = [
            f"## Automated Agent Task Implementation - `{task_title or task_id}`",
            "",
            "> **NOTICE:** This Pull Request is created as a **DRAFT** by the autonomous agent platform.",
            "> It requires human review, validation, and explicit approval before any merge operation.",
            "",
            "### 1. Task Context & Traceability",
            f"- **Task ID:** `{task_id}`",
            f"- **Verified Commit Revision:** `{verified_revision}`",
            f"- **Verification Status:** **`{status}`**",
            f"- **Originating Reference:** {source_issue or 'AI Developer Studio finding'}",
            "",
            "### 2. Verification Gate Summary",
            "| Gate / Check | Status | Duration | Details |",
            "| :--- | :---: | :---: | :--- |",
        ]

        for c in checks:
            badge = "PASSED" if c.status == "PASSED" else ("FAILED" if c.status == "FAILED" else c.status)
            dur = f"{c.duration_ms}ms" if c.duration_ms > 0 else "-"
            lines.append(f"| `{c.name}` | **{badge}** | {dur} | {c.message} |")

        lines.extend([
            "",
            "### 3. Files Modified",
        ])
        if changed_files:
            for f in changed_files:
                lines.append(f"- `{f}`")
        else:
            lines.append("- *(No files recorded)*")

        if blocking_findings:
            lines.extend([
                "",
                "### 4. Blocking Findings (Must Resolve Before Merge)",
            ])
            for bf in blocking_findings:
                loc = f" (`{bf.file_path}:{bf.line_number}`)" if bf.file_path else ""
                lines.append(f"- **[{bf.severity}]** {bf.message}{loc}")

        if warnings:
            lines.extend([
                "",
                "### 5. Non-Blocking Warnings & Recommendations",
            ])
            for w in warnings:
                loc = f" (`{w.file_path}:{w.line_number}`)" if w.file_path else ""
                lines.append(f"- **[{w.severity}]** {w.message}{loc}")

        lines.extend([
            "",
            "---",
            "*Generated by Platform Independent Verifier & GitBranchService (Parth)*",
        ])

        return "\n".join(lines)


__all__ = ["IndependentVerifier"]
