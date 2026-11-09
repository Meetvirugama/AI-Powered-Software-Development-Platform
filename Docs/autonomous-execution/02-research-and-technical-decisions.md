# 02 — Research & Technical Decisions

## 1. Research Overview

To design an effective, robust autonomous code synthesis and durable execution engine, we surveyed state-of-the-art agent architectures and distributed workflow systems.

---

## 2. Code Editing Architectures

### 2.1 SWE-agent (Princeton NLP)
- **Core Concept:** Providing LLMs with specialized, constrained software engineering tools (e.g., search/replace, line navigation) drastically reduces generation errors compared to unconstrained code replacement.
- **Key Insight:** Immediate deterministic lint/syntax validation after editing enables rapid rejection of corrupted output before downstream test pipelines run.
- **Adopted:** Constrained search/replace edit blocks, single-match requirements, and immediate AST/linter validation.

### 2.2 Aider (Paul Gauthier)
- **Core Concept:** LLMs perform best on code maintenance when generating targeted search/replace blocks with exact context rather than whole-file rewrites or standard unified diffs (which models frequently miscalculate hunk offsets for).
- **Key Insight:** Each block specifies exact search text and replacement text. The patch applicator finds the unique occurrence and performs atomic replacement.
- **Adopted:** Strict single-match verification (`occurrences == 1`). If zero matches or multiple matches are detected, the patch is rejected immediately.

### 2.3 Agentless (OpenAI / University of Illinois)
- **Core Concept:** Two-phase approach: localizing relevant files/functions first, then generating candidate patches in parallel and ranking them based on test suites.
- **Evaluation:** While multi-candidate ranking is highly effective for offline benchmarks, running parallel test executions across multiple full workspaces in production requires substantial compute, token budgets, and worker resources.
- **Decision:** Candidate patch selection is prioritized as **P3 (Future Work)**. The current priority is rock-solid single-path synthesis with bounded self-refinement.

---

## 3. Iterative Self-Correction & Verbal Reinforcement

### 3.1 Reflexion (Shinn et al.) & Self-Refine (Madaan et al.)
- **Core Concept:** Models improve output quality significantly when provided with structured execution feedback (syntax errors, linter output, exception traces) in subsequent turns.
- **Key Insight:** Self-correction loops must be bounded (2–3 iterations). Without strict bounds, models can enter hallucination loops or degrade code quality.
- **Adopted:** Bounded 3-attempt loop:
  - Attempt 1: Initial synthesis.
  - Attempt 2: First correction using syntax/linter failure feedback.
  - Attempt 3: Final correction.
  - If still invalid: Fail safely and abort execution.

---

## 4. Durable Execution Systems

### 4.1 DBOS vs Temporal
| Dimension | DBOS Transact | Temporal |
| :--- | :--- | :--- |
| **Architecture** | Lightweight Python library backed by standard PostgreSQL | Heavy distributed server cluster (Go/Java) requiring separate deployment |
| **Integration** | Directly decorates Python functions (`@DBOS.workflow`, `@DBOS.step`) | Requires activity workers, workflows, and gRPC connection |
| **Persistence** | System tables inside PostgreSQL database | Clustered Cassandra/PostgreSQL persistence layer |
| **Replay & Idempotency**| Native step memoization via transaction log | Event-sourcing history replay |
| **Suitability** | Perfect fit for existing Python/FastAPI/PostgreSQL stack | Excessive operational overhead for current system scale |

### 4.2 DBOS Architectural Decision
- **Workflow Scope:** Wrap the multi-stage post-approval workflow (`execute` $\rightarrow$ `checkpoint` $\rightarrow$ `test` $\rightarrow$ `repair` $\rightarrow$ `verify` $\rightarrow$ `draft_pr`) as durable DBOS steps.
- **Database Session Isolation:** Never pass live SQLAlchemy ORM sessions into durable step arguments. Steps receive serializable identifiers (`task_id`, `actor_id`, etc.) and open fresh sessions via `SessionLocal()`.
- **Fault-Tolerant Fallback:** In environments where DBOS is uninitialized or in test mocks, the workflow engine falls back to a tested sequential execution runner with equivalent checkpointing and status tracking.

