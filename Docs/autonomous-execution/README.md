# Autonomous Execution Documentation Index

Welcome to the comprehensive technical documentation for **Feature F22: Autonomous Code Synthesis, Plan-Bound Editing, and Durable Workflow Execution** (Issue #202 / Issue #203).

This documentation suite details the end-to-end architecture enabling the platform to autonomously synthesize code changes, enforce plan-bound security boundaries, apply search/replace patches, and execute multi-stage workflows durably with HTTP 202 acceptance and SSE streaming.

---

## Document Roadmap

| Document | Title | Description |
| :--- | :--- | :--- |
| **[00](00-existing-architecture-audit.md)** | **Existing Architecture Audit** | Complete forensic audit of pre-existing execution loop, synchronous bottlenecks, and fallback loops. |
| **[01](01-requirements-and-scope.md)** | **Requirements & Scope** | Functional, security, non-functional requirements, and P0/P1 acceptance criteria. |
| **[02](02-research-and-technical-decisions.md)** | **Research & Technical Decisions** | Comparative analysis of SWE-agent, Aider, Agentless, Reflexion, Self-Refine, and DBOS. |
| **[03](03-edit-synthesizer-architecture.md)** | **EditSynthesizer Architecture** | Service contracts, search/replace block design, context gathering, and prompt engineering. |
| **[04](04-patch-validation-and-application.md)** | **Patch Validation & Application** | The 7-stage validation pipeline: JSON schema, single match, path safety, atomic application, AST syntax, linting, and stale fingerprinting. |
| **[05](05-plan-bound-edit-security.md)** | **Plan-Bound Edit Security** | 3-level scope enforcement, ADR-010 human approval gate, and threat model analysis. |
| **[06](06-self-refinement-and-budget.md)** | **Self-Refinement & Budgets** | Hard 3-attempt ceiling, verbal failure reinforcement, loop detection, and cycle prevention. |
| **[07](07-durable-workflow-architecture.md)** | **Durable Workflow Architecture** | DBOS durable steps, stable workflow IDs, idempotency, checkpointing, and crash recovery. |
| **[08](08-api-and-frontend-integration.md)** | **API & Frontend Integration** | HTTP 202 Accepted, GET `/workflow-status`, Redis pubsub SSE streaming, and React UI integration. |
| **[09](09-database-and-audit.md)** | **Database & Audit Trails** | Data models, step execution records, task checkpoints, timeline events, and secret scrubbing. |
| **[10](10-testing-and-validation.md)** | **Testing & Validation Report** | Automated test verification across 83 test cases (100% pass rate) and frontend build verification. |
| **[11](11-implementation-changelog.md)** | **Implementation Changelog** | Chronological record of architectural changes, modifications, decisions, and fixes. |
| **[12](12-future-candidate-patch-selection.md)** | **Candidate Patch Selection (P3)** | Proposed multi-candidate patch ranking and test-driven selection roadmap. |
| **[13](13-operations-and-troubleshooting.md)** | **Operations & Troubleshooting** | Operational runbooks, failure mode diagnostics, SSE reconnect behavior, and recovery steps. |

---

## Quick Reference: Core Services & Endpoints

### Backend Services
- **`backend/ai/services/edit_synthesizer.py`**: Search/replace block synthesis, 7-stage validation pipeline, bounded self-refinement.
- **`backend/ai/services/agent_execution_loop.py`**: Step executor with synthesis dispatch, payload priority, and loop detection.
- **`backend/ai/workflows/autonomous_task_workflow.py`**: DBOS durable workflow containing 7 durable steps.

### REST Endpoints
- `POST /api/v1/tasks/{task_id}/run-workflow` (Accepts `async_execution=True` -> `HTTP 202 Accepted`)
- `GET /api/v1/tasks/{task_id}/workflow-status` (Returns active status, current step, and progress percentage)
