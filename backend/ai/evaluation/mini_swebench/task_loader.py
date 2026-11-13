"""Task loader and manifest manager for Mini SWE-bench (Phase 4 & 5, task3.md §9.2)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from ai.evaluation.mini_swebench.models import BenchmarkTaskMetadata

logger = logging.getLogger(__name__)


class BenchmarkTask:
    """A loaded benchmark task with its metadata, issue text, and test code."""

    def __init__(
        self,
        metadata: BenchmarkTaskMetadata,
        task_dir: Path,
        issue_text: str,
        reproduction_code: str,
        regression_code: str,
    ) -> None:
        self.metadata = metadata
        self.task_dir = task_dir
        self.issue_text = issue_text
        self.reproduction_code = reproduction_code
        self.regression_code = regression_code

    @property
    def task_id(self) -> str:
        return self.metadata.task_id


class MiniSWEBenchTaskLoader:
    """Discovers, loads, and validates Mini SWE-bench tasks from disk."""

    def __init__(self, dataset_dir: Optional[Path] = None) -> None:
        if dataset_dir is not None:
            self.dataset_dir = dataset_dir
        else:
            self.dataset_dir = Path(__file__).resolve().parent / "dataset"

        self.tasks_dir = self.dataset_dir / "tasks"
        self._tasks: Dict[str, BenchmarkTask] = {}
        self.load_all()

    @property
    def tasks(self) -> List[BenchmarkTask]:
        return list(self._tasks.values())

    def load_all(self) -> int:
        """Scan tasks directory and load all task directories."""
        self._tasks.clear()
        if not self.tasks_dir.exists():
            logger.warning("Mini SWE-bench tasks directory not found: %s", self.tasks_dir)
            return 0

        for tdir in sorted(self.tasks_dir.iterdir()):
            if not tdir.is_dir():
                continue

            meta_file = tdir / "metadata.json"
            if not meta_file.exists():
                continue

            try:
                meta = BenchmarkTaskMetadata.model_validate_json(meta_file.read_text(encoding="utf-8"))
                issue_file = tdir / "issue.md"
                issue_text = issue_file.read_text(encoding="utf-8") if issue_file.exists() else meta.issue_description

                repro_file = tdir / meta.reproduction_test
                repro_code = repro_file.read_text(encoding="utf-8") if repro_file.exists() else ""

                reg_file = tdir / meta.regression_test
                reg_code = reg_file.read_text(encoding="utf-8") if reg_file.exists() else ""

                task = BenchmarkTask(
                    metadata=meta,
                    task_dir=tdir,
                    issue_text=issue_text,
                    reproduction_code=repro_code,
                    regression_code=reg_code,
                )
                self._tasks[task.task_id] = task
            except Exception as exc:
                logger.error("Failed to load task %s: %s", tdir.name, exc)

        return len(self._tasks)

    def get_task(self, task_id: str) -> Optional[BenchmarkTask]:
        return self._tasks.get(task_id)


__all__ = ["BenchmarkTask", "MiniSWEBenchTaskLoader"]
