# 10. Development Tasks — Master Task Board
> **Version:** 3.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-10-15

> [!NOTE]
> Task data is synchronized with `Docs/daily_tasks.md`, `Docs/week1.md`, `Docs/week2.md`, and `Docs/week3.md`.

---

## Status Legend

```
DONE        — Merged, tested, and verified
IN PROGRESS — Actively being implemented
TODO        — Planned and scheduled
BLOCKED     — Waiting on dependency or review
```

---

## WEEK 1 — Repository Intelligence Foundation (100% COMPLETE)

### Week 1 Milestone Goal
A user connects a GitHub repository, the backend clones and scans it, extracts symbols and dependency edges, indexes chunks into pgvector, and answers grounded questions via the fixed-viewport React 19 Workbench with source citations.

| Task ID | Task | Owner | Priority | Status | Verification / Artifacts |
|---|---|---|---|---|---|
| W1-01 | FastAPI project skeleton + config + logging | Yug | P0 | DONE | `app/main.py`, `app/core/logging.py`, health API |
| W1-02 | Database foundation + pgvector + migrations | Om | P0 | DONE | Alembic migrations, `code_chunks`, `memory_entries` |
| W1-03 | GitHub App integration + OAuth flow | Parth / Yug | P0 | DONE | `app/integrations/github/`, JWT cookie auth |
| W1-04 | Repository Sync Service & Redis queue | Yug / Parth | P0 | DONE | `app/services/repository_sync.py`, worker loop |
| W1-05 | tree-sitter AST parser & language detector | Prit | P0 | DONE | `backend/scanner/`, 8 languages detected |
| W1-06 | Symbol & edge extractor | Prit | P0 | DONE | `symbols.py`, `graph.py`, symbol tables |
| W1-07 | Symbol chunker & tiktoken token counter | Devu | P0 | DONE | `backend/indexer/chunker.py` |
| W1-08 | LLM Gateway (Gemini + Groq) | Meet | P0 | DONE | `backend/ai/llm/client.py`, schemas & retries |
| W1-09 | Embedding service & pgvector storage | Meet | P0 | DONE | `backend/ai/embeddings/service.py` |
| W1-10 | Hybrid retrieval (Vector + Lexical FTS + RRF) | Meet | P0 | DONE | `vector.py`, `lexical.py`, `fusion.py`, `reranker.py` |
| W1-11 | ContextBuilder with token budget & truncation | Meet | P0 | DONE | `backend/ai/context/builder.py` |
| W1-12 | Prompt builder & output/grounding validator | Dev | P0 | DONE | `prompt_builder.py`, `validator.py`, `grounding.py` |
| W1-13 | End-to-end RAG pipeline | Meet / Dev | P0 | DONE | `backend/ai/pipeline.py` |
| W1-14 | Repository chat & search APIs | Yug | P0 | DONE | `POST /chat`, `POST /search` |
| W1-15 | React 19 Workbench UI (Fixed Viewport + Panels) | Dhramraj | P0 | DONE | `frontend/src/pages/RepositoryChat.tsx` |
| W1-16 | Security baseline, secret scrubbing & isolation | Sukun | P0 | DONE | `SecretScanner`, multi-tenant isolation tests |
| W1-17 | Comprehensive regression test suite | Keval | P0 | DONE | 369 passed tests, 71.31% code coverage |

---

## WEEK 2 — Developer Intelligence Suite (ACTIVE)

### Week 2 Milestone Goal
Provide four standalone, production-ready developer intelligence capabilities in the Workbench: Code Explanation, Bug Detection, Test Generation, and Standalone AI Code Review.

| Task ID | Task | Owner | Priority | Status | Deliverables |
|---|---|---|---|---|---|
| W2-01 | Shared `IntelligenceContext` interface & token bounding | Meet | P0 | DONE | `build_intelligence_context()`, `TargetSnippet`, caller graph |
| W2-02 | Pydantic output schemas (`CodeExplanation`, `BugFinding`, `TestGen`, `ReviewReport`) | Dev | P0 | IN PROGRESS | `backend/ai/schemas/` models & validation tests |
| W2-03 | Repository Explorer & Drawer UI foundations | Dhramraj | P0 | IN PROGRESS | Source viewer with line numbers & feature action buttons |
| W2-04 | Analysis API routing (`/explain`, `/detect-bugs`, `/generate-tests`, `/review`) | Yug | P0 | IN PROGRESS | Validated request/response schemas & repository auth |
| W2-05 | Analysis run persistence (`analysis_runs`, `code_findings`) | Om | P0 | IN PROGRESS | SQLAlchemy models, Alembic migration & history query |
| W2-06 | GitHub source service (files, commits, PR diffs) | Parth | P0 | IN PROGRESS | Authorized diff provider, revision integrity |
| W2-07 | AST symbol range resolution & import tracking | Prit | P0 | DONE | Exact start/end line mapping for selected symbols, SourceLocationResolver & ImportTracker |
| W2-08 | Static scanner adapter (Ruff, Bandit, secret scanner) | Devu | P0 | IN PROGRESS | Normalized static finding schemas & deduplication |
| W2-09 | Prompt-injection boundaries & secret redaction | Sukun | P0 | IN PROGRESS | Untrusted code boundaries & security test suite |
| W2-10 | QA defect fixtures & acceptance test matrix | Keval | P0 | IN PROGRESS | Fixture repository with known bugs, QA evaluation suite |
| W2-11 | Feature 1: `CodeExplanationService` & pipeline | Dev / Meet | P0 | TODO | Purpose, logic flow, key symbols, data flow, limitations |
| W2-12 | Feature 2: `BugDetectionEngine` (Static + AI) | Dev / Devu | P0 | TODO | Off-by-one, null safety, resource leak, exception analysis |
| W2-13 | Feature 3: `TestGenerationService` | Dev / Prit | P0 | TODO | Framework detection (`pytest`/`unittest`/`jest`), test file generation |
| W2-14 | Feature 4: `AICodeReviewEngine` | Dev / Parth | P0 | TODO | Correctness, security, performance, maintainability diff review |
| W2-15 | Week 2 Integration, Hardening & Acceptance Gate | All | P0 | TODO | Scenarios A–E, zero mock in production, docs update |

---

## WEEK 3 — Workflow Automation, GitHub Ecosystem & PR (UPCOMING)

### Week 3 Milestone Goal
Convert verified developer intelligence into a controlled development workflow: Issue intake -> Task planning -> Human Approval Gate -> Isolated workspace -> Bounded test repair -> Verification -> GitHub Draft PR.

| Task ID | Task | Owner | Priority | Status | Deliverables |
|---|---|---|---|---|---|
| W3-01 | GitHub Issue Intake & Finding-to-Issue Converter (F31) | Parth / Yug | P0 | TODO | Issue import API, issue creation from findings |
| W3-02 | Task Planner & Structured Plan Schema (F32) | Meet / Dev | P0 | TODO | `TaskPlanner`, step dependencies, verification strategy |
| W3-03 | Mandatory Human Approval Gate (F32) | Meet / Dhramraj | P0 | TODO | Server-enforced approval, invalidation on plan revision |
| W3-04 | Isolated Workspace & Task Branch Manager (F33) | Prit / Parth | P0 | TODO | `.workspaces/task-<id>`, `agent/task-<id>` branch |
| W3-05 | Tool Router & Allowed Command Policy Engine (F34) | Devu / Sukun | P0 | TODO | Command allowlist, sandboxed tool dispatch, audit logging |
| W3-06 | Restricted Test Runner & Execution Loop (F35) | Prit / Devu | P0 | TODO | Command execution with timeouts and output bounds |
| W3-07 | Bounded Self-Repair Loop (Max 3 attempts) (F35) | Meet / Dev | P0 | TODO | Failure diagnosis, targeted patch, task-level budget ceiling |
| W3-08 | Independent Verification & Review Engine (F36) | Dev / Keval | P0 | TODO | Separate verification check, static scan, AI code review |
| W3-09 | Authorized Push & GitHub Draft PR Creator (F37) | Parth / Yug | P0 | TODO | Human push authorization, GitHub Draft PR with summary |
| W3-10 | Task Dashboard, Progress & Timeline UI (F38) | Dhramraj | P0 | TODO | Live task progress, timeline events, side-by-side diff |
| W3-11 | Persistence, Checkpoints & Crash Recovery (F39) | Om / Yug | P0 | TODO | Task state recovery, idempotent operations, audit trails |
| W3-12 | Security Attack Matrix & Release Sign-off (F40) | Sukun / Keval | P0 | TODO | Prompt-injection attacks, path traversal, full E2E demo |

---

## Current Team Assignments

| Member | Current Focus | Deliverables |
|---|---|---|
| **Meet** | `IntelligenceContext` & Context Enrichment | Shared context builder, caller resolution, token budgeting |
| **Dev** | Output Schemas & AI Engine Services | Pydantic models for Explanation, Bugs, Tests, and Review |
| **Dhramraj** | Workbench UI & Feature Drawers | Code intelligence panels in fixed-viewport React 19 layout |
| **Yug** | Analysis API Layer & Route Guards | `/explain`, `/detect-bugs`, `/generate-tests`, `/review` routes |
| **Om** | Analysis Persistence & Models | `analysis_runs`, `code_findings` models and migrations |
| **Parth** | Authorized Diff & Commit Provider | Fetching file contents, commit trees, and PR diffs |
| **Prit** | AST Symbol & Line Range Mapper | Resolving functions/classes to exact source line ranges |
| **Devu** | Static Analysis Adapter | Normalizing Ruff, Bandit, and ESLint findings |
| **Sukun** | Prompt-Injection Defenses & Scrubbing | Untrusted data boundary markers, secret scrubbers |
| **Keval** | Quality Fixtures & Regression Testing | Acceptance test suites, fixture codebases with defects |
