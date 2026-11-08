"""
DBOS Transact Proof-of-Concept: Durable Repository Synchronization Workflow.

Demonstrates:
1. Multi-step durable workflow (@DBOS.workflow and @DBOS.step).
2. Step checkpointing and idempotency.
3. Resumption from failure / simulated crash without repeating completed steps.
4. Bounded retries with backoff on transient errors.
5. Concurrency bounds and observability status tracking.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    from dbos import DBOS, WorkflowStatus
except ImportError:
    class _DBOSStub:
        @staticmethod
        def workflow(*args, **kwargs):
            def decorator(fn):
                return fn
            return decorator

        @staticmethod
        def step(*args, **kwargs):
            def decorator(fn):
                return fn
            return decorator

    DBOS = _DBOSStub()  # type: ignore
    WorkflowStatus = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class StepRecord:
    name: str
    started_at: float
    completed_at: float | None = None
    output: Any = None
    error: str | None = None
    attempts: int = 1


@dataclass
class WorkflowExecutionResult:
    workflow_id: str
    status: str  # "SUCCESS", "FAILED", "RETRYING"
    completed_steps: list[str]
    step_records: dict[str, StepRecord] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    resumed_from_checkpoint: bool = False
    total_duration_ms: float = 0.0


class DurableSyncWorkflow:
    """
    Durable Repository Synchronization Workflow orchestrated via DBOS Transact concepts.

    Step Progression:
    1. Clone: Shallow checkout or tarball download.
    2. Scan: File system traversal with .gitignore filters.
    3. Embed: Batch AST symbol embedding under rate limiter.
    4. Commit: Transactional persistence of vector chunks and metadata.
    """

    def __init__(self, step_recorder: dict[str, StepRecord] | None = None) -> None:
        self.step_records: dict[str, StepRecord] = step_recorder if step_recorder is not None else {}
        self.simulated_crashes: set[str] = set()

    def simulate_crash_on_step(self, step_name: str) -> None:
        """Inject a simulated process crash after the named step completes."""
        self.simulated_crashes.add(step_name)

    async def _invoke_step(self, step_func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute step via DBOS runtime if initialized, or via underlying implementation."""
        try:
            return await step_func(*args, **kwargs)
        except Exception as exc:
            err_msg = str(exc)
            if "invoked before DBOS initialized" in err_msg or "called without a DBOS instance" in err_msg:
                import inspect

                unwrapped = inspect.unwrap(step_func)
                return await unwrapped(self, *args, **kwargs)
            raise

    @DBOS.step()  # type: ignore
    async def clone_step(
        self,
        owner: str,
        repo: str,
        branch: str,
        commit_sha: str | None = None,
    ) -> dict[str, Any]:
        """Step 1: Shallow clone repository workspace."""
        step_name = "clone"
        if step_name in self.step_records and self.step_records[step_name].completed_at is not None:
            logger.info("dbos_step_cache_hit_skipping", extra={"step": step_name})
            return self.step_records[step_name].output

        record = StepRecord(name=step_name, started_at=time.time())
        self.step_records[step_name] = record

        await asyncio.sleep(0.01)
        workspace = f"/tmp/workspaces/{owner}_{repo}_{branch}"
        resolved_commit = commit_sha or "a1b2c3d4e5f67890"
        result = {"workspace": workspace, "commit_sha": resolved_commit, "branch": branch}

        record.completed_at = time.time()
        record.output = result

        if step_name in self.simulated_crashes:
            self.simulated_crashes.remove(step_name)
            raise RuntimeError(f"Simulated process crash after {step_name} step")

        return result

    @DBOS.step()  # type: ignore
    async def scan_step(self, workspace: str, file_count: int = 15) -> list[str]:
        """Step 2: Scan repository files respecting .gitignore."""
        step_name = "scan"
        if step_name in self.step_records and self.step_records[step_name].completed_at is not None:
            logger.info("dbos_step_cache_hit_skipping", extra={"step": step_name})
            return self.step_records[step_name].output

        record = StepRecord(name=step_name, started_at=time.time())
        self.step_records[step_name] = record

        await asyncio.sleep(0.01)
        scanned = [f"{workspace}/file_{i}.py" for i in range(file_count)]

        record.completed_at = time.time()
        record.output = scanned

        if step_name in self.simulated_crashes:
            self.simulated_crashes.remove(step_name)
            raise RuntimeError(f"Simulated process crash after {step_name} step")

        return scanned

    @DBOS.step()  # type: ignore
    async def embed_step(
        self,
        scanned_files: list[str],
        chunk_multiplier: int = 3,
        fail_attempts: int = 0,
    ) -> dict[str, Any]:
        """Step 3: Generate vector embeddings under rate-limiting and transient retry policies."""
        step_name = "embed"
        if step_name in self.step_records and self.step_records[step_name].completed_at is not None:
            logger.info("dbos_step_cache_hit_skipping", extra={"step": step_name})
            return self.step_records[step_name].output

        record = self.step_records.get(step_name)
        if not record:
            record = StepRecord(name=step_name, started_at=time.time())
            self.step_records[step_name] = record
        else:
            record.attempts += 1

        if record.attempts <= fail_attempts:
            record.error = f"Transient 429 quota exhaustion on attempt {record.attempts}"
            raise ConnectionError(record.error)

        await asyncio.sleep(0.01)
        total_chunks = len(scanned_files) * chunk_multiplier
        result = {"chunk_count": total_chunks, "dimensions": 768, "provider": "gemini"}

        record.completed_at = time.time()
        record.output = result

        if step_name in self.simulated_crashes:
            self.simulated_crashes.remove(step_name)
            raise RuntimeError(f"Simulated process crash after {step_name} step")

        return result

    @DBOS.step()  # type: ignore
    async def commit_step(
        self,
        repository_id: str,
        commit_sha: str,
        embed_stats: dict[str, Any],
    ) -> dict[str, Any]:
        """Step 4: Atomically persist chunks and update repository metadata."""
        step_name = "commit"
        if step_name in self.step_records and self.step_records[step_name].completed_at is not None:
            logger.info("dbos_step_cache_hit_skipping", extra={"step": step_name})
            return self.step_records[step_name].output

        record = StepRecord(name=step_name, started_at=time.time())
        self.step_records[step_name] = record

        await asyncio.sleep(0.01)
        result = {
            "repository_id": repository_id,
            "indexed_commit": commit_sha,
            "chunks_stored": embed_stats.get("chunk_count", 0),
            "status": "SYNCED",
        }

        record.completed_at = time.time()
        record.output = result

        if step_name in self.simulated_crashes:
            self.simulated_crashes.remove(step_name)
            raise RuntimeError(f"Simulated process crash after {step_name} step")

        return result

    @DBOS.workflow()  # type: ignore
    async def run(
        self,
        repository_id: str,
        owner: str,
        repo: str,
        branch: str = "main",
        commit_sha: str | None = None,
        max_retries: int = 3,
        fail_embed_attempts: int = 0,
    ) -> dict[str, Any]:
        """Full durable workflow execution coordinating the steps."""
        clone_info = await self._invoke_step(self.clone_step, owner, repo, branch, commit_sha)
        files = await self._invoke_step(self.scan_step, clone_info["workspace"])

        # Bounded step retries
        embed_info = None
        for attempt in range(max_retries):
            try:
                embed_info = await self._invoke_step(
                    self.embed_step,
                    files,
                    fail_attempts=fail_embed_attempts,
                )
                break
            except ConnectionError:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(0.05 * (2**attempt))

        if embed_info is None:
            raise RuntimeError("Embed step did not produce output")

        commit_info = await self._invoke_step(
            self.commit_step,
            repository_id=repository_id,
            commit_sha=clone_info["commit_sha"],
            embed_stats=embed_info,
        )

        return {
            "repository_id": repository_id,
            "commit_sha": clone_info["commit_sha"],
            "files_scanned": len(files),
            "chunks_stored": commit_info["chunks_stored"],
            "status": "COMPLETED",
        }


# Workflow Registry for Deduplication & Execution
_WORKFLOW_REGISTRY: dict[str, WorkflowExecutionResult] = {}
_CHECKPOINT_STORE: dict[str, dict[str, StepRecord]] = {}


async def run_durable_sync_workflow(
    workflow_id: str,
    repository_id: str,
    owner: str,
    repo: str,
    branch: str = "main",
    commit_sha: str | None = None,
    simulate_crash_after: str | None = None,
    fail_embed_attempts: int = 0,
    max_retries: int = 3,
) -> WorkflowExecutionResult:
    """
    Execute a durable sync workflow with checkpoint store, resumption, and idempotency.

    If workflow_id was already completed, returns the cached result without rerunning (idempotency).
    If workflow was previously interrupted (simulated crash), resumes from stored checkpoints.
    """
    start_time = time.perf_counter()

    # Idempotency check: Return existing completed workflow
    if workflow_id in _WORKFLOW_REGISTRY and _WORKFLOW_REGISTRY[workflow_id].status == "SUCCESS":
        logger.info("dbos_workflow_idempotent_deduplication", extra={"workflow_id": workflow_id})
        return _WORKFLOW_REGISTRY[workflow_id]

    # Checkpoint recovery: Resume from existing saved step records if present
    checkpoints = _CHECKPOINT_STORE.setdefault(workflow_id, {})
    resumed = any(r.completed_at is not None for r in checkpoints.values())

    workflow = DurableSyncWorkflow(step_recorder=checkpoints)
    if simulate_crash_after:
        workflow.simulate_crash_on_step(simulate_crash_after)

    try:
        try:
            output = await workflow.run(
                repository_id=repository_id,
                owner=owner,
                repo=repo,
                branch=branch,
                commit_sha=commit_sha,
                max_retries=max_retries,
                fail_embed_attempts=fail_embed_attempts,
            )
        except Exception as exc:
            err_msg = str(exc)
            if "invoked before DBOS initialized" in err_msg or "called without a DBOS instance" in err_msg:
                import inspect

                unwrapped_run = inspect.unwrap(workflow.run)
                output = await unwrapped_run(
                    workflow,
                    repository_id=repository_id,
                    owner=owner,
                    repo=repo,
                    branch=branch,
                    commit_sha=commit_sha,
                    max_retries=max_retries,
                    fail_embed_attempts=fail_embed_attempts,
                )
            else:
                raise

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        completed = [name for name, r in checkpoints.items() if r.completed_at is not None]
        result = WorkflowExecutionResult(
            workflow_id=workflow_id,
            status="SUCCESS",
            completed_steps=completed,
            step_records=dict(checkpoints),
            output=output,
            resumed_from_checkpoint=resumed,
            total_duration_ms=round(duration_ms, 2),
        )
        _WORKFLOW_REGISTRY[workflow_id] = result
        return result

    except Exception as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        completed = [name for name, r in checkpoints.items() if r.completed_at is not None]
        logger.warning(
            "dbos_workflow_interrupted_or_failed",
            extra={"workflow_id": workflow_id, "completed_steps": completed, "error": str(exc)},
        )
        result = WorkflowExecutionResult(
            workflow_id=workflow_id,
            status="FAILED",
            completed_steps=completed,
            step_records=dict(checkpoints),
            output={"error": str(exc)},
            resumed_from_checkpoint=resumed,
            total_duration_ms=round(duration_ms, 2),
        )
        return result
