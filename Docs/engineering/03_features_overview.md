# 03. Features Overview
> **Version:** 3.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-10-15 | **Status:** Synchronized

---

## Complete Feature Matrix

### Priority Legend
| Symbol | Priority | Meaning | Target Milestone |
|---|---|---|---|
| P0 | Critical | Essential core capability | Weeks 1–3 |
| P1 | Strong | Significantly enhances developer workflow | Weeks 2–3 |
| P2 | Extended | Advanced capabilities | Post-launch |

---

## 1. Repository Intelligence Foundation (Week 1 — COMPLETE)

| ID | Feature | Priority | Status | Owner | Implementation Summary |
|---|---|---|---|---|---|
| F-01 | GitHub Integration (OAuth, App, token manager) | P0 | 🟢 Done | Parth / Yug | `app/integrations/github/`, JWT cookie session |
| F-02 | Repository Engine (walk, detect, tree-sitter, symbols) | P0 | 🟢 Done | Prit | `backend/scanner/`, 8 languages parsed |
| F-03 | Repository Sync (clone → scan → index pipeline) | P0 | 🟢 Done | Yug / Parth / Devu | `app/services/repository_sync.py`, Redis queue |
| F-04 | Hybrid Retrieval (Vector + Lexical + RRF + Rerank) | P0 | 🟢 Done | Meet | pgvector `<=>` cosine + FTS + RRF + Cross-Encoder |
| F-05 | LLM Gateway (Gemini & Groq) | P0 | 🟢 Done | Meet | `backend/ai/llm/client.py`, schemas & retries |
| F-06 | Embedding Service & Batching | P0 | 🟢 Done | Meet | `backend/ai/embeddings/service.py`, dimension validation |
| F-07 | ContextBuilder (Token budget & truncation) | P0 | 🟢 Done | Meet | `backend/ai/context/builder.py`, `cl100k_base` budget |
| F-08 | PromptBuilder & GroundingValidator | P0 | 🟢 Done | Dev | Data separation, removes hallucinated lines |
| F-09 | OutputValidator & JSON Repair Loop | P0 | 🟢 Done | Dev | Pydantic validation + LLM-assisted repair |
| F-10 | Repository Chat & Hybrid Search API | P0 | 🟢 Done | Yug / Meet | `POST /api/v1/repositories/{id}/chat`, `/search` |
| F-11 | React 19 Workbench Layout | P0 | 🟢 Done | Dhramraj | Fixed-viewport layout, repository explorer, chat |

---

## 2. Developer Intelligence Suite (Week 2 — ACTIVE)

| ID | Feature | Priority | Status | Owner | Deliverable & Contract |
|---|---|---|---|---|---|
| F-12 | Shared `IntelligenceContext` & Symbol Resolution | P0 | 🟢 Done | Meet / Prit | `TargetSnippet`, `SymbolContext`, caller references |
| F-13 | Code Explanation Service | P0 | 🔵 In Progress | Dev / Meet | Purpose, logic flow, key symbols, limitations |
| F-14 | Dedicated Bug Detection (Static + AI) | P0 | 🔵 In Progress | Dev / Devu | Off-by-one, null safety, resource leak, Ruff/Bandit |
| F-15 | Framework-Aware Test Generation | P0 | 🔵 In Progress | Dev / Prit | `pytest`, `unittest`, `jest` compatible test files |
| F-16 | Standalone AI Code Review | P0 | 🔵 In Progress | Dev / Parth | Correctness, security, performance, maintainability diff review |
| F-17 | Analysis Run & Finding Persistence | P0 | 🔵 In Progress | Om | `analysis_runs` and `code_findings` models |
| F-18 | Workbench Code Drawers & Actions | P0 | 🔵 In Progress | Dhramraj | Code explanation drawer, bug inspector, test preview |
| F-19 | Analysis API Routing | P0 | 🔵 In Progress | Yug | `/explain`, `/detect-bugs`, `/generate-tests`, `/review` |
| F-20 | Prompt-Injection Shields & Sanitization | P0 | 🔵 In Progress | Sukun | Tagged boundaries, secret redaction in findings |
| F-21 | Defect Fixtures & Acceptance Suite | P0 | 🔵 In Progress | Keval | Acceptance scenarios A through E verification |

---

## 3. Workflow Automation & GitHub Ecosystem (Week 3 — UPCOMING)

| ID | Feature | Priority | Status | Owner | Planned Capability |
|---|---|---|---|---|---|
| F-22 | GitHub Issue Intake & Creation (F31) | P0 | ⚪ Todo | Parth / Yug | Import issue, create issue from finding |
| F-23 | Task Planner & Implementation Steps (F32) | P0 | ⚪ Todo | Meet / Dev | Structured plan, affected files, test strategy |
| F-24 | Mandatory Human Approval Gate (F32) | P0 | ⚪ Todo | Meet / Dhramraj | Server-enforced approval, invalidation on revision |
| F-25 | Isolated Workspace & Task Branch (F33) | P0 | ⚪ Todo | Prit / Parth | `.workspaces/task-<id>`, `agent/task-<id>` |
| F-26 | Controlled Tool Router & Policy Engine (F34) | P0 | ⚪ Todo | Devu / Sukun | Command template allowlist, argument validation |
| F-27 | Restricted Test Runner (F35) | P0 | ⚪ Todo | Prit / Devu | Test execution with timeout and output bounds |
| F-28 | Bounded Self-Repair Loop (F35) | P0 | ⚪ Todo | Meet / Dev | Targeted repair on failure, ceiling of 3 attempts |
| F-29 | Independent Verification & AI Review (F36) | P0 | ⚪ Todo | Dev / Keval | Verification check, static scan, PR summary |
| F-30 | Git Branch Push & GitHub Draft PR (F37) | P0 | ⚪ Todo | Parth / Yug | Human authorization, branch push, Draft PR creation |
| F-31 | Task Dashboard & Execution Timeline (F38) | P0 | ⚪ Todo | Dhramraj | Live task execution progress, timeline events |
| F-32 | Checkpoints & Crash Recovery (F39) | P0 | ⚪ Todo | Om / Yug | Task recovery state, idempotent operations |
| F-33 | Security Attack Matrix & Release Gate (F40) | P0 | ⚪ Todo | Sukun / Keval | End-to-end verification and release sign-off |
