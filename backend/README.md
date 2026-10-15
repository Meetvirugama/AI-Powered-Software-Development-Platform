# Backend — AI-Powered Software Development Platform

The backend provides the API Gateway, asynchronous workers, AST-based repository parsing, hybrid vector retrieval (pgvector + FTS), and multi-provider LLM orchestration.

**Backend Lead:** Yug | **AI/ML Lead:** Meet | **Database Lead:** Om | **Testing Lead:** Keval

---

## 1. Architecture & Module Map

```text
backend/
├── app/
│   ├── api/v1/          # REST endpoints (auth, repositories, chat)
│   ├── core/            # Configuration, database session, logging, rate limiting
│   ├── models/          # SQLAlchemy ORM models (users, repositories, sync_jobs, etc.)
│   ├── schemas/         # Pydantic validation schemas
│   ├── services/        # Domain business logic (auth, repository sync)
│   ├── repositories/    # Database query layer with repository_id isolation
│   ├── integrations/    # GitHub App client, token manager, Redis queue
│   └── workers/         # Background sync and indexing workers
├── ai/
│   ├── llm/             # LLM Gateway (Gemini, Groq providers, retry, token tracking)
│   ├── embeddings/      # Gemini embedding service with batching (768 dims)
│   ├── retrieval/       # VectorRetriever, LexicalRetriever, RRFFusion, CrossEncoderReranker
│   ├── context/         # ContextBuilder (token budgeting, AgentContext rendering)
│   ├── prompts/         # Cached prompt templates with traversal guards
│   └── schemas/         # Response schemas, error hierarchy, and validators
├── scanner/             # FileWalker, LanguageDetector, tree-sitter AST parser
├── indexer/             # Symbol-aware chunker, content-hash incremental indexer
├── migrations/          # Alembic versioned migration scripts
└── tests/               # Unit and integration tests
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
JWT_SECRET=your-secure-jwt-secret-here
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

### Existing Migrations (5 Total):
1. `24498ac67b3e` — `add_pgvector_extension`
2. `5f6dc031921b` — `identity_schema` (`users`, `github_installations`, `repositories`)
3. `aef3bb17eb34` — `content_tables` (`repository_files`, `code_symbols`, `symbol_edges`)
4. `cb4e2a7d0f31` — `add_sync_jobs` (`sync_jobs`)
5. `e7b8c9d0f1a2` — `add_code_chunks_and_memory` (`code_chunks`, `memory_entries`)

---

## 4. Running the Backend

### Start FastAPI Development Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.

### Start Asynchronous Sync Worker
```bash
python -m app.workers.sync_worker
```

---

## 5. Testing & Quality Assurance

Run the test suite with coverage enforcement ($\ge 70\%$ required):
```bash
pytest --cov=app --cov=ai --cov=scanner --cov=indexer --cov-fail-under=70
```

Current test status:
- **Total Tests:** 369 passed, 1 skipped, 0 failed
- **Line Coverage:** 71.31%
