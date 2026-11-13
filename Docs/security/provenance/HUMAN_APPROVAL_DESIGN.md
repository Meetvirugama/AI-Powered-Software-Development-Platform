# Human-in-the-Loop Approval Architecture & Cryptographic Binding

## 1. Design Overview

When an autonomous AI agent encounters a plan step or tool operation classified as `HIGH_RISK` (e.g., deleting existing repository files, executing custom scripts, or updating workflow pipelines), execution is immediately suspended. A human developer must review the proposed action and authorize execution.

To guarantee that human approval cannot be exploited by an attacker (e.g., via time-of-check-to-time-of-use attacks, approval replay, or argument mutation), the platform implements **Cryptographic Argument Binding**.

```mermaid
sequenceDiagram
    autonumber
    participant Loop as AgentExecutionLoop
    participant Policy as TaintPolicyEngine
    participant DB as Approval Store
    participant UI as Developer Workbench UI
    actor Dev as Human Reviewer

    Loop->>Policy: evaluate_step(HIGH_RISK PlanStep)
    Policy-->>Loop: PolicyDecision(allowed=False, approval_required=True)
    Loop->>Policy: Request Approval Token
    Policy->>Policy: Compute SHA-256(canonical_args)
    Policy->>DB: Store ExecutionApproval(task_id, repo_id, tool, hash, expires_at)
    Loop->>UI: Emit Approval Required Notification
    
    Dev->>UI: Inspect Diff / Arguments / Provenance Lineage
    Dev->>UI: Click "Approve Step"
    UI->>Policy: grant_approval(approval_id, user_id)
    
    Loop->>Policy: evaluate_step(with approval_id)
    Policy->>Policy: Verify (task_id, repo_id, tool_name)
    Policy->>Policy: Verify SHA-256(current_args) == stored_hash
    Policy->>Policy: Verify not expired AND not consumed
    Policy->>Policy: Mark consumed=True
    Policy-->>Loop: PolicyDecision(allowed=True)
    Loop->>Loop: Proceed with Sandbox Execution
```

---

## 2. Cryptographic Argument Binding

An approval token is strictly bound to the exact payload of the requested tool invocation. Any tampering with argument values invalidates the token.

### 2.1 Canonical Argument Serialization
Arguments are serialized to JSON with deterministic key ordering and compact delimiters:

$$\text{CanonicalJSON}(A) = \text{json.dumps}(A, \text{sort\_keys}=\text{True}, \text{separators}=(\text{","}, \text{":"}))$$

$$\text{ArgumentsHash}(A) = \text{SHA-256}(\text{CanonicalJSON}(A))$$

In [`backend/ai/security/taint_policy.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/security/taint_policy.py#L32-L42):
```python
@staticmethod
def compute_arguments_hash(arguments: Dict[str, Any]) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

### 2.2 Replay & Tampering Protections

| Security Threat | Attack Vector | Mitigation in `ExecutionApproval` |
|---|---|---|
| **Parameter Tampering** | Attacker gets approval to delete `temp.txt`, then agent mutates arguments to delete `main.py` | Hash mismatch: `compute_arguments_hash({"path": "main.py"}) != stored_hash`. Execution denied. |
| **Approval Replay** | Attacker reuses an approval token for repeated executions | Single-use consumption: upon first successful evaluation, `approval.consume()` marks `consumed=True`. Subsequent attempts fail. |
| **Cross-Task Hijacking** | Approval issued for Task A is submitted for Task B | Scope binding: `approval.task_id == task_id` check fails. |
| **Cross-Repository Hijacking** | Approval granted in public test repo is submitted in production repo | Repository binding: `approval.repository_id == repository_id` check fails. |
| **Stale Authorization** | Approval granted hours or days earlier is activated after code changes | Time-to-Live (TTL): `datetime.now(timezone.utc) > approval.expires_at` triggers expiration denial. |

---

## 3. The `ExecutionApproval` Data Model

Defined in [`backend/ai/security/taint_policy.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/security/taint_policy.py#L45-L89):

```python
class ExecutionApproval(BaseModel):
    approval_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    repository_id: Optional[str] = None
    tool_name: str
    arguments_hash: str
    user_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    consumed: bool = False
    consumed_at: Optional[datetime] = None

    def is_valid(self) -> bool:
        if self.consumed:
            return False
        return datetime.now(timezone.utc) <= self.expires_at

    def matches(self, tool_name: str, arguments: Dict[str, Any], task_id: str, repository_id: Optional[str] = None) -> bool:
        if self.task_id != task_id:
            return False
        if self.repository_id and repository_id and self.repository_id != repository_id:
            return False
        if self.tool_name != tool_name:
            return False
        computed = TaintPolicyEngine.compute_arguments_hash(arguments)
        return hmac.compare_digest(self.arguments_hash, computed)

    def consume(self) -> None:
        self.consumed = True
        self.consumed_at = datetime.now(timezone.utc)
```

Notice the use of `hmac.compare_digest` to prevent timing side-channel attacks during hash validation.

---

## 4. Audit Logging & Non-Repudiation

Whenever an approval is granted, consumed, or rejected, the event is recorded by `ProvenanceAuditLogger`:

```python
audit_logger.log(
    event_type=ProvenanceAuditEventType.APPROVAL_GRANTED,
    task_id=task_id,
    provenance_id=None,
    details={
        "approval_id": approval.approval_id,
        "tool_name": approval.tool_name,
        "arguments_hash": approval.arguments_hash,
        "authorized_by": user_id,
    }
)
```

The audit trail provides immutable forensic evidence identifying who authorized high-risk operations and the exact parameters that were executed.
