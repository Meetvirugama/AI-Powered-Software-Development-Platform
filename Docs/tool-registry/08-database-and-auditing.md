# 08 — Database Schema & Audit Logging

## 1. Overview

Every tool invocation within the platform is audited for security, compliance, debugging, and post-mortem analysis. To support the Unified Tool Registry, the underlying `tool_invocations` table and ORM model have been extended with 9 audit fields and two additional execution statuses.

---

## 2. Alembic Migration `g4d5e6f7a8b9`

The migration script [`backend/migrations/versions/g4d5e6f7a8b9_extend_tool_invocations_audit_fields.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/migrations/versions/g4d5e6f7a8b9_extend_tool_invocations_audit_fields.py) adds the new audit columns to the `tool_invocations` table using batch operations to maintain SQLite compatibility during testing while targeting production PostgreSQL.

- **Revision ID:** `g4d5e6f7a8b9`
- **Down Revision:** `f3c4d5e6a7b8`
- **Table Altered:** `tool_invocations`

```python
def upgrade() -> None:
    with op.batch_alter_table("tool_invocations") as batch_op:
        batch_op.add_column(sa.Column("tool_version", sa.String(length=32), nullable=True, server_default="1.0.0"))
        batch_op.add_column(sa.Column("tool_source", sa.String(length=32), nullable=True, server_default="builtin"))
        batch_op.add_column(sa.Column("provider_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("risk_tier", sa.String(length=32), nullable=True, server_default="read_only"))
        batch_op.add_column(sa.Column("schema_fingerprint", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("execution_timeout_s", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("execution_timed_out", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.add_column(sa.Column("rate_limit_status", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("error_category", sa.String(length=64), nullable=True))
```

---

## 3. ORM Model Extension (`ToolInvocation`)

Defined in [`backend/app/models/task.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/models/task.py):

### 3.1 Extended Invocations Status Enum
```python
class ToolInvocationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"          # NEW
    RATE_LIMITED = "rate_limited" # NEW
```

### 3.2 Audit Field Definitions
| Column | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `tool_version` | `VARCHAR(32)` | YES (default "1.0.0") | Semantic version of the invoked tool |
| `tool_source` | `VARCHAR(32)` | YES (default "builtin") | Origin (`builtin`, `mcp`, `plugin`) |
| `provider_id` | `VARCHAR(128)` | YES | Identifier of external provider or MCP server |
| `risk_tier` | `VARCHAR(32)` | YES (default "read_only") | Tool risk tier assigned at registration |
| `schema_fingerprint`| `VARCHAR(64)` | YES | SHA-256 hash of input schema at execution time |
| `execution_timeout_s`| `FLOAT` | YES | Timeout constraint applied to invocation |
| `execution_timed_out`| `BOOLEAN` | NO (default false) | Flag indicating whether invocation timed out |
| `rate_limit_status` | `VARCHAR(32)` | YES | `allowed`, `limited`, or `exempt` |
| `error_category` | `VARCHAR(64)` | YES | Structured error code (e.g. `INVALID_ARGUMENTS`) |

---

## 4. API Schemas & Service Integration

1. **`ToolInvocationResponse` (`backend/app/schemas/task.py`):**
   - Serializes all 9 audit fields for API consumers, UI dashboards, and reporting workers.

2. **`TaskRepository.record_tool_invocation` (`backend/app/repositories/task_repository.py`):**
   - Persists all audit fields to PostgreSQL.

3. **`TaskHistoryService` (`backend/app/services/task_history_service.py`):**
   - Appends high-fidelity tool execution events into the task timeline and recovery logs.

4. **`TaskExecutionOrchestrator` (`backend/app/services/task_execution_orchestrator.py`):**
   - Bridges the agent loop with `record_tool_invocation`, classifying `TIMEOUT`, `RATE_LIMITED`, `BLOCKED`, and `COMPLETED` events in real time.
