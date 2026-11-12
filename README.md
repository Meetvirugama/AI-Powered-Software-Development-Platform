# AI-Powered Software Development Platform

An enterprise-grade, repository-aware developer intelligence and autonomous software development platform. The platform connects deep codebase understanding, AI-assisted developer intelligence, deterministic verification, and human-guided workflow automation into a single traceable engineering system.

---

## 🌟 Key Capabilities

1. **Repository Intelligence (Week 1 — Complete)**:
   - Automated GitHub App integration, shallow cloning, and webhook synchronization.
   - Multilingual AST parsing (via tree-sitter) for Python, TypeScript, JavaScript, Go, Rust, Java, C, and C++.
   - Symbol extraction (functions, classes, methods) and caller-callee dependency graphs.
   - Hybrid RAG retrieval combining pgvector dense cosine search with PostgreSQL full-text lexical search, fused via Reciprocal Rank Fusion (RRF) and Cross-Encoder reranking.
   - Grounded repository chat with file and line-range citations.

2. **Developer Intelligence Suite (Week 2 — Complete)**:
   - **Code Explanation**: Deep context-enriched explanation of files, classes, functions, or custom line ranges.
   - **Bug Detection**: Detection of off-by-one, null safety, resource leaks, and unhandled exceptions harmonizing deterministic static analysis (Ruff/Bandit/ESLint) with grounded AI reasoning.
   - **Test Generation**: Framework-aware test file generation tailored to repository conventions (`pytest`, `unittest`, `jest`).
   - **AI Code Review**: Standalone review of files, commits, and GitHub PR diffs with categorized findings across correctness, security, performance, and reliability.

3. **Workflow Automation & GitHub Ecosystem (Week 3 — Complete)**:
   - Converting GitHub issues or user requirements into structured implementation plans.
   - Mandatory **Human Approval Gate** before code execution.
   - Disposable isolated task workspaces (`.workspaces/task-<id>`) with path traversal guards.
   - Controlled tool router enforcing allowed command templates and sandboxed operations.
   - Bounded self-repair loop (maximum 3 attempts) for failing tests with anti-cycling guards.
   - Independent verification and automated GitHub Draft Pull Request creation with zero credentials leaked.

4. **Enterprise Hardening & Advanced Intelligence (Production Phase — Complete)**:
   - **Timing-Safe Auth & OAuth Hardening (Batch 1 / Issue #181 / PR #202)**: Timing-safe HMAC validation, strict 32-byte secret enforcement, Redis-persisted OAuth state nonces, and refresh token rotation.
   - **Durable GitHub Webhook Ingestion & Automation (Batch 2 / Issue #182 / PR #219)**: State-machine driven background webhook worker queue (`github_webhook_events`), lease-based atomic claiming, push-to-sync automation with commit SHA deduplication, and automated consolidated PR reviews.
   - **Multi-Stage Code Retrieval Engine (Batch 3 / F07 / Issue #187 / PR #220)**: 7-stage retrieval architecture with code-aware lexical search, adaptive HNSW search profiles (40/64/120) with transaction savepoint protection, 1-hop AST symbol graph expansion, Redis retrieval caching with generation-based invalidation, and ONNX cross-encoder evaluation with graceful fallback.
   - **Bounded Agentic Repository Chat (Batch 4 / F08 / Issue #188 / PR #220)**: Normalized LLM tool calling (Gemini & Groq), read-only repository inspection tools (`search_code`, `read_file_range`, `find_symbol_definition`, `find_symbol_references`), strict execution policy, request-level token & timeout budgets, dual-mode chat API, and React UI inspection badges.

---

## 🏗️ Architecture & Technology Stack

```text
Frontend (React 19 + TypeScript + Vite + Tailwind CSS)
                       │
                 HTTP REST / SSE
                       ▼
Backend Gateway (FastAPI + Pydantic v2 + SQLAlchemy 2.0)
     ├── API Layer (/api/v1/auth, /repositories, /chat, /tasks, /github)
     ├── Security & Middleware (Timing-Safe JWT, Rate Limiting, CORS, CSRF)
     └── Worker Subsystem (Sync Worker + Durable Webhook Worker)
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
AI & Retrieval Engine         Repository Scanner & Indexer
  ├── LLM Gateway               ├── FileWalker & LanguageDetector
  │   (Gemini & Groq)           ├── tree-sitter AST Parser
  ├── Agent Orchestrator        ├── Symbol & Edge Extractor
  │   & Tool Registry           ├── SymbolChunker & HNSW Indexer
  ├── Multi-Stage Retrieval     └── Incremental Cache Invalidation
  │   (Adaptive HNSW, Graph,
  │    Lexical FTS, Redis Cache)
  └── ContextBuilder & Verifier
                       │
                 Infrastructure
        ├── PostgreSQL 15 + pgvector (port 5433/5432)
        ├── Redis 7 (port 6379)
        └── GitHub API (GitHub App authentication)
```

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy (asyncio), Alembic, Pydantic v2, Redis, tree-sitter.
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS, Lucide Icons, Zustand.
- **Database**: PostgreSQL 15 with `pgvector` extension for 768-dimensional vector search.
- **AI Models**: Google Gemini (`gemini-flash-lite-latest`) & Groq (`llama-3.3-70b-versatile`) via unified provider gateway.

---

## 🚀 Quick Start (Local Development)

### 1. Prerequisites
- Python 3.11+ (with virtual environment in `.venv`)
- Node.js 20+ and npm
- (Optional) Docker for local PostgreSQL/Redis, or free cloud accounts at [Supabase](https://supabase.com) and [Upstash](https://upstash.com)

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your credentials (API keys, GitHub App, Database & Redis)
```
> [!TIP]
> If you are using Supabase and Upstash (already configured in `.env`), you do **not** need Docker to run locally!

### 3. Run Locally (One Command)
```bash
./run_local.sh
# Or using Make:
make run
```
This automatically applies any pending database migrations and launches:
- **Frontend UI**: [http://localhost:5173](http://localhost:5173)
- **Backend API**: [http://localhost:8000](http://localhost:8000)
- **API Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Readiness Health Check**: [http://localhost:8000/api/v1/health/ready](http://localhost:8000/api/v1/health/ready)

### Alternative: Run Services in Separate Terminals
```bash
# Terminal 1: Backend
.venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Frontend
cd frontend && npm run dev
```

### (Optional) 100% Offline Local Mode with Docker
If you prefer running a local database instead of cloud Supabase/Upstash:
```bash
docker compose up -d
```
Then set in your `.env`:
```env
DATABASE_URL=postgresql+psycopg://platform:platform@localhost:5433/agent_platform
REDIS_URL=redis://localhost:6379/0
```

---

## ☁️ Cloud Deployment (Vercel + Azure + Upstash + Supabase)

See the detailed end-to-end cloud production deployment guide in:
👉 **[`Docs/deployment/cloud_deployment_guide.md`](./Docs/deployment/cloud_deployment_guide.md)**
and template variables in **[`.env.production.example`](./.env.production.example)**.

---

## 🧪 Testing & Verification

### Backend Tests
```bash
cd backend
# Run full test suite with CI coverage gate (>=71%)
../.venv/bin/pytest --cov-fail-under=71

# Run specific test modules
../.venv/bin/pytest tests/test_context_builder.py
../.venv/bin/pytest tests/test_rag_pipeline.py
```
*Current test suite status: **500+ passed**, 0 failed across core, security, adversarial, webhook, and agentic test suites.*

### Frontend Lint, Test & Build
```bash
cd frontend
# Run linter
npm run lint

# Run unit tests
npm test -- --run

# Build production bundle
npm run build
```
*Frontend test status: **329 passed across 27 suites**, 0 TypeScript errors (`tsc -b`), production Vite build passing.*

---

## 📖 Documentation Index

All detailed specifications, architecture diagrams, and milestone plans are maintained in the [`Docs/`](./Docs/README.md) directory:

- [Documentation Master Index](./Docs/README.md)
- [Multi-Stage Code Retrieval Engine](./Docs/retrieval/README.md)
- [Bounded Agentic Repository Chat](./Docs/agentic-chat/README.md)
- [Week 1 — Repository Intelligence Foundation](./Docs/week1.md)
- [Week 2 — Developer Intelligence Suite](./Docs/week2.md)
- [Week 3 — Workflow Automation & GitHub Integration](./Docs/week3.md)
- [Daily Tasks Checklist](./Docs/daily_tasks.md)
- [Database Migrations Guide](./Docs/db_migrations.md)
- [GitHub App Setup Guide](./Docs/github_app_setup.md)
- [Prompt Architecture & Safety](./Docs/prompt_architecture.md)
- [Engineering Architecture Suite](./Docs/engineering/README.md)
- [Week 1 Security Report](./Docs/security/week1_security_report.md)
- [Week 3 Threat Model & Security Report](./Docs/security/week3_security_report.md)

---

## 👥 Engineering Team

- **Meet**: Repository Intelligence, Context Retrieval, Task Planning & Execution Lifecycle
- **Dev**: AI Analysis Engines, Structured Output Schemas & Verification
- **Dhramraj**: Frontend UX, Workbench, Workflow & Timeline Interfaces
- **Yug**: API Gateway, Orchestration & Service Integration
- **Om**: Database Architecture, Alembic Migrations & Persistence
- **Parth**: GitHub Ecosystem, OAuth, Repository Operations & Draft PRs
- **Prit**: AST Parsing, Language Detection & Workspace Isolation
- **Devu**: Static Analysis Integration, Symbol Chunking & Tool Policy
- **Sukun**: Security Architecture, Prompt-Injection Defense & Trust Boundaries
- **Keval**: Quality Assurance, Fixtures & Acceptance Testing Matrix
