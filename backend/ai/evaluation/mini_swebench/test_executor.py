"""Isolated Test Executor for Mini SWE-bench tasks (Phase 4 & 5, task3.md §9.7)."""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Tuple

from ai.evaluation.mini_swebench.task_loader import BenchmarkTask

logger = logging.getLogger(__name__)


class BenchmarkTestExecutor:
    """Executes reproduction and regression tests for a benchmark task."""

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds

    def execute_test_code(self, test_code: str, target_dir: Path) -> Tuple[bool, str]:
        """Run a test snippet using python in target_dir."""
        with tempfile.NamedTemporaryFile("w", suffix=".py", dir=str(target_dir), delete=False) as tf:
            tf.write(test_code)
            test_file_path = tf.name

        try:
            cmd = [sys.executable, test_file_path]
            proc = subprocess.run(
                cmd,
                cwd=str(target_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            passed = proc.returncode == 0
            output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
            return passed, output
        except subprocess.TimeoutExpired:
            return False, f"Test execution timed out after {self.timeout_seconds}s"
        except Exception as exc:
            return False, f"Test execution error: {exc}"
        finally:
            try:
                Path(test_file_path).unlink(missing_ok=True)
            except OSError:
                pass

    def evaluate_task_tests(
        self,
        task: BenchmarkTask,
        workspace_dir: Path,
    ) -> Tuple[bool, bool, str]:
        """Run reproduction and regression tests against the task workspace.
        
        Returns:
            Tuple of (repro_passed, reg_passed, summary_log)
        """
        repro_passed, repro_log = self.execute_test_code(task.reproduction_code, workspace_dir)
        reg_passed, reg_log = self.execute_test_code(task.regression_code, workspace_dir)

        log = f"Reproduction test ({'PASS' if repro_passed else 'FAIL'}):\n{repro_log}\n"
        log += f"Regression test ({'PASS' if reg_passed else 'FAIL'}):\n{reg_log}\n"
        return repro_passed, reg_passed, log


__all__ = ["BenchmarkTestExecutor"]
