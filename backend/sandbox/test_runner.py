"""Restricted Test Runner & Execution Loop for Isolated Workspaces.

Owner: Prit Zania — Week 3 Day 4 Deliverable (Docs/week3.md §6 F35, §8 Day 4, line 634)
Reference:
- Docs/week3.md §6 (F35 Test Runner and Bounded Repair Loop)
- Docs/week3.md §8 (Day 4 Code Changes, Test Execution and Bounded Repair)
- Docs/week3.md §11 (Scenario D: Test failure and repair exhaustion)
- Docs/daily_tasks.md (line 634: Prit Restricted test runner executing pytest or npm test)
- ADR-007 (Sandbox Isolation), ADR-010 (Mandatory Human Approval Gate & Bounded Repair Loop)

Key Capabilities:
1. Detects or reads repository test configuration (pytest, unittest, jest).
2. Explicitly handles unsupported frameworks (vitest, go test) and ambiguous configurations without crashing.
3. Enforces command allowlists and prevents unauthorized package/dependency installation.
4. Executes tests strictly within the task workspace directory (cwd=workspace_path).
5. Enforces hard timeout budgets (default 60s, max 300s) and bounds output capture (100 KB max).
6. Strips sensitive host environment variables and redacts secrets from test logs.
7. Parses exit codes, duration, test counts (passed, failed, skipped, error), and failing test names.
8. Classifies failures into TEST_FAILURE (repair eligible) vs INFRASTRUCTURE_ERROR / TIMEOUT / SECURITY_VIOLATION.
9. Enforces the strict 3-attempt ceiling on the task-level self-repair loop per ADR-010.
10. Detects and rejects duplicate failed patch signatures to avoid infinite loops.
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from app.core.secret_redaction import redact
from app.schemas.workspace import (
    RepairAttemptRecord,
    TestFailureClassification,
    TestOutcomeStatus,
    WorkspaceRepairBudgetStatus,
    WorkspaceTestExecutionRequest,
    WorkspaceTestExecutionResult,
)
from sandbox.command_runner import WorkspaceCommandRunner
from sandbox.constants import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    DISALLOWED_COMMAND_TOKENS,
    MAX_COMMAND_OUTPUT_BYTES,
    MAX_TIMEOUT_SECONDS,
)
from sandbox.exceptions import (
    WorkspaceDuplicateRepairPatchError,
    WorkspacePathEscapeError,
    WorkspacePolicyViolationError,
    WorkspaceRepairBudgetExhaustedError,
    WorkspaceTestExecutionError,
    WorkspaceUnsupportedFrameworkError,
)
from sandbox.path_guard import WorkspacePathGuard
from scanner.framework_detector import FrameworkDetectionResult, FrameworkDetector

logger = logging.getLogger(__name__)

# Hard task-level repair budget ceiling per ADR-010 & Docs/week3.md §6 F35
MAX_REPAIR_ATTEMPTS: int = 3

# Permitted test runner commands
ALLOWED_TEST_RUNNERS: frozenset[str] = frozenset(
    {"pytest", "python", "python3", "npm", "npx", "node"}
)

# Unsupported runners that must return explicit failure rather than attempting blind execution
UNSUPPORTED_FRAMEWORKS: frozenset[str] = frozenset(
    {"vitest", "mocha", "jasmine", "cargo", "go", "mvn", "gradle"}
)

# Regex patterns for pytest output summary
_PYTEST_SUMMARY_RE = re.compile(
    r"=+\s*(?:(?P<passed>\d+)\s+passed)?(?:,\s*)?"
    r"(?:(?P<failed>\d+)\s+failed)?(?:,\s*)?"
    r"(?:(?P<skipped>\d+)\s+skipped)?(?:,\s*)?"
    r"(?:(?P<errors>\d+)\s+errors?)?(?:,\s*)?"
    r"(?:(?P<warnings>\d+)\s+warnings?)?"
    r"(?:.*in\s+(?P<duration>[\d.]+)s)?\s*=+",
    re.IGNORECASE,
)
_PYTEST_FAILED_ITEM_RE = re.compile(r"FAILED\s+([^\s:]+(?:::[^\s]+)*)", re.IGNORECASE)

# Regex patterns for Jest / npm test summary
_JEST_TESTS_SUMMARY_RE = re.compile(
    r"Tests:\s+(?:(?P<failed>\d+)\s+failed,\s*)?"
    r"(?:(?P<passed>\d+)\s+passed,\s*)?"
    r"(?:(?P<skipped>\d+)\s+skipped,\s*)?"
    r"(?P<total>\d+)\s+total",
    re.IGNORECASE,
)
_JEST_FAILED_ITEM_RE = re.compile(r"●\s+(.+)", re.IGNORECASE)

# Regex patterns for Python unittest summary
_UNITTEST_RAN_RE = re.compile(r"Ran\s+(?P<total>\d+)\s+tests?\s+in\s+(?P<duration>[\d.]+)s", re.IGNORECASE)
_UNITTEST_FAILED_RE = re.compile(r"FAILED\s+\((?:failures=(?P<failures>\d+))?(?:,\s*)?(?:errors=(?P<errors>\d+))?\)", re.IGNORECASE)
_UNITTEST_OK_RE = re.compile(r"OK(?:\s+\(skipped=(?P<skipped>\d+)\))?", re.IGNORECASE)


class WorkspaceTestRunner:
    """Restricted test runner executing project test commands inside isolated workspaces."""

    def __init__(
        self,
        command_runner: WorkspaceCommandRunner | None = None,
        framework_detector: FrameworkDetector | None = None,
        max_output_bytes: int = MAX_COMMAND_OUTPUT_BYTES,
        default_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        max_repair_attempts: int = MAX_REPAIR_ATTEMPTS,
    ) -> None:
        self._command_runner = command_runner or WorkspaceCommandRunner()
        self._framework_detector = framework_detector or FrameworkDetector()
        self._max_output_bytes = max_output_bytes
        self._default_timeout_seconds = default_timeout_seconds
        self._max_repair_attempts = max_repair_attempts

        # In-memory repair attempts and patch signatures indexed by task_id
        self._repair_attempts: dict[str, list[RepairAttemptRecord]] = {}
        self._applied_patch_hashes: dict[str, set[str]] = {}

    # -----------------------------------------------------------------------
    # 1. Framework & Test Command Detection
    # -----------------------------------------------------------------------

    def detect_test_configuration(
        self,
        workspace_root: Path,
        explicit_framework: str | None = None,
    ) -> tuple[str, str, list[str], str]:
        """Determine framework, executable, base arguments, and detection status.

        Returns:
            (framework_name, executable, base_args, status_str)
        """
        # If user/caller explicitly specified a supported framework
        if explicit_framework:
            clean_fw = explicit_framework.strip().lower()
            if clean_fw in UNSUPPORTED_FRAMEWORKS:
                return clean_fw, "", [], "UNSUPPORTED_FRAMEWORK"
            if clean_fw == "pytest":
                return "pytest", "pytest", ["-v"], "CONFIRMED"
            if clean_fw == "unittest":
                return "unittest", "python", ["-m", "unittest", "-v"], "CONFIRMED"
            if clean_fw in ("jest", "npm"):
                return "jest", "npm", ["test", "--"], "CONFIRMED"

        # Otherwise inspect workspace filesystem via FrameworkDetector
        try:
            res: FrameworkDetectionResult = self._framework_detector.detect(repo_root=str(workspace_root))
            if res.is_ambiguous:
                return "ambiguous", "", [], "AMBIGUOUS"

            if res.status == "UNSUPPORTED_FRAMEWORK" or (res.framework and res.framework.lower() in UNSUPPORTED_FRAMEWORKS):
                return str(res.framework or "unknown").lower(), "", [], "UNSUPPORTED_FRAMEWORK"

            if not res.framework or res.status == "NO_CONFIG_FOUND":
                # Fallback check: look for pytest.ini, tests directory or package.json
                if (workspace_root / "pytest.ini").exists() or (workspace_root / "tests").is_dir():
                    return "pytest", "pytest", ["-v"], "CONFIRMED"
                if (workspace_root / "package.json").exists():
                    return "jest", "npm", ["test", "--"], "CONFIRMED"
                return "none", "", [], "NO_CONFIG_FOUND"

            fw_lower = str(res.framework).lower()
            if fw_lower == "pytest":
                return "pytest", "pytest", ["-v"], "CONFIRMED"
            elif fw_lower == "unittest":
                return "unittest", "python", ["-m", "unittest", "-v"], "CONFIRMED"
            elif fw_lower == "jest":
                return "jest", "npm", ["test", "--"], "CONFIRMED"
            else:
                return fw_lower, "", [], "UNSUPPORTED_FRAMEWORK"

        except Exception as exc:
            logger.warning("framework_detection_error", extra={"error": str(exc)})
            return "unknown", "", [], "ERROR"

    # -----------------------------------------------------------------------
    # 2. Command & Path Validation
    # -----------------------------------------------------------------------

    def validate_test_request(
        self,
        workspace_root: Path,
        command: str,
        arguments: Sequence[str],
        test_path: str | None = None,
    ) -> None:
        """Validate test command, arguments, and targeted path against security policies.

        Raises:
            WorkspacePolicyViolationError: If unauthorized command, tokens, or install actions detected.
            WorkspacePathEscapeError: If targeted test_path attempts traversal outside workspace.
        """
        raw_cmd = (command or "").strip()
        if not raw_cmd:
            raise WorkspacePolicyViolationError("Test runner executable cannot be empty.")

        # Check for disallowed shell tokens or null bytes
        for token in DISALLOWED_COMMAND_TOKENS:
            if token in raw_cmd:
                raise WorkspacePolicyViolationError(
                    f"Test command contains forbidden shell operator or token: '{token}'"
                )

        # Allowlist validation
        base_exec = Path(raw_cmd).stem.lower()
        if base_exec not in ALLOWED_TEST_RUNNERS and raw_cmd.lower() not in ALLOWED_TEST_RUNNERS:
            raise WorkspacePolicyViolationError(
                f"Command '{raw_cmd}' is not an authorized test runner executable. "
                f"Permitted: {sorted(ALLOWED_TEST_RUNNERS)}"
            )

        # Disallow dependency installation commands (Docs/week3.md §6 F35)
        forbidden_subcommands = ("install", "add", "remove", "update", "upgrade", "uninstall")
        norm_args = [str(a).lower() for a in arguments]
        if base_exec in ("npm", "yarn", "pnpm") and any(sub in norm_args for sub in forbidden_subcommands):
            raise WorkspacePolicyViolationError(
                "Arbitrary dependency or package installation inside test runner is strictly prohibited."
            )
        if base_exec in ("python", "python3") and any("pip" in a for a in norm_args):
            raise WorkspacePolicyViolationError(
                "Arbitrary pip installation inside test runner is strictly prohibited."
            )

        # Check argument strings for disallowed shell tokens
        for arg in arguments:
            arg_str = str(arg)
            if "\x00" in arg_str:
                raise WorkspacePolicyViolationError("Argument contains null byte.")
            for token in DISALLOWED_COMMAND_TOKENS:
                if token in arg_str:
                    raise WorkspacePolicyViolationError(
                        f"Argument '{arg_str}' contains forbidden shell operator or token: '{token}'"
                    )

        # Validate target test_path containment
        if test_path:
            WorkspacePathGuard.resolve_within_workspace(workspace_root, test_path)

    # -----------------------------------------------------------------------
    # 3. Output Parsing & Statistics Extraction
    # -----------------------------------------------------------------------

    def parse_test_output(
        self,
        framework: str,
        stdout: str,
        stderr: str,
        exit_code: int,
    ) -> tuple[int, int, int, int, int, list[str], list[str]]:
        """Parse test logs to extract counts and failing test cases.

        Returns:
            (passed_count, failed_count, skipped_count, error_count, total_count, failed_names, details)
        """
        passed = 0
        failed = 0
        skipped = 0
        errors = 0
        total = 0
        failed_names: list[str] = []
        details: list[str] = []

        combined = f"{stdout}\n{stderr}"

        if framework == "pytest":
            # Match pytest summary line tokens regardless of order (e.g. "1 failed, 3 passed in 0.42s" or "5 passed in 0.35s")
            for line in combined.splitlines():
                line_str = line.strip()
                if line_str.startswith("=") and line_str.endswith("=") and any(k in line_str for k in ("passed", "failed", "skipped", "error")):
                    passed_m = re.search(r"(\d+)\s+passed", line_str, re.IGNORECASE)
                    if passed_m:
                        passed = int(passed_m.group(1))
                    failed_m = re.search(r"(\d+)\s+failed", line_str, re.IGNORECASE)
                    if failed_m:
                        failed = int(failed_m.group(1))
                    skipped_m = re.search(r"(\d+)\s+skipped", line_str, re.IGNORECASE)
                    if skipped_m:
                        skipped = int(skipped_m.group(1))
                    errors_m = re.search(r"(\d+)\s+error", line_str, re.IGNORECASE)
                    if errors_m:
                        errors = int(errors_m.group(1))
                    total = passed + failed + skipped + errors
                    break

            if total == 0:
                passed_m = re.search(r"(\d+)\s+passed", combined, re.IGNORECASE)
                if passed_m:
                    passed = int(passed_m.group(1))
                failed_m = re.search(r"(\d+)\s+failed", combined, re.IGNORECASE)
                if failed_m:
                    failed = int(failed_m.group(1))
                skipped_m = re.search(r"(\d+)\s+skipped", combined, re.IGNORECASE)
                if skipped_m:
                    skipped = int(skipped_m.group(1))
                errors_m = re.search(r"(\d+)\s+error", combined, re.IGNORECASE)
                if errors_m:
                    errors = int(errors_m.group(1))
                total = passed + failed + skipped + errors

            # Find all failing test items
            for item in _PYTEST_FAILED_ITEM_RE.finditer(combined):
                name = item.group(1).strip()
                if name and name not in failed_names:
                    failed_names.append(name)

            # If pytest exit code == 1 but regex missed counts
            if exit_code == 1 and failed == 0 and errors == 0:
                failed = len(failed_names) if failed_names else 1
                total = max(total, failed + passed)

        elif framework == "jest":
            match = _JEST_TESTS_SUMMARY_RE.search(combined)
            if match:
                failed = int(match.group("failed") or 0)
                passed = int(match.group("passed") or 0)
                skipped = int(match.group("skipped") or 0)
                total = int(match.group("total") or (failed + passed + skipped))

            for item in _JEST_FAILED_ITEM_RE.finditer(combined):
                name = item.group(1).strip()
                if name and name not in failed_names:
                    failed_names.append(name)

            if exit_code != 0 and failed == 0:
                failed = len(failed_names) if failed_names else 1
                total = max(total, failed + passed)

        elif framework == "unittest":
            ran_match = _UNITTEST_RAN_RE.search(combined)
            if ran_match:
                total = int(ran_match.group("total") or 0)

            fail_match = _UNITTEST_FAILED_RE.search(combined)
            if fail_match:
                failed = int(fail_match.group("failures") or 0)
                errors = int(fail_match.group("errors") or 0)
                passed = max(0, total - failed - errors)
            else:
                ok_match = _UNITTEST_OK_RE.search(combined)
                if ok_match:
                    skipped = int(ok_match.group("skipped") or 0)
                    passed = max(0, total - skipped)

        else:
            # Generic fallback based on exit code
            if exit_code == 0:
                passed = 1
                total = 1
            else:
                failed = 1
                total = 1

        # Extract up to 5 informative failure snippet lines
        for line in combined.splitlines():
            line_str = line.strip()
            if any(term in line_str for term in ("AssertionError:", "assert ", "FAILED ", "Error:", "FAIL ")):
                if len(details) < 5 and line_str not in details:
                    details.append(line_str)

        return passed, failed, skipped, errors, total, failed_names, details

    # -----------------------------------------------------------------------
    # 4. Failure Classification (F35, Docs/week3.md §6 & §8 Day 4)
    # -----------------------------------------------------------------------

    def classify_failure(
        self,
        exit_code: int,
        timed_out: bool,
        failed_count: int,
        error_count: int,
        stdout: str,
        stderr: str,
        framework_status: str,
    ) -> tuple[TestOutcomeStatus, TestFailureClassification, bool]:
        """Classify test outcome into status, failure category, and repair eligibility.

        Returns:
            (TestOutcomeStatus, TestFailureClassification, is_repair_eligible)
        """
        if timed_out:
            return TestOutcomeStatus.TIMEOUT, TestFailureClassification.TIMEOUT, False

        if framework_status == "UNSUPPORTED_FRAMEWORK":
            return TestOutcomeStatus.UNSUPPORTED_FRAMEWORK, TestFailureClassification.INFRASTRUCTURE_ERROR, False

        if framework_status == "AMBIGUOUS":
            return TestOutcomeStatus.AMBIGUOUS, TestFailureClassification.INFRASTRUCTURE_ERROR, False

        if framework_status == "NO_CONFIG_FOUND":
            return TestOutcomeStatus.NO_TESTS_FOUND, TestFailureClassification.INFRASTRUCTURE_ERROR, False

        if exit_code == 0:
            return TestOutcomeStatus.PASSED, TestFailureClassification.NONE, False

        combined = f"{stdout}\n{stderr}".lower()

        # Check for infrastructure crashes vs assertion failures
        # SyntaxError in test configuration or unhandled crash outside test cases
        infra_indicators = (
            "command not found",
            "is not recognized as an internal or external command",
            "no such file or directory",
            "permission denied",
            "cannot find module",
            "modulenotfounderror: no module named",
            "importbreak",
        )
        if any(ind in combined for ind in infra_indicators):
            return TestOutcomeStatus.ERROR, TestFailureClassification.INFRASTRUCTURE_ERROR, False

        # If tests ran and assertions or test cases failed -> Eligible for bounded repair!
        if failed_count > 0 or "assertionerror" in combined or "failed" in combined or exit_code == 1:
            return TestOutcomeStatus.FAILED, TestFailureClassification.TEST_FAILURE, True

        # Pytest exit code 5 means no tests were collected
        if exit_code == 5 or "no tests ran" in combined:
            return TestOutcomeStatus.NO_TESTS_FOUND, TestFailureClassification.INFRASTRUCTURE_ERROR, False

        # General non-zero exit fallback
        return TestOutcomeStatus.ERROR, TestFailureClassification.INFRASTRUCTURE_ERROR, False

    # -----------------------------------------------------------------------
    # 5. Execute Tests Inside Workspace Sandbox
    # -----------------------------------------------------------------------

    def run_tests(
        self,
        workspace_root: Path,
        request: WorkspaceTestExecutionRequest,
        workspace_id: str | None = None,
        workspace_revision: str | None = None,
    ) -> WorkspaceTestExecutionResult:
        """Safely execute tests inside the task workspace and return structured results."""
        start_time = time.perf_counter()

        if not workspace_root.exists() or not workspace_root.is_dir():
            raise WorkspaceTestExecutionError(
                f"Workspace root directory does not exist: {workspace_root}"
            )

        # 1. Detect Framework & Test Command
        framework, cmd, base_args, fw_status = self.detect_test_configuration(
            workspace_root=workspace_root,
            explicit_framework=request.framework,
        )

        if fw_status in ("UNSUPPORTED_FRAMEWORK", "AMBIGUOUS", "NO_CONFIG_FOUND"):
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            status_enum = (
                TestOutcomeStatus.UNSUPPORTED_FRAMEWORK
                if fw_status == "UNSUPPORTED_FRAMEWORK"
                else (TestOutcomeStatus.AMBIGUOUS if fw_status == "AMBIGUOUS" else TestOutcomeStatus.NO_TESTS_FOUND)
            )
            return WorkspaceTestExecutionResult(
                task_id=request.task_id,
                workspace_id=workspace_id,
                success=False,
                status=status_enum,
                classification=TestFailureClassification.INFRASTRUCTURE_ERROR,
                is_repair_eligible=False,
                framework=framework,
                command=cmd or "none",
                exit_code=-1,
                duration_ms=duration_ms,
                error=f"Test framework status: {fw_status}. Cannot run tests.",
                workspace_revision=workspace_revision,
            )

        # 2. Assemble Arguments
        all_args = list(base_args)
        if request.test_path:
            all_args.append(request.test_path)
        if request.arguments:
            all_args.extend(request.arguments)

        # 3. Security & Policy Validation
        try:
            self.validate_test_request(
                workspace_root=workspace_root,
                command=cmd,
                arguments=all_args,
                test_path=request.test_path,
            )
        except (WorkspacePolicyViolationError, WorkspacePathEscapeError) as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning("test_execution_security_violation", extra={"error": str(exc)})
            return WorkspaceTestExecutionResult(
                task_id=request.task_id,
                workspace_id=workspace_id,
                success=False,
                status=TestOutcomeStatus.ERROR,
                classification=TestFailureClassification.SECURITY_VIOLATION,
                is_repair_eligible=False,
                framework=framework,
                command=cmd,
                arguments=all_args,
                exit_code=-1,
                duration_ms=duration_ms,
                error=str(exc),
                workspace_revision=workspace_revision,
            )

        # 4. Execute Subprocess via CommandRunner
        timeout = min(
            request.timeout_seconds or self._default_timeout_seconds,
            MAX_TIMEOUT_SECONDS,
        )

        cmd_result = self._command_runner.run_command(
            workspace_root=workspace_root,
            command=cmd,
            arguments=all_args,
            timeout_seconds=timeout,
            custom_env=request.environment,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # 5. Redact secrets and enforce output truncation limits
        raw_stdout = cmd_result.stdout or ""
        raw_stderr = cmd_result.stderr or ""
        clean_stdout = redact(raw_stdout)
        clean_stderr = redact(raw_stderr)

        if len(clean_stdout.encode("utf-8")) > self._max_output_bytes:
            clean_stdout = clean_stdout[: self._max_output_bytes] + "\n... [TRUNCATED: output exceeded size limit]"

        if len(clean_stderr.encode("utf-8")) > self._max_output_bytes:
            clean_stderr = clean_stderr[: self._max_output_bytes] + "\n... [TRUNCATED: error output exceeded size limit]"

        # 6. Parse Output
        passed, failed, skipped, errors, total, failed_names, details = self.parse_test_output(
            framework=framework,
            stdout=clean_stdout,
            stderr=clean_stderr,
            exit_code=cmd_result.exit_code,
        )

        # 7. Classify Failure & Determine Repair Eligibility
        outcome_status, classification, is_repair_eligible = self.classify_failure(
            exit_code=cmd_result.exit_code,
            timed_out=cmd_result.timed_out,
            failed_count=failed,
            error_count=errors,
            stdout=clean_stdout,
            stderr=clean_stderr,
            framework_status=fw_status,
        )

        # Check if budget is already exhausted
        attempts_used = len(self._repair_attempts.get(request.task_id, []))
        if attempts_used >= self._max_repair_attempts:
            is_repair_eligible = False

        return WorkspaceTestExecutionResult(
            task_id=request.task_id,
            workspace_id=workspace_id,
            success=(outcome_status == TestOutcomeStatus.PASSED),
            status=outcome_status,
            classification=classification,
            is_repair_eligible=is_repair_eligible,
            framework=framework,
            command=cmd,
            arguments=all_args,
            exit_code=cmd_result.exit_code,
            duration_ms=duration_ms,
            passed_count=passed,
            failed_count=failed,
            skipped_count=skipped,
            error_count=errors,
            total_count=total,
            stdout=clean_stdout,
            stderr=clean_stderr,
            failed_test_names=failed_names,
            failure_details=details,
            timed_out=cmd_result.timed_out,
            error=cmd_result.error,
            workspace_revision=workspace_revision,
        )

    # -----------------------------------------------------------------------
    # 6. Bounded Auto-Repair Budget Enforcement (ADR-010, Docs/week3.md §6 F35)
    # -----------------------------------------------------------------------

    def get_repair_budget_status(self, task_id: str) -> WorkspaceRepairBudgetStatus:
        """Return the current repair attempt budget status for a task."""
        records = self._repair_attempts.get(task_id, [])
        used = len(records)
        is_exhausted = used >= self._max_repair_attempts
        last_at = records[-1].timestamp if records else None

        return WorkspaceRepairBudgetStatus(
            task_id=task_id,
            repair_attempts_used=used,
            repair_attempts_max=self._max_repair_attempts,
            is_budget_exhausted=is_exhausted,
            is_eligible_for_repair=not is_exhausted,
            last_attempt_at=last_at,
        )

    def can_attempt_repair(self, task_id: str) -> bool:
        """Return True if the task has remaining repair budget."""
        used = len(self._repair_attempts.get(task_id, []))
        return used < self._max_repair_attempts

    def record_repair_attempt(
        self,
        task_id: str,
        patch_summary: str,
        patch_content: str | None = None,
        workspace_revision: str | None = None,
        test_status_before: TestOutcomeStatus | None = None,
        test_status_after: TestOutcomeStatus | None = None,
        success: bool = False,
    ) -> RepairAttemptRecord:
        """Record a repair attempt, checking the 3-attempt ceiling and rejecting duplicate failed patches.

        Raises:
            WorkspaceRepairBudgetExhaustedError: If attempt budget (3) is exceeded.
            WorkspaceDuplicateRepairPatchError: If identical failed patch is repeatedly submitted.
        """
        records = self._repair_attempts.setdefault(task_id, [])
        used = len(records)

        # Enforce hard ceiling of 3 attempts per ADR-010
        if used >= self._max_repair_attempts:
            raise WorkspaceRepairBudgetExhaustedError(
                f"Task '{task_id}' has exhausted its maximum of {self._max_repair_attempts} "
                f"repair attempts. Execution must stop for human review."
            )

        # Compute patch signature hash to prevent infinite loops
        patch_data = patch_content if patch_content is not None else patch_summary
        patch_hash = hashlib.sha256(patch_data.encode("utf-8")).hexdigest()

        applied_hashes = self._applied_patch_hashes.setdefault(task_id, set())
        if patch_hash in applied_hashes:
            raise WorkspaceDuplicateRepairPatchError(
                f"Identical repair patch already attempted for task '{task_id}'. "
                f"Repeated identical patches are rejected to prevent infinite repair loops."
            )

        applied_hashes.add(patch_hash)
        attempt_number = used + 1

        record = RepairAttemptRecord(
            attempt_number=attempt_number,
            task_id=task_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            patch_summary=patch_summary,
            patch_hash=patch_hash,
            workspace_revision=workspace_revision,
            test_status_before=test_status_before,
            test_status_after=test_status_after,
            success=success,
        )
        records.append(record)

        logger.info(
            "repair_attempt_recorded",
            extra={
                "task_id": task_id,
                "attempt": attempt_number,
                "max": self._max_repair_attempts,
                "success": success,
            },
        )
        return record

    def get_repair_history(self, task_id: str) -> list[RepairAttemptRecord]:
        """Return the immutable list of repair attempt records for a task."""
        return list(self._repair_attempts.get(task_id, []))
