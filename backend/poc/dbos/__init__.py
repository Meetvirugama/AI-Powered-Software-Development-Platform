"""
DBOS Transact Proof-of-Concept Package.

Evaluates DBOS Transact for reliable, durable multi-step job execution
(Issue #184 evaluation criteria).
"""

from .workflow import (
    DurableSyncWorkflow,
    StepRecord,
    WorkflowExecutionResult,
    run_durable_sync_workflow,
)

__all__ = [
    "DurableSyncWorkflow",
    "StepRecord",
    "WorkflowExecutionResult",
    "run_durable_sync_workflow",
]
