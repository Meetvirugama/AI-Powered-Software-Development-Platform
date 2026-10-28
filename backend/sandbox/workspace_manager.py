"""Isolated Workspace Manager Implementation.

Owner: Prit Zania — Week 3 Day 1 Deliverable (Docs/week3.md §6 F33, §8 Day 1)
Reference: Docs/week3.md §6 (F33 — Isolated Workspace and Repository Operations)

Key Capabilities:
1. Provisions disposable task workspaces under designated sandboxes (.workspaces/task-<id>).
2. Supports Git worktree isolation with automatic fallback to isolated directory trees.
3. Enforces full lifecycle state machine (NOT_CREATED -> CREATING -> READY -> IN_USE -> STOPPED/FAILED -> CLEANUP_PENDING -> CLEANED).
4. Provides guarded, sandboxed file operations (read, write, patch, delete, list).
5. Imforces resource quotas (file size caps, disk budgets, modified file counts).
6. Guarantees safe, idempotent cleanup without touching host repository or sibling tasks.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.core.config import PROJECT_ROOT
from app.core.secret_redaction import redact
from app.services.git_branch import format_agent_branch_name
from app.schemas.workspace import (
    WorkspaceCleanupResult,
    WorkspaceCreateRequest,
    WorkspaceCreateResult,
    WorkspaceFilePatchRequest,
    WorkspaceFilePatchResult,
    WorkspaceFileReadRequest,
    WorkspaceFileReadResult,
    WorkspaceFileWriteRequest,
    WorkspaceFileWriteResult,
    WorkspaceIsolationType,
    WorkspaceMetadata,
    WorkspaceResourceLimits,
    WorkspaceStatus,
    can_transition_workspace,
)
from sandbox.constants import DEFAULT_WORKSPACE_SUBDIR
from sandbox.exceptions import (
    WorkspaceCleanupError,
    WorkspaceCreationError,
    WorkspaceError,
    WorkspaceFileError,
    WorkspaceLimitExceededError,
    WorkspacePathEscapeError,
    WorkspaceStateError,
)
from sandbox.path_guard import WorkspacePathGuard
from sandbox.resource_monitor import WorkspaceResourceMonitor

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Manages isolated working environments and Git worktrees for tasks."""

    def __init__(self, base_workspaces_dir: str | Path | None = None) -> None:
        """Initialize the workspace manager.

        Args:
            base_workspaces_dir: Custom root for workspace sandboxes. Defaults to PROJECT_ROOT / .workspaces.
        """
        if base_workspaces_dir is not None:
            self._base_dir = Path(base_workspaces_dir).resolve()
        else:
            self._base_dir = (PROJECT_ROOT / DEFAULT_WORKSPACE_SUBDIR).resolve()

        self._workspaces: dict[str, WorkspaceMetadata] = {}
        self._monitors: dict[str, WorkspaceResourceMonitor] = {}

    @property
    def base_directory(self) -> Path:
        """Return the base directory housing all task workspaces."""
        return self._base_dir

    # -----------------------------------------------------------------------
    # Workspace Lifecycle Operations
    # -----------------------------------------------------------------------

    def create_workspace(self, request: WorkspaceCreateRequest) -> WorkspaceMetadata:
        """Create and initialize an isolated workspace for a task.

        Lifecycle: NOT_CREATED -> CREATING -> READY (or FAILED on error).
        """
        task_id = str(request.task_id).strip()
        start_time = time.perf_counter()

        # Idempotency / conflict check
        existing = self._workspaces.get(task_id)
        if existing and existing.status in (WorkspaceStatus.READY, WorkspaceStatus.IN_USE):
            return existing

        # Ensure base directory exists
        self._base_dir.mkdir(parents=True, exist_ok=True)
        WorkspacePathGuard.validate_workspace_root(self._base_dir)

        # Formulate safe workspace path
        raw_slug = task_id[5:] if task_id.lower().startswith("task-") else task_id
        cleaned_short = format_agent_branch_name(raw_slug).replace("agent/task-", "")
        safe_task_slug = f"task-{cleaned_short}"
        workspace_path = (self._base_dir / safe_task_slug).resolve()

        branch_name = request.branch_name or f"agent/{safe_task_slug}"
        limits = request.resource_limits or WorkspaceResourceLimits()


        metadata = WorkspaceMetadata(
            workspace_id=str(uuid4()),
            task_id=task_id,
            repository_id=str(request.repository_id),
            base_revision=request.base_revision,
            branch_name=branch_name,
            workspace_path=str(workspace_path),
            status=WorkspaceStatus.CREATING,
            isolation_type=request.isolation_type,
            resource_limits=limits,
        )
        self._workspaces[task_id] = metadata

        try:
            isolation_used = self._provision_workspace(
                workspace_path=workspace_path,
                repo_root=Path(request.repository_root) if request.repository_root else None,
                base_revision=request.base_revision,
                branch_name=branch_name,
                preferred_isolation=request.isolation_type,
            )
            metadata.isolation_type = isolation_used
            metadata.status = WorkspaceStatus.READY
            metadata.updated_at = datetime.now(timezone.utc).isoformat()
            self._monitors[task_id] = WorkspaceResourceMonitor(workspace_path, limits)

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.info(
                "workspace_created",
                extra={
                    "task_id": task_id,
                    "workspace_id": metadata.workspace_id,
                    "path": str(workspace_path),
                    "duration_ms": duration_ms,
                    "isolation": isolation_used,
                },
            )
            return metadata

        except Exception as exc:
            metadata.status = WorkspaceStatus.FAILED
            metadata.error_message = redact(str(exc))
            metadata.updated_at = datetime.now(timezone.utc).isoformat()
            # Clean up partial directory on failure
            self._safe_remove_dir(workspace_path)
            raise WorkspaceCreationError(f"Failed to create workspace for task '{task_id}': {exc}") from exc

    def _provision_workspace(
        self,
        workspace_path: Path,
        repo_root: Path | None,
        base_revision: str,
        branch_name: str,
        preferred_isolation: WorkspaceIsolationType,
    ) -> WorkspaceIsolationType:
        """Provision the filesystem tree using git worktree or directory copy."""
        # Clean existing path if needed
        self._safe_remove_dir(workspace_path)

        if preferred_isolation == "git_worktree" and repo_root and (repo_root / ".git").exists():
            try:
                # Try creating git worktree
                # git worktree add -B <branch_name> <workspace_path> <base_revision>
                cmd = [
                    "git",
                    "-C",
                    str(repo_root),
                    "worktree",
                    "add",
                    "-B",
                    branch_name,
                    str(workspace_path),
                    base_revision,
                ]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                if proc.returncode == 0 and workspace_path.exists():
                    return "git_worktree"
                logger.warning(
                    "git_worktree_failed_falling_back",
                    extra={"stderr": proc.stderr, "task_path": str(workspace_path)},
                )
            except Exception as e:
                logger.warning(
                    "git_worktree_exception_falling_back",
                    extra={"error": str(e)},
                )

        # Fallback to isolated directory copy if repo_root is provided, or create empty sandbox
        workspace_path.mkdir(parents=True, exist_ok=True)
        if repo_root and repo_root.exists():
            for item in repo_root.iterdir():
                if item.name in (".git", ".workspaces", "venv", "__pycache__", ".pytest_cache", "node_modules"):
                    continue
                dest = workspace_path / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, symlinks=False, ignore=shutil.ignore_patterns(".git*", "__pycache__"))
                elif item.is_file():
                    shutil.copy2(item, dest)
        return "directory_copy"

    def get_workspace(self, task_id: str) -> WorkspaceMetadata | None:
        """Retrieve workspace metadata by task ID."""
        return self._workspaces.get(task_id)

    def get_workspace_path(self, task_id: str) -> Path:
        """Resolve the verified workspace root Path for a task."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")
        if meta.status not in (WorkspaceStatus.READY, WorkspaceStatus.IN_USE):
            raise WorkspaceStateError(
                f"Workspace for task '{task_id}' is in state '{meta.status}', not available for operations."
            )
        path = Path(meta.workspace_path)
        if not path.exists():
            raise WorkspaceError(f"Workspace directory on disk missing for task '{task_id}': {path}")
        return path

    def transition_state(self, task_id: str, new_status: WorkspaceStatus) -> WorkspaceMetadata:
        """Transition a workspace to a new state enforcing the state machine."""
        meta = self.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'.")

        if not can_transition_workspace(meta.status, new_status):
            raise WorkspaceStateError(
                f"Cannot transition workspace '{task_id}' from '{meta.status}' to '{new_status}'."
            )

        meta.status = new_status
        meta.updated_at = datetime.now(timezone.utc).isoformat()
        return meta

    # -----------------------------------------------------------------------
    # Guarded Sandboxed File Operations
    # -----------------------------------------------------------------------

    def read_file(self, task_id: str, file_path: str) -> WorkspaceFileReadResult:
        """Safely read a file within the task's isolated workspace."""
        try:
            root = self.get_workspace_path(task_id)
            meta = self._workspaces[task_id]
            resolved = WorkspacePathGuard.resolve_within_workspace(root, file_path)

            if not resolved.exists() or not resolved.is_file():
                return WorkspaceFileReadResult(
                    success=False,
                    file_path=file_path,
                    error=f"File not found: '{file_path}'",
                )

            # Check file size limit
            stat = resolved.stat()
            monitor = self._monitors.get(task_id)
            if monitor:
                monitor.check_file_size(stat.st_size, file_path)

            content = resolved.read_text(encoding="utf-8", errors="replace")
            return WorkspaceFileReadResult(
                success=True,
                file_path=file_path,
                content=content,
                size_bytes=len(content.encode("utf-8")),
            )
        except WorkspaceError as exc:
            return WorkspaceFileReadResult(success=False, file_path=file_path, error=redact(str(exc)))
        except Exception as exc:
            return WorkspaceFileReadResult(success=False, file_path=file_path, error=f"Read error: {redact(str(exc))}")

    def write_file(
        self,
        task_id: str,
        file_path: str,
        content: str,
        create_parents: bool = True,
    ) -> WorkspaceFileWriteResult:
        """Safely write or overwrite a file within the task's isolated workspace."""
        try:
            root = self.get_workspace_path(task_id)
            meta = self._workspaces[task_id]
            resolved = WorkspacePathGuard.resolve_within_workspace(root, file_path)

            encoded = content.encode("utf-8")
            content_size = len(encoded)

            monitor = self._monitors.get(task_id)
            if monitor:
                monitor.check_file_size(content_size, file_path)
                monitor.check_disk_quota(content_size)
                monitor.record_file_modification(file_path)

            if create_parents:
                resolved.parent.mkdir(parents=True, exist_ok=True)

            created = not resolved.exists()

            # Atomic write via temporary file
            temp_path = resolved.with_name(f"{resolved.name}.tmp.{uuid4().hex[:8]}")
            temp_path.write_text(content, encoding="utf-8")
            temp_path.replace(resolved)

            return WorkspaceFileWriteResult(
                success=True,
                file_path=file_path,
                bytes_written=content_size,
                created=created,
            )
        except WorkspaceError as exc:
            return WorkspaceFileWriteResult(success=False, file_path=file_path, error=redact(str(exc)))
        except Exception as exc:
            return WorkspaceFileWriteResult(success=False, file_path=file_path, error=f"Write error: {redact(str(exc))}")

    def patch_file(
        self,
        task_id: str,
        file_path: str,
        target_content: str,
        replacement_content: str,
    ) -> WorkspaceFilePatchResult:
        """Safely apply a text patch to a file within the task workspace."""
        if not target_content:
            return WorkspaceFilePatchResult(
                success=False,
                file_path=file_path,
                error="Target content cannot be empty.",
            )

        read_res = self.read_file(task_id, file_path)
        if not read_res.success or read_res.content is None:
            return WorkspaceFilePatchResult(
                success=False,
                file_path=file_path,
                error=read_res.error or "Could not read target file for patching.",
            )

        current_content = read_res.content
        if target_content not in current_content:
            return WorkspaceFilePatchResult(
                success=False,
                file_path=file_path,
                error=f"Target content not found in '{file_path}'.",
            )

        count = current_content.count(target_content)
        new_content = current_content.replace(target_content, replacement_content)

        write_res = self.write_file(task_id, file_path, new_content, create_parents=False)
        if not write_res.success:
            return WorkspaceFilePatchResult(
                success=False,
                file_path=file_path,
                error=write_res.error or "Failed to write patched content.",
            )

        return WorkspaceFilePatchResult(
            success=True,
            file_path=file_path,
            occurrences_replaced=count,
        )

    def delete_file(self, task_id: str, file_path: str) -> bool:
        """Safely remove a file inside the isolated workspace."""
        root = self.get_workspace_path(task_id)
        resolved = WorkspacePathGuard.resolve_within_workspace(root, file_path)
        if resolved.exists() and resolved.is_file():
            resolved.unlink()
            return True
        return False

    def list_files(self, task_id: str, subpath: str = "") -> list[str]:
        """List repository-relative files within the workspace."""
        root = self.get_workspace_path(task_id)
        target_dir = root
        if subpath:
            target_dir = WorkspacePathGuard.resolve_within_workspace(root, subpath)

        if not target_dir.exists() or not target_dir.is_dir():
            return []

        files: list[str] = []
        for parent, dirnames, filenames in os.walk(target_dir):
            # Prune .git and caches
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", ".pytest_cache")]
            for f in filenames:
                full_path = Path(parent) / f
                rel = full_path.relative_to(root).as_posix()
                files.append(rel)
        files.sort()
        return files

    # -----------------------------------------------------------------------
    # Decommissioning & Cleanup
    # -----------------------------------------------------------------------

    def cleanup_workspace(self, task_id: str, force: bool = False) -> WorkspaceCleanupResult:
        """Safely decommission and remove a workspace directory.

        Lifecycle: (READY | IN_USE | STOPPED | FAILED) -> CLEANUP_PENDING -> CLEANED.
        Idempotent: Re-cleaning an already cleaned or absent workspace returns success.
        """
        start_time = time.perf_counter()
        meta = self.get_workspace(task_id)

        if not meta:
            # Idempotent success when workspace does not exist
            return WorkspaceCleanupResult(
                success=True,
                workspace_id=task_id,
                duration_ms=0.0,
            )

        if meta.status == WorkspaceStatus.CLEANED:
            return WorkspaceCleanupResult(
                success=True,
                workspace_id=meta.workspace_id,
                cleaned_path=meta.workspace_path,
                duration_ms=0.0,
            )

        workspace_path = Path(meta.workspace_path)
        worktree_pruned = False

        try:
            meta.status = WorkspaceStatus.CLEANUP_PENDING
            meta.updated_at = datetime.now(timezone.utc).isoformat()

            # Attempt Git worktree removal if applicable
            if meta.isolation_type == "git_worktree":
                try:
                    # git worktree remove --force <workspace_path>
                    proc = subprocess.run(
                        ["git", "worktree", "remove", "--force", str(workspace_path)],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=30,
                    )
                    if proc.returncode == 0:
                        worktree_pruned = True
                except Exception as e:
                    logger.warning("git_worktree_remove_failed", extra={"error": str(e)})

            # Safe physical directory removal
            self._safe_remove_dir(workspace_path)

            meta.status = WorkspaceStatus.CLEANED
            meta.cleaned_at = datetime.now(timezone.utc).isoformat()
            meta.updated_at = meta.cleaned_at
            self._monitors.pop(task_id, None)

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return WorkspaceCleanupResult(
                success=True,
                workspace_id=meta.workspace_id,
                cleaned_path=str(workspace_path),
                worktree_pruned=worktree_pruned,
                duration_ms=duration_ms,
            )

        except Exception as exc:
            meta.status = WorkspaceStatus.FAILED
            meta.error_message = redact(f"Cleanup failure: {exc}")
            raise WorkspaceCleanupError(f"Failed to clean workspace '{task_id}': {exc}") from exc

    def _safe_remove_dir(self, directory: Path) -> None:
        """Safely delete directory ensuring it is strictly under base_directory."""
        if not directory.exists():
            return

        # Critical guard: never delete the root base_dir or anything outside it
        resolved = directory.resolve()
        if resolved == self._base_dir or resolved == PROJECT_ROOT or not resolved.is_relative_to(self._base_dir):
            raise WorkspaceCleanupError(
                f"Refusing to delete unsafe or non-sandbox directory: {resolved}"
            )

        try:
            shutil.rmtree(resolved, ignore_errors=False)
        except Exception:
            # Retry with error handler on Windows if file was read-only
            def _remove_readonly(func: Any, path: str, _: Any) -> None:
                os.chmod(path, 0o777)
                func(path)

            shutil.rmtree(resolved, onerror=_remove_readonly)
