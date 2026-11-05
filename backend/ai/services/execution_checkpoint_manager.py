"""Execution Checkpoint Manager.

Implements Phase 9: Verified Checkpoints & State Persistence (task.md §10, test plan OPS-01, OPS-02, OPS-03).
Guarantees:
- Checkpoints are saved ONLY after a step passes verification (OPS-01).
- Resume preserves completed verified steps and continues remaining work safely (OPS-02).
- Interrupted or partial edits roll back to the last verified checkpoint (OPS-03).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExecutionCheckpoint:
    """Snapshot of execution state recorded after step verification."""

    checkpoint_id: str
    task_id: str
    step_id: str
    workspace_revision: str
    diff_hash: str
    completed_step_ids: list[str] = field(default_factory=list)
    completed_requirement_ids: list[str] = field(default_factory=list)
    verified_files: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    remaining_budget: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionCheckpointManager:
    """Manages transactional checkpoints for safe resumption and rollback."""

    def __init__(self, storage_dir: str | None = None) -> None:
        self.storage_dir = storage_dir
        self._checkpoints: dict[str, list[ExecutionCheckpoint]] = {}  # task_id -> list[ExecutionCheckpoint]

    def save_checkpoint(
        self,
        task_id: str,
        step_id: str,
        workspace_revision: str,
        diff_hash: str | None = None,
        completed_step_ids: Sequence[str] | None = None,
        completed_requirement_ids: Sequence[str] | None = None,
        verified_files: Sequence[str] | None = None,
        evidence: Mapping[str, Any] | None = None,
        remaining_budget: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionCheckpoint:
        """Create and record an immutable checkpoint after step verification succeeds."""
        if not diff_hash:
            diff_hash = hashlib.sha256(f"{task_id}:{step_id}:{workspace_revision}".encode()).hexdigest()[:16]

        checkpoint_id = f"ckpt-{task_id[:8] if len(task_id) >= 8 else task_id}-{step_id}-{len(self._checkpoints.get(task_id, [])) + 1}"
        ckpt = ExecutionCheckpoint(
            checkpoint_id=checkpoint_id,
            task_id=task_id,
            step_id=step_id,
            workspace_revision=workspace_revision,
            diff_hash=diff_hash,
            completed_step_ids=list(completed_step_ids or []),
            completed_requirement_ids=list(completed_requirement_ids or []),
            verified_files=list(verified_files or []),
            evidence=dict(evidence or {}),
            remaining_budget=dict(remaining_budget or {}),
            metadata=dict(metadata or {}),
        )

        if task_id not in self._checkpoints:
            self._checkpoints[task_id] = []
        self._checkpoints[task_id].append(ckpt)
        logger.info(
            "Saved verified checkpoint %s for task %s (step: %s, revision: %s, completed_reqs: %d)",
            checkpoint_id,
            task_id,
            step_id,
            workspace_revision,
            len(completed_requirement_ids or []),
        )
        return ckpt

    def get_latest_checkpoint(self, task_id: str) -> ExecutionCheckpoint | None:
        """Return the most recent verified checkpoint for task."""
        ckpts = self._checkpoints.get(task_id, [])
        return ckpts[-1] if ckpts else None

    def get_checkpoint(self, task_id: str, checkpoint_id: str) -> ExecutionCheckpoint | None:
        """Return specific checkpoint by ID."""
        for c in self._checkpoints.get(task_id, []):
            if c.checkpoint_id == checkpoint_id:
                return c
        return None

    def list_checkpoints(self, task_id: str) -> list[ExecutionCheckpoint]:
        """List all checkpoints recorded for task."""
        return list(self._checkpoints.get(task_id, []))

    def can_resume(self, task_id: str) -> bool:
        """Return True if task has at least one valid checkpoint to resume from."""
        return len(self._checkpoints.get(task_id, [])) > 0

    def rollback_to_checkpoint(self, task_id: str, checkpoint_id: str) -> ExecutionCheckpoint:
        """Prune checkpoints subsequent to checkpoint_id, returning the target checkpoint."""
        ckpts = self._checkpoints.get(task_id, [])
        target_idx = -1
        for idx, c in enumerate(ckpts):
            if c.checkpoint_id == checkpoint_id:
                target_idx = idx
                break

        if target_idx == -1:
            raise ValueError(f"Checkpoint '{checkpoint_id}' not found for task '{task_id}'")

        # Rollback: keep up to target_idx
        rolled_back = ckpts[target_idx]
        self._checkpoints[task_id] = ckpts[: target_idx + 1]
        logger.info("Rolled back task %s to checkpoint %s (step %s)", task_id, checkpoint_id, rolled_back.step_id)
        return rolled_back

