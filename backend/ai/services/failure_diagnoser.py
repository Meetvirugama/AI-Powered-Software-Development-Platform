"""backend/ai/services/failure_diagnoser.py

Traceback Failure Diagnosis Engine for Autonomous Self-Repair.
Part of Phase 4 (Diff-Based Testing, Diagnosis & Bounded Self-Repair).

Parses pytest and vitest test execution failure traces, identifying:
- Root cause application vs test frames
- Failing assertion statements and error categories
- Suggested repair targets and code locations
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FailureFrame:
    """Individual frame from a diagnosed execution stack trace."""

    file_path: str
    line_number: int
    function_name: str
    code_line: str = ""
    is_test_frame: bool = False


@dataclass
class FailureDiagnosis:
    """Structured diagnosis of a test execution failure."""

    error_type: str
    error_message: str
    failed_test_name: str | None = None
    failed_test_file: str | None = None
    root_cause_file: str | None = None
    root_cause_line: int | None = None
    failing_statement: str | None = None
    frames: list[FailureFrame] = field(default_factory=list)
    raw_snippet: str = ""
    suggested_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "error_message": self.error_message,
            "failed_test_name": self.failed_test_name,
            "failed_test_file": self.failed_test_file,
            "root_cause_file": self.root_cause_file,
            "root_cause_line": self.root_cause_line,
            "failing_statement": self.failing_statement,
            "frames": [
                {
                    "file_path": f.file_path,
                    "line_number": f.line_number,
                    "function_name": f.function_name,
                    "code_line": f.code_line,
                    "is_test_frame": f.is_test_frame,
                }
                for f in self.frames
            ],
            "raw_snippet": self.raw_snippet,
            "suggested_action": self.suggested_action,
        }


class FailureDiagnoser:
    """Diagnostic engine extracting actionable root causes from automated test failures."""

    # Pytest failure patterns
    PYTEST_FAIL_HEADER = re.compile(r"^_{3,}\s*(.*?)\s*_{3,}$", re.MULTILINE)
    PYTEST_ERROR_LINE = re.compile(r"^E\s+([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Exit|Interrupt|Failure)?):\s*(.*)$", re.MULTILINE)
    PYTEST_ASSERT_LINE = re.compile(r"^>\s+(.*)$", re.MULTILINE)
    PYTEST_LOCATION_LINE = re.compile(r"^([a-zA-Z0-9_\-/\\]+\.py):(\d+):\s*(?:in\s+(\w+))?", re.MULTILINE)

    # Vitest failure patterns
    VITEST_FAIL_HEADER = re.compile(r"FAIL\s+([^\s]+\.(?:test|spec)\.[tj]sx?)", re.MULTILINE)
    VITEST_ERROR_LINE = re.compile(r"(AssertionError|Error|TypeError|ReferenceError):\s*(.*)$", re.MULTILINE)
    VITEST_FRAME_LINE = re.compile(r"at\s+(?:.*?\s+\()?(.*?):(\d+):(\d+)\)?", re.MULTILINE)

    @classmethod
    def is_test_file(cls, path: str) -> bool:
        """Evaluate whether a path references a test file."""
        norm = path.replace("\\", "/").lower()
        return (
            "/tests/" in norm
            or norm.startswith("tests/")
            or "/test/" in norm
            or norm.startswith("test/")
            or "test_" in norm
            or norm.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", "_test.py"))
        )

    def diagnose_failure(
        self,
        raw_output: str,
        framework: str = "pytest",
    ) -> list[FailureDiagnosis]:
        """Parse raw test runner stdout/stderr and return structured failure diagnoses."""
        if not raw_output or not raw_output.strip():
            return []

        if framework.lower() == "vitest" or "vitest" in raw_output.lower():
            return self._diagnose_vitest(raw_output)

        return self._diagnose_pytest(raw_output)

    def _diagnose_pytest(self, output: str) -> list[FailureDiagnosis]:
        diagnoses: list[FailureDiagnosis] = []

        # Split output into failure sections if multiple tests failed
        # Sections usually start with "_______ test_name _______"
        sections = self.PYTEST_FAIL_HEADER.split(output)

        if len(sections) > 1:
            for i in range(1, len(sections), 2):
                test_name = sections[i].strip()
                sec_content = sections[i + 1] if (i + 1) < len(sections) else ""
                diag = self._parse_single_pytest_block(test_name, sec_content)
                if diag:
                    diagnoses.append(diag)
        else:
            # Fallback parse whole output as a single failure block
            diag = self._parse_single_pytest_block(None, output)
            if diag:
                diagnoses.append(diag)

        return diagnoses

    def _parse_single_pytest_block(
        self,
        test_name: str | None,
        block: str,
    ) -> FailureDiagnosis | None:
        err_type = "AssertionError"
        err_msg = ""
        failing_stmt = None
        frames: list[FailureFrame] = []

        err_match = self.PYTEST_ERROR_LINE.search(block)
        if err_match:
            err_type = err_match.group(1).strip()
            err_msg = err_match.group(2).strip()

        assert_match = self.PYTEST_ASSERT_LINE.search(block)
        if assert_match:
            failing_stmt = assert_match.group(1).strip()

        loc_matches = self.PYTEST_LOCATION_LINE.findall(block)
        for loc in loc_matches:
            f_path, line_str, fn = loc
            line_no = int(line_str)
            is_test = self.is_test_file(f_path)
            frames.append(
                FailureFrame(
                    file_path=f_path,
                    line_number=line_no,
                    function_name=fn or "",
                    is_test_frame=is_test,
                )
            )

        if not err_msg and not loc_matches and not test_name:
            return None

        # Determine root cause frame:
        # Prefer application frame (non-test frame) if present in the traceback;
        # otherwise use the innermost test frame.
        app_frames = [f for f in frames if not f.is_test_frame]
        test_frames = [f for f in frames if f.is_test_frame]

        root_cause_file = None
        root_cause_line = None

        if app_frames:
            # Last app frame is where the actual code failed
            target_frame = app_frames[-1]
            root_cause_file = target_frame.file_path
            root_cause_line = target_frame.line_number
        elif test_frames:
            target_frame = test_frames[-1]
            root_cause_file = target_frame.file_path
            root_cause_line = target_frame.line_number

        test_file = test_frames[0].file_path if test_frames else None

        suggested = ""
        if root_cause_file and not self.is_test_file(root_cause_file):
            suggested = f"Inspect implementation logic in '{root_cause_file}' at line {root_cause_line}."
        elif test_file:
            suggested = f"Verify assertions and expectations in '{test_file}'."

        return FailureDiagnosis(
            error_type=err_type,
            error_message=err_msg or "Test failed without explicit error message",
            failed_test_name=test_name,
            failed_test_file=test_file,
            root_cause_file=root_cause_file,
            root_cause_line=root_cause_line,
            failing_statement=failing_stmt,
            frames=frames,
            raw_snippet=block[:1000],
            suggested_action=suggested,
        )

    def _diagnose_vitest(self, output: str) -> list[FailureDiagnosis]:
        diagnoses: list[FailureDiagnosis] = []

        err_type = "AssertionError"
        err_msg = ""
        err_match = self.VITEST_ERROR_LINE.search(output)
        if err_match:
            err_type = err_match.group(1).strip()
            err_msg = err_match.group(2).strip()

        frames: list[FailureFrame] = []
        loc_matches = self.VITEST_FRAME_LINE.findall(output)
        for loc in loc_matches:
            f_path, line_str, _ = loc
            line_no = int(line_str)
            is_test = self.is_test_file(f_path)
            frames.append(
                FailureFrame(
                    file_path=f_path,
                    line_number=line_no,
                    function_name="",
                    is_test_frame=is_test,
                )
            )

        test_header_match = self.VITEST_FAIL_HEADER.search(output)
        test_file = test_header_match.group(1).strip() if test_header_match else None

        app_frames = [f for f in frames if not f.is_test_frame]
        test_frames = [f for f in frames if f.is_test_frame]

        root_cause_file = app_frames[-1].file_path if app_frames else (test_frames[-1].file_path if test_frames else test_file)
        root_cause_line = app_frames[-1].line_number if app_frames else (test_frames[-1].line_number if test_frames else None)

        diagnoses.append(
            FailureDiagnosis(
                error_type=err_type,
                error_message=err_msg or "Vitest execution failed.",
                failed_test_file=test_file,
                root_cause_file=root_cause_file,
                root_cause_line=root_cause_line,
                frames=frames,
                raw_snippet=output[:1000],
                suggested_action=f"Review component code at '{root_cause_file}'" if root_cause_file else "Check frontend test failures.",
            )
        )

        return diagnoses
