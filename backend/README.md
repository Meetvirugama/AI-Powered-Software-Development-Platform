# Backend — AI-Powered Software Development Platform

The backend provides the API Gateway, asynchronous workers, AST-based repository parsing, hybrid vector retrieval (pgvector + FTS), and multi-provider LLM orchestration.

**Backend Lead:** Yug | **AI/ML Lead:** Meet | **Database Lead:** Om | **Testing Lead:** Keval

---

## 1. Architecture & Module Map

```text
backend/
├── app/
│   ├── api/v1/          # REST endpoints (auth, repositories, chat, tasks, analysis, github)
│   ├── core/            # Configuration, database session, logging, rate limiting, security
│   ├── models/          # SQLAlchemy ORM models (users, repositories, tasks, webhooks, etc.)
│   ├── schemas/         # Pydantic validation schemas
│   ├── services/        # Domain business logic (auth, sync, review, task lifecycle)
│   ├── repositories/    # Database query layer with repository_id isolation
│   ├── integrations/    # GitHub App client, token manager, Redis queue
│   └── workers/         # Background sync worker and durable webhook worker
├── ai/
│   ├── agent/           # Bounded Agentic Chat (orchestrator, tool registry, policy, budget)
│   ├── llm/             # LLM Gateway (Gemini, Groq providers, tool calling, token tracking)
│   ├── embeddings/      # Gemini embedding service with batching (768 dims)
│   ├── retrieval/       # Multi-Stage Retrieval (vector, lexical FTS, RRF, reranker, ONNX, cache, graph)
│   ├── context/         # ContextBuilder (token budgeting, AgentContext rendering)
│   ├── prompts/         # Cached prompt templates with traversal guards
│   └── schemas/         # Response schemas, error hierarchy, and validators
├── sandbox/             # Workspace isolation, diff verification, test runner, command runner
├── scanner/             # FileWalker, LanguageDetector, tree-sitter AST parser
├── indexer/             # Symbol-aware chunker, content-hash incremental indexer
├── migrations/          # 12 Alembic versioned migration scripts
└── tests/               # Unit, integration, security, and adversarial tests
```

---

## 2. Environment Setup

### Prerequisites
- Python 3.11+
- PostgreSQL 15+ with `pgvector`
- Redis 7+

### Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration (`.env`)
Copy `.env.example` to `.env` and configure:
```dotenv
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_platform
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=your-secure-jwt-secret-min-32-chars
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
GITHUB_CLIENT_ID=Iv1.xxx
GITHUB_CLIENT_SECRET=xxx
GITHUB_WEBHOOK_SECRET=xxx
GEMINI_API_KEY=AIzaSy...
GROQ_API_KEY=gsk_...
```

---

## 3. Database Migrations (Alembic)

Run all migrations up to `head`:
```bash
alembic upgrade head
```

### Applied Migrations (12 Total):
1. `24498ac67b3e` — `add_pgvector_extension`
2. `5f6dc031921b` — `identity_schema` (`users`, `github_installations`, `repositories`)
3. `aef3bb17eb34` — `content_tables` (`repository_files`, `code_symbols`, `symbol_edges`)
4. `cb4e2a7d0f31` — `add_sync_jobs` (`sync_jobs`)
5. `e7b8c9d0f1a2` — `add_code_chunks_and_memory` (`code_chunks`, `memory_entries`)
6. `f1c2d3e4b5a6` — `add_analysis_runs_and_findings` (`analysis_runs`, `code_findings`)
7. `b627460d74e0` — `add_pull_requests_table` (`pull_requests`)
8. `b3c4d5e6f7a8` — `add_workflow_automation_tables` (`tasks`, `task_plans`, `workspaces`, etc.)
9. `c94e1f8a2d73` — `add_week3_task_and_issue_tables` (`github_issues`)
10. `d5e6f7a8b9c0` — `fix_constraints_and_add_indexes` (foreign key & index hardening)
11. `e1f2a3b4c5d6` — `add_github_webhook_events_and_repo_automation` (`github_webhook_events`)
12. `e8f9a0b1c2d3` — `add_code_search_text_and_index_generation` (`code_search_text`, active index generation)

---

## 4. Running the Backend

### Start FastAPI Development Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.

### Start Asynchronous Workers
```bash
# Terminal 2: Repository Sync Worker
python -m app.workers.sync_worker

# Terminal 3: Durable GitHub Webhook Worker
python -m app.workers.webhook_worker
```

---

## 5. Testing & Quality Assurance

Run the test suite with coverage enforcement:
```bash
pytest --cov=app --cov=ai --cov=scanner --cov=indexer --cov-fail-under=70
```

Current test status:
- **Total Tests:** 500+ passed across core, security, adversarial, webhook, and agentic suites
- **Alembic Migration Verification:** Verified 100% linear and acyclic with zero schema drift
