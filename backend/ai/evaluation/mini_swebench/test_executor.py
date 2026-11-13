"""Isolated Test Executor for Mini SWE-bench tasks (Phase 4 & 5, task3.md §9.7)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Tuple

from ai.evaluation.mini_swebench.task_loader import BenchmarkTask

logger = logging.getLogger(__name__)


class BenchmarkTestExecutor:
    """Executes reproduction and regression tests for a benchmark task in an isolated temp workspace."""

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds

    def execute_test_code(self, test_code: str, target_dir: Path) -> Tuple[bool, str]:
        """Run a test snippet using python in an isolated copy of target_dir without polluting source tree."""
        with tempfile.TemporaryDirectory(prefix="swebench_eval_") as tmp_dir:
            work_dir = Path(tmp_dir)
            if target_dir.exists():
                for item in target_dir.iterdir():
                    if item.name == "__pycache__":
                        continue
                    dest = work_dir / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest)
                    else:
                        shutil.copy2(item, dest)

            test_file_path = work_dir / "_eval_runner_test.py"
            test_file_path.write_text(test_code, encoding="utf-8")

            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONPATH"] = f"{work_dir}{os.pathsep}{target_dir}"

            try:
                cmd = [sys.executable, "-B", str(test_file_path)]
                proc = subprocess.run(
                    cmd,
                    cwd=str(work_dir),
                    env=env,
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

    def evaluate_task_tests(
        self,
        task: BenchmarkTask,
        workspace_dir: Path,
    ) -> Tuple[bool, bool, str]:
        """Run reproduction and regression tests against the task workspace."""
        repro_passed, repro_log = self.execute_test_code(task.reproduction_code, workspace_dir)
        reg_passed, reg_log = self.execute_test_code(task.regression_code, workspace_dir)

        log = f"Reproduction test ({'PASS' if repro_passed else 'FAIL'}):\n{repro_log}\n"
        log += f"Regression test ({'PASS' if reg_passed else 'FAIL'}):\n{reg_log}\n"
        return repro_passed, reg_passed, log


__all__ = ["BenchmarkTestExecutor"]
