"""Resource Monitor & Quota Enforcement for Isolated Workspaces.

Owner: Prit Zania — Week 3 Day 1 Deliverable (Docs/week3.md §6 F33, ADR-007)
"""

from __future__ import annotations

import os
from pathlib import Path

from app.schemas.workspace import WorkspaceResourceLimits
from sandbox.exceptions import WorkspaceLimitExceededError


class WorkspaceResourceMonitor:
    """Monitors disk usage, file sizes, and operation quotas within a task workspace."""

    def __init__(self, workspace_root: Path, limits: WorkspaceResourceLimits | None = None) -> None:
        self.workspace_root = workspace_root
        self.limits = limits or WorkspaceResourceLimits()
        self._modified_files: set[str] = set()

    def check_file_size(self, size_bytes: int, file_path: str = "") -> None:
        """Validate that file size is within acceptable limits."""
        if size_bytes > self.limits.max_file_size_bytes:
            raise WorkspaceLimitExceededError(
                f"File '{file_path}' size ({size_bytes} bytes) exceeds maximum limit "
                f"of {self.limits.max_file_size_bytes} bytes."
            )

    def calculate_disk_usage(self) -> int:
        """Calculate total disk usage in bytes across all files in workspace."""
        if not self.workspace_root.exists() or not self.workspace_root.is_dir():
            return 0

        total_bytes = 0
        for root, _, files in os.walk(self.workspace_root):
            for filename in files:
                filepath = Path(root) / filename
                try:
                    if not filepath.is_symlink():
                        total_bytes += filepath.stat().st_size
                except OSError:
                    continue
        return total_bytes

    def check_disk_quota(self, anticipated_additional_bytes: int = 0) -> None:
        """Verify that current disk usage plus anticipated writes does not exceed limit."""
        current_usage = self.calculate_disk_usage()
        projected = current_usage + max(0, anticipated_additional_bytes)
        if projected > self.limits.max_disk_bytes:
            raise WorkspaceLimitExceededError(
                f"Projected workspace disk usage ({projected} bytes) exceeds maximum quota "
                f"of {self.limits.max_disk_bytes} bytes."
            )

    def record_file_modification(self, rel_path: str) -> None:
        """Track modified files and verify against max_files_modified budget."""
        self._modified_files.add(rel_path)
        if len(self._modified_files) > self.limits.max_files_modified:
            raise WorkspaceLimitExceededError(
                f"Number of modified files ({len(self._modified_files)}) exceeds ceiling "
                f"of {self.limits.max_files_modified} files per task."
            )

    @property
    def modified_files_count(self) -> int:
        return len(self._modified_files)
