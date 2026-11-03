# 00. Project Dashboard
> **Version:** 3.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-10-15 | **Status:** Active

---

## Project Identity

| Field | Value |
|---|---|
| **Project Name** | AI-Powered Software Development Platform |
| **Short Name** | Developer Intelligence Platform |
| **Version** | 1.0.0 |
| **App Env** | development / local |
| **API Prefix** | `/api/v1` |
| **Repo Root** | `AI-Powered-Software-Development-Platform/` |

---

## Current Status

| Metric | Value |
|---|---|
| **Development Phase** | Production Hardened & Acceptance Verified |
| **Current Week/Sprint** | Week 3 (100% Complete) |
| **Week 1 Progress** | 100% COMPLETE (Repository Intelligence, Hybrid RAG, Auth, UI) |
| **Week 2 Progress** | 100% COMPLETE (Developer Intelligence Suite: Explain, Bug, TestGen, Review) |
| **Week 3 Progress** | 100% COMPLETE (Workflow Automation, Approval Gate, Sandbox, Repair, Draft PR) |
| **Current Milestone** | Production Hardening, Audit Fixes & Acceptance Sign-off |
| **Test Suite Health** | 100% passing across backend and frontend test suites |
| **Frontend Health** | 0 lint errors (`oxlint`), production build passing (`tsc -b && vite build`) |

---

## Feature Status Across Milestones

### Week 1 — Repository Intelligence Foundation (100% Done)

| Feature | Owner | Status | Notes |
|---|---|---|---|
| FastAPI Backend Skeleton | Yug | 🟢 Done | `app/main.py`, config, logging, health check |
| Docker Compose (PostgreSQL 15 + Redis 7) | Yug / Om | 🟢 Done | pgvector enabled, volume persistence |
| LLM Gateway (Gemini & Groq) | Meet | 🟢 Done | Google Gemini + Groq provider adapters |
| Embedding Service & Client | Meet | 🟢 Done | Batching, dimension validation, retries |
| Hybrid Retrieval (Vector + Lexical) | Meet | 🟢 Done | pgvector `<=>` cosine + PostgreSQL FTS |
| RRF Fusion & Cross-Encoder Reranker | Meet | 🟢 Done | Reciprocal Rank Fusion + cross-encoder |
| Context Builder & Prompt Assembly | Meet / Dev | 🟢 Done | `tiktoken` budget, truncation, prompt isolation |
| End-to-End RAG Pipeline | Meet | 🟢 Done | 7-step retrieval, grounding & repair loop |
| Grounding Validator | Dev | 🟢 Done | Validates file paths, line ranges, drops hallucinations |
| Tree-sitter Scanner & Language Detector | Prit | 🟢 Done | Multi-language AST parsing & symbol extraction |
| Symbol Chunker & HNSW Indexing | Devu / Om | 🟢 Done | AST-aware chunking, vector & GIN indexes |
| Identity & Auth API | Yug / Parth | 🟢 Done | GitHub OAuth, JWT cookies, user session management |
| Repositories & Sync API | Yug / Parth | 🟢 Done | Clone, file tree, symbol list, Redis sync queue |
| Repository Chat API | Yug / Meet | 🟢 Done | Grounded Q&A with file and line citations |
| React 19 Frontend Workbench | Dhramraj | 🟢 Done | Fixed-viewport layout, repository explorer, chat UI |

### Week 2 — Developer Intelligence Suite (100% Done)

| Feature | Owner | Status | Notes |
|---|---|---|---|
| Shared `IntelligenceContext` & Facade Service | Meet | 🟢 Done | Context enrichment, bug/test/review builders, caching & drift gate |
| Developer Intelligence Schemas | Dev | 🟢 Done | Explanation, BugFinding, TestGen, ReviewReport |
| Workbench Drawers & Action Triggers | Dhramraj | 🟢 Done | Explain, Bug, Test, Review drawer shells |
| Analysis REST Endpoints | Yug | 🟢 Done | `/explain`, `/detect-bugs`, `/generate-tests`, `/review` |
| Analysis Persistence (`analysis_runs`) | Om | 🟢 Done | Run tracking, finding models, revision mapping |
| Authorized Diffs & Source Ingestion | Parth | 🟢 Done | GitHub commit and PR-diff retrieval |
| AST Symbol & Line Range Mapper | Prit | 🟢 Done | Exact line ranges, function/class resolution |
| Static Scanner Adapter | Devu | 🟢 Done | Ruff, Bandit, secret scanner integration |
| Prompt-Injection & Security Defense | Sukun | 🟢 Done | Data tagging, secret scrubbing, auth guards |
| Quality Fixtures & QA Matrix | Keval | 🟢 Done | Defect fixtures, accuracy baselines |

### Week 3 — Workflow Automation & Production Hardening (100% Done)

| Feature | Owner | Status | Notes |
|---|---|---|---|
| GitHub Issue Integration (F31) | Parth | 🟢 Done | Import issue, create issue from finding |
| Task Planner & Human Approval Gate (F32) | Meet | 🟢 Done | Structured plan, explicit approval gate |
| Isolated Workspace & Worktree (F33) | Prit | 🟢 Done | `.workspaces/task-<id>`, path traversal guards |
| Tool Router & Policy Engine (F34) | Devu | 🟢 Done | Command allowlist, sandboxed tool invocation |
| Test Runner & Bounded Repair Loop (F35) | Meet | 🟢 Done | Automated tests, max 3 repair attempts |
| Independent Verification & Review (F36) | Dev | 🟢 Done | Revision check, static + AI review, PR summary |
| Git Push & GitHub Draft PR (F37) | Parth | 🟢 Done | Branch creation, authorized push, Draft PR |
| Task Dashboard & Timeline UI (F38) | Dhramraj | 🟢 Done | Live task progress, approval modal, diff review |
| Persistence & Crash Recovery (F39) | Om | 🟢 Done | Task checkpoints, event history, recovery |
| Security & Release Acceptance (F40) | Sukun / Keval | 🟢 Done | Attack matrix, end-to-end acceptance demo |

---

## Team & Primary Ownership

| Member | Role | Core Responsibility |
|---|---|---|
| **Meet** | Lead Architect / Intelligence Pipelines | RAG, ContextBuilder, Task Planner, Execution Loop |
| **Dev** | AI Engines & Quality Lead | Explanation, Bug Detection, Test Generation, Review Schemas |
| **Dhramraj** | Frontend UX Lead | Workbench, Repository Explorer, Analysis Drawers, Task Timeline |
| **Yug** | Backend / API Lead | FastAPI Gateway, Orchestration, Analysis & Task Endpoints |
| **Om** | Database / Persistence Lead | PostgreSQL + pgvector, Alembic Migrations, Task Persistence |
| **Parth** | GitHub Ecosystem Lead | GitHub App, OAuth, Repository Clone, Branch & PR Automation |
| **Prit** | AST & Workspace Lead | tree-sitter AST, Symbol Extraction, Isolated Workspace |
| **Devu** | Static Analysis & Tool Router Lead | Symbol Chunker, Ruff/Bandit Scanner, Tool Policy Engine |
| **Sukun** | Security Lead | Prompt-Injection Shields, Secret Redaction, Sandbox Policy |
| **Keval** | Quality Assurance Lead | Fixture Suites, End-to-End Acceptance, Test Coverage |

---

## Approved Tech Stack & Policy

- **LLM Provider Policy:** **Google Gemini** (`gemini-flash-lite-latest`) & **Groq** (`llama-3.3-70b-versatile`) **only**. No unauthorized third-party LLMs.
- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (asyncio), Alembic, Pydantic v2, Redis 7.
- **Database:** PostgreSQL 15 + `pgvector` extension.
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS, Zustand, Lucide Icons.
- **Testing:** pytest (asyncio, coverage, respx), oxlint (frontend).
