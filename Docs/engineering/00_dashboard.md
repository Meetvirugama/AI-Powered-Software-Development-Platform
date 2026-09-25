# 00. Project Dashboard
> **Version:** 1.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-24 | **Status:** Active

---

## Project Identity

| Field | Value |
|---|---|
| **Project Name** | AI-Powered Agentic Software Engineering Platform |
| **Short Name** | Agentic Platform |
| **Version** | 1.0.0 |
| **App Env** | development |
| **API Prefix** | `/api/v1` |
| **Repo Root** | `AI-Powered-Software-Development-Platform/` |

---

## Current Status

| Metric | Value |
|---|---|
| **Development Phase** | Week 1 — Repository Intelligence Foundation |
| **Current Week/Sprint** | Week 1 |
| **Overall Progress** | ~35% of Week 1 complete |
| **Current Milestone** | W1: RAG pipeline + repository-aware chat end-to-end |
| **Upcoming Milestone** | W2: Agentic execution loop |

---

## Task Summary

| Category | Count |
|---|---|
| 🟢 Done | ~15 tasks (skeleton, LLM gateway, embeddings, vector retrieval, validator, prompt builder, walker, chunker) |
| 🔵 In Progress | ~10 tasks (context builder, RRF fusion, reranker, lexical retrieval, auth API) |
| ⚪ Todo | ~30 tasks (agents, sandbox, memory, review engine, CI integration) |
| 🔴 Blocked | TBD |
| 🟡 Review | TBD |
| 🐛 Bugs | TBD |

---

## Feature Status

| Feature | Status |
|---|---|
| FastAPI Backend Skeleton | 🟢 Done |
| Health API | 🟢 Done |
| Docker Compose (PostgreSQL + Redis) | 🟢 Done |
| LLM Gateway (OpenAI) | 🟢 Done |
| Embedding Service (OpenAI) | 🟢 Done |
| Vector Retrieval (pgvector) | 🟢 Done |
| Output Validator | 🟢 Done |
| Prompt Builder | 🟢 Done |
| Grounding Validator | 🟢 Done (skeleton) |
| File Walker (Scanner) | 🟢 Done |
| Symbol Chunker (Indexer) | 🟢 Done |
| Auth API (GitHub OAuth + JWT) | 🔵 In Progress |
| Context Builder | 🔵 In Progress |
| Lexical Retrieval | 🔵 In Progress |
| RRF Fusion | 🔵 In Progress |
| Cross-Encoder Reranker | 🔵 In Progress |
| Frontend (React/Vite) | 🔵 In Progress |
| GitHub Integration | 🔵 In Progress |
| Database Models (SQLAlchemy) | 🔵 In Progress |
| Repository Chat API | ⚪ Todo |
| Agentic System | ⚪ Todo |
| Context Continuity Engine | ⚪ Todo |
| Agent Sandbox | ⚪ Todo |

---

## Team

| Member | Role | Primary Module |
|---|---|---|
| **Meet** | AI/ML + RAG Lead | `backend/ai/` + `backend/agent/orchestrator/` |
| **Yug** | Backend Lead | `backend/app/api/`, `backend/app/core/` |
| **Om** | Database Lead | `backend/app/models/`, `backend/app/repositories/`, migrations |
| **Parth** | GitHub Integration Lead | `backend/app/integrations/github/` |
| **Dhramraj** | Frontend Lead | `frontend/src/` |
| **Prit** | Repository Engine Lead | `backend/scanner/` |
| **Divu** | Indexing Lead | `backend/indexer/`, `backend/agent/tools/` |
| **Dev** | AI Quality Lead | `backend/ai/prompts/`, `backend/ai/schemas/` |
| **Keval** | Testing Lead | `backend/tests/` |
| **Sukun** | Security Lead | `backend/agent/policy/` |

---

## Major Dependencies

| Dependency | Version | Purpose |
|---|---|---|
| FastAPI | ≥0.115 | Backend API framework |
| SQLAlchemy | ≥2.0 | ORM |
| Alembic | ≥1.13 | DB migrations |
| PostgreSQL 15 + pgvector | latest | Primary DB + vector storage |
| Redis 7 | latest | Session cache, job queue |
| OpenAI API | TBD | LLM + embeddings |
| httpx | TBD | Async HTTP client for LLM |
| sentence-transformers | TBD | Cross-encoder reranker |
| tree-sitter | TBD | AST parsing |
| Vite + React 19 | latest | Frontend |
| Zustand | ≥5.0 | Frontend state |
| TanStack Query | ≥5.0 | Server state |

---

## Current Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Cross-module interface breakage | High | team_rules.md interface freeze + PR review |
| LLM API cost overrun | Medium | Token budget enforced in LLMGateway |
| Database schema conflicts | Medium | Only Om creates migrations |
| Embedding dimension mismatch | Medium | EmbeddingService validates dimensions |
| Secrets in codebase | High | pre-commit detect-secrets hook |

---

## Recent Changes

| Date | Change | Author |
|---|---|---|
| 2026-09-24 | LLM Gateway + OpenAI Provider implemented | Meet |
| 2026-09-24 | Embedding Service with batch + retry | Meet |
| 2026-09-24 | Vector Retrieval (pgvector cosine search) | Meet |
| 2026-09-24 | Cross-Encoder Reranker (stub) | Meet |
| 2026-09-24 | RRF Fusion (stub) | Meet |
| 2026-09-24 | OutputValidator + repair loop | Dev |
| 2026-09-24 | PromptBuilder (system/data separation) | Dev |
| 2026-09-24 | GroundingValidator (skeleton) | Dev |
| 2026-09-24 | FileWalker scanner | Prit |
| 2026-09-24 | SymbolChunker indexer | Divu |
| 2026-09-24 | Frontend skeleton (Vite + React + Zustand) | Dhramraj |

---

## Status Legend

```
🟢 Done          — Implemented and merged
🔵 In Progress   — Actively being worked on
🟡 Review        — PR open, under review
🟠 Testing       — Under QA
🔴 Blocked       — Waiting on dependency or blocked by bug
⚪ Todo          — Not yet started
🐛 Bug           — Known defect
```
