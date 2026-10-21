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

2. **Developer Intelligence Suite (Week 2 — Active)**:
   - **Code Explanation**: Deep context-enriched explanation of files, classes, functions, or custom line ranges.
   - **Bug Detection**: Detection of off-by-one, null safety, resource leaks, and unhandled exceptions harmonizing deterministic static analysis (Ruff/Bandit/ESLint) with grounded AI reasoning.
   - **Test Generation**: Framework-aware test file generation tailored to repository conventions (`pytest`, `unittest`, `jest`).
   - **AI Code Review**: Standalone review of files, commits, and GitHub PR diffs with categorized findings across correctness, security, performance, and reliability.

3. **Workflow Automation & GitHub Ecosystem (Week 3 — Upcoming)**:
   - Converting GitHub issues or user requirements into structured implementation plans.
   - Mandatory **Human Approval Gate** before code execution.
   - Disposable isolated task workspaces (`agent/task-<id>`) with path traversal guards.
   - Controlled tool router enforcing allowed command templates and sandboxed operations.
   - Bounded self-repair loop (maximum 3 attempts) for failing tests.
   - Independent verification and automated GitHub Draft Pull Request creation.

---

## 🏗️ Architecture & Technology Stack

```text
Frontend (React 19 + TypeScript + Vite + Tailwind CSS)
                       │
                 HTTP REST / SSE
                       ▼
Backend Gateway (FastAPI + Pydantic v2 + SQLAlchemy 2.0)
     ├── API Layer (/api/v1/auth, /repositories, /chat)
     ├── Security & Middleware (JWT, Rate Limiting, CORS, CSRF)
     └── Worker Subsystem (Redis Queue + Background Sync Worker)
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
AI & Retrieval Engine         Repository Scanner & Indexer
  ├── LLM Gateway               ├── FileWalker & LanguageDetector
  │   (Gemini & Groq)           ├── tree-sitter AST Parser
  ├── Embedding Service         ├── Symbol & Edge Extractor
  ├── Hybrid Vector/Lexical RAG └── SymbolChunker & HNSW Indexer
  └── ContextBuilder
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

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.11+
- Node.js 18+ and npm
- Docker and Docker Compose

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your Google Gemini / Groq API keys and GitHub App credentials
```

### 3. Start Infrastructure Services
```bash
docker compose up -d
```
This spins up PostgreSQL 15 (with `pgvector`) and Redis 7.

### 4. Run Backend
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Run database migrations
cd backend
alembic upgrade head

# Start API server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
- API Health check: `http://127.0.0.1:8000/api/v1/health`
- Interactive OpenAPI docs: `http://127.0.0.1:8000/docs`

### 5. Run Frontend
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.

---

## 🧪 Testing & Verification

### Backend Tests
```bash
cd backend
# Run full test suite with coverage
../.venv/bin/pytest --cov-fail-under=70

# Run specific test modules
../.venv/bin/pytest tests/test_context_builder.py
../.venv/bin/pytest tests/test_rag_pipeline.py
```
*Current test suite status: **369 passed**, 1 skipped, 0 failed (71.31% code coverage).*

### Frontend Lint & Build
```bash
cd frontend
# Run linter
npm run lint

# Build production bundle
npm run build
```

---

## 📖 Documentation Index

All detailed specifications, architecture diagrams, and milestone plans are maintained in the [`Docs/`](./Docs/README.md) directory:

- [Documentation Master Index](./Docs/README.md)
- [Week 1 — Repository Intelligence Foundation](./Docs/week1.md)
- [Week 2 — Developer Intelligence Suite](./Docs/week2.md)
- [Week 3 — Workflow Automation & GitHub Integration](./Docs/week3.md)
- [Daily Tasks Checklist](./Docs/daily_tasks.md)
- [Database Migrations Guide](./Docs/db_migrations.md)
- [GitHub App Setup Guide](./Docs/github_app_setup.md)
- [Prompt Architecture & Safety](./Docs/prompt_architecture.md)
- [Engineering Architecture Suite](./Docs/engineering/README.md)
- [Week 1 Security Report](./Docs/security/week1_security_report.md)

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
