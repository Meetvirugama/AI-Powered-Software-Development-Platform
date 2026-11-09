# 09 — Database Schema, Checkpoints, and Audit Trails

## 1. Executive Summary

Autonomous execution modifies repository code, runs tests, and interacts with remote version control. Full forensic traceability is mandatory. Every attempt, synthesis decision, patch hash, validation metric, and workflow state transition is durably audited in PostgreSQL.

---

## 2. Persisted Audit Models and Entities

### 2.1 StepExecutionRecord Auditing
Within `AgentExecutionLoop`, each executed step records:
- `step_id`: Unique identifier of the plan step.
- `action_type`: `edit`, `patch`, `create`, `write`, `verify`, or `run_tests`.
- `target_file`: Canonicalized relative path.
- `synthesis_attempts`: Total attempts taken (1 to 3).
- `patch_hashes`: SHA-256 hashes of synthesized edit blocks.
- `validation_status`: `VALIDATED`, `REJECTED`, or `FAILED`.
- `changed_files`: List of files mutated on disk.
- `failure_category`: Categorized error reason if failed.

### 2.2 TaskCheckpoint Architecture
At each major durable step, a `TaskCheckpoint` record is persisted:
- `task_id`: Target task UUID.
- `checkpoint_type`: `APPROVED`, `WORKSPACE_SETUP`, `PLAN_EXECUTION`, `DIFF_VERIFIED`, `TESTS_COMPLETED`, `VERIFIED`, `PR_PUBLISHED`.
- `state_data`: JSON payload containing step records, verified git commit SHA, and remaining repair budget.
- **Secret Scrubbing**: All passwords, API keys, JWTs, and bearer tokens are scrubbed using `scrub_sensitive_data()` before database insertion.

### 2.3 TaskEvent Ordered Timeline
Every milestone emits a `TaskEvent` row:
- `event_type`: State transition or failure event.
- `summary`: Human-readable summary without raw secrets.
- `payload`: Detailed structured event data.
- `created_at`: Strict chronological ordering.

---

## 3. Data Integrity & Migration Strategy

- No destructive database alterations were required; existing SQLAlchemy models (`Task`, `TaskPlan`, `TaskApproval`, `TaskCheckpoint`, `TaskEvent`) already provided structured JSONB columns (`state_data`, `payload`, `metadata`) that cleanly house workflow execution metadata.
- `TaskRepository` was enhanced with `get_approved_plan(task_id)` to query the active approved plan version without breaking existing queries.
