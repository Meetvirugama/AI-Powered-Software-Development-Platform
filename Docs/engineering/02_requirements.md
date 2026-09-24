# 02. Requirements Documentation
> **Version:** 1.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-24 | **Status:** Draft

---

## Functional Requirements

### Authentication & GitHub Integration

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-001 | GitHub OAuth Login | System provides `GET /api/v1/auth/github/login` that redirects user to GitHub OAuth | Developer | P0 | ⚪ Todo (stub only) | F-01 |
| FR-002 | OAuth Callback & JWT | System exchanges OAuth code for token, creates/updates user, returns JWT via httpOnly cookie | Developer | P0 | ⚪ Todo (stub only) | F-01 |
| FR-003 | Current User Info | `GET /api/v1/auth/me` returns authenticated user object from JWT | Developer | P0 | ⚪ Todo (stub only) | F-01 |
| FR-004 | Logout | `POST /api/v1/auth/logout` invalidates session via Redis blocklist | Developer | P0 | ⚪ Todo | F-01 |
| FR-005 | GitHub App Installation | System receives installation_id and stores in DB | Developer | P0 | ⚪ Todo | F-01 |
| FR-006 | Installation Token Cache | System caches GitHub installation tokens in Redis (55 min TTL) | System | P0 | ⚪ Todo | F-01 |

### Repository Management

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-010 | List Repositories | `GET /api/v1/repositories` lists user's accessible repositories | Developer | P0 | ⚪ Todo (stub only) | F-02 |
| FR-011 | Repository Detail | `GET /api/v1/repositories/{id}` returns repository metadata and sync status | Developer | P0 | ⚪ Todo | F-02 |
| FR-012 | Repository Sync | System can clone and scan a repository, tracking sync status | System | P0 | ⚪ Todo | F-02, F-03 |
| FR-013 | File Walking | System traverses repository, skips `.git`, `node_modules`, `venv`, `__pycache__`, `dist`, `build`, `.next`, `.cache` | System | P0 | 🟢 Done (`FileWalker`) | F-02 |
| FR-014 | Gitignore Respect | File walker respects `.gitignore` using `pathspec` | System | P0 | 🟢 Done | F-02 |
| FR-015 | Binary Skip | File walker skips binary files (null byte detection) | System | P0 | 🟢 Done | F-02 |
| FR-016 | File Size Limit | File walker skips files >1 MB | System | P0 | 🟢 Done | F-02 |

### Code Intelligence

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-020 | AST Symbol Extraction | System parses Python/TS/JS/Java/Go/Rust/C/C++ via tree-sitter and extracts functions, methods, classes with line numbers | System | P0 | ⚪ Todo (tree-sitter installed, parser TBD) | F-02 |
| FR-021 | Symbol Chunking | System creates chunks from symbols: function/method → `function` type, class → `class` type, remaining → `module` type | System | P0 | 🟢 Done (`SymbolChunker`) | F-03 |
| FR-022 | Dependency Graph | System builds symbol dependency graph (calls, imports, extends, implements) | System | P0 | ⚪ Todo (`graph.py` stub) | F-02 |
| FR-023 | Language Detection | System detects language per file | System | P0 | ⚪ Todo (`detector.py` stub) | F-02 |

### Embeddings & Vector Storage

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-030 | Single Text Embedding | System embeds a single text string via OpenAI | System | P0 | 🟢 Done (`EmbeddingService.embed`) | F-04 |
| FR-031 | Batch Embedding | System embeds batches of up to 100 texts per API call, concurrently | System | P0 | 🟢 Done (`EmbeddingService.embed_batch`) | F-04 |
| FR-032 | Dimension Validation | Embedding service validates vector dimensions; mismatches are non-retryable | System | P0 | 🟢 Done | F-04 |
| FR-033 | Vector Cosine Search | System queries `code_chunks` via pgvector `<=>` cosine distance, scoped by `repository_id` | System | P0 | 🟢 Done (`VectorRetriever`) | F-04 |
| FR-034 | Lexical Search | System queries `code_chunks` via PostgreSQL FTS `ts_rank` | System | P0 | 🔵 In Progress (`LexicalRetriever` stub) | F-04 |
| FR-035 | RRF Fusion | System combines vector + lexical results via Reciprocal Rank Fusion (k=60) | System | P0 | 🔵 In Progress (stub, Day 5) | F-04 |
| FR-036 | Cross-Encoder Rerank | System reranks top-30 RRF candidates to top-8 using `cross-encoder/ms-marco-MiniLM-L-6-v2` | System | P0 | 🔵 In Progress (stub, Day 5) | F-04 |

### LLM Gateway

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-040 | Single LLM Entry Point | All LLM calls go through `LLMGateway.generate()` only | System | P0 | 🟢 Done | F-05 |
| FR-041 | LLM Structured Logging | Every LLM call logs: model, input_tokens, output_tokens, latency_ms, success/failure | System | P0 | 🟢 Done | F-05 |
| FR-042 | LLM Retry | Provider retries up to 3 times on 429/5xx with exponential backoff (1s, 2s, 4s) | System | P0 | 🟢 Done (OpenAIProvider) | F-05 |
| FR-043 | LLM Timeout | Per-request timeout of 30 seconds | System | P0 | 🟢 Done | F-05 |
| FR-044 | Structured Output | LLM gateway supports JSON mode + Pydantic schema validation | System | P0 | 🟢 Done | F-05 |

### AI Output Quality

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-050 | Output Validation | `OutputValidator.validate()` parses JSON and validates against Pydantic schema | System | P0 | 🟢 Done | F-04 |
| FR-051 | Output Repair | `OutputValidator.repair()` asks LLM to fix invalid JSON, max 2 retries | System | P0 | 🟢 Done | F-04 |
| FR-052 | Grounding Validation | `GroundingValidator` removes hallucinated file/line citations | System | P0 | 🟢 Done (skeleton; DB query stub for Day 4) | F-04 |
| FR-053 | Confidence Downgrade | If >50% of citations ungrounded, confidence downgrades to "low" | System | P0 | 🟢 Done (logic present) | F-04 |

### Prompts

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-060 | System/Data Separation | Repository content NEVER goes into the system prompt | Dev (Policy) | P0 | 🟢 Done (PromptBuilder enforces) | F-04 |
| FR-061 | Chat Prompt Build | `PromptBuilder.build_chat_prompt()` returns `[system_msg, user_msg]` | System | P0 | 🟢 Done | F-04 |
| FR-062 | Summary Prompt Build | `PromptBuilder.build_summary_prompt()` for large code section summarization | System | P0 | 🟢 Done | F-04 |

### Context Builder

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-070 | Context Assembly | `ContextBuilder.build()` assembles code chunks + memory + conversation history | System | P0 | 🔵 In Progress (stub, Day 6) | F-04 |
| FR-071 | Token Limit Enforcement | Context builder truncates input to stay within LLM context window (default 100k tokens) | System | P0 | 🔵 In Progress | F-04 |
| FR-072 | Memory Deduplication | Memory entries are deduplicated by ID and sorted by recency | System | P0 | 🔵 In Progress | F-07 |

### Agentic System

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-080 | Task Planning | Agent generates step-by-step plan before executing | Developer | P0 | ⚪ Todo | F-06 |
| FR-081 | Human Plan Approval | Agent does NOT execute until developer approves plan | Developer | P0 | ⚪ Todo | F-06 |
| FR-082 | Sandbox Execution | All file changes happen inside isolated container | System | P0 | ⚪ Todo | F-06 |
| FR-083 | Test Generation | Agent generates unit/integration/regression tests | System | P0 | ⚪ Todo | F-06 |
| FR-084 | Self-Verification Loop | Agent runs tests; on failure: diagnose → fix → retry (max 3) | System | P0 | ⚪ Todo | F-06 |
| FR-085 | Independent Verification | Separate LLM call (no shared state with coding agent) checks requirement match | System | P0 | ⚪ Todo | F-06 |
| FR-086 | Draft PR Creation | Agent creates a draft PR on GitHub with test results + review findings | Developer | P0 | ⚪ Todo | F-06 |
| FR-087 | Agent Kill Switch | Developer can stop a running agent immediately | Developer | P0 | ⚪ Todo | F-08 |
| FR-088 | Agent Budget Limits | Enforced: 40 iterations, 15 tool calls/step, 3 test retries, 30 min wall clock, 500k tokens | System | P0 | ⚪ Todo | F-08 |

### Health

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-090 | Health Endpoint | `GET /api/v1/health` returns `{"status":"ok","version":"1.0.0"}` without requiring DB | System | P0 | 🟢 Done | — |

---

## Non-Functional Requirements

| ID | Category | Requirement | Priority | Status |
|---|---|---|---|---|
| NFR-001 | Performance | LLM response time ≤ 30s per request (enforced by timeout) | P0 | 🟢 Done |
| NFR-002 | Performance | Embedding batch processing ≤ 100 items per API call | P0 | 🟢 Done |
| NFR-003 | Performance | Vector search should return results via HNSW index on `code_chunks.embedding` | P0 | ⚪ Todo (index TBD on DB setup) |
| NFR-004 | Security | No secrets in source code (pre-commit detect-secrets hook) | P0 | 🔵 In Progress |
| NFR-005 | Security | All secrets loaded from environment variables | P0 | 🟢 Done (pydantic-settings) |
| NFR-006 | Security | JWT authentication for all non-health, non-auth endpoints | P0 | ⚪ Todo |
| NFR-007 | Security | GitHub webhook signature verification (HMAC) | P0 | ⚪ Todo |
| NFR-008 | Security | Repository content treated as untrusted data (prompt injection prevention) | P0 | 🟢 Done (PromptBuilder) |
| NFR-009 | Security | Agent cannot access host filesystem or credentials | P0 | ⚪ Todo (sandbox) |
| NFR-010 | Scalability | Embedding service uses async batch processing (asyncio.gather) | P0 | 🟢 Done |
| NFR-011 | Scalability | Redis used for session cache and job queue | P0 | 🟢 Done (configured) |
| NFR-012 | Reliability | LLM retries on 429/5xx with exponential backoff | P0 | 🟢 Done |
| NFR-013 | Reliability | Every agent run creates recoverable checkpoints | P0 | ⚪ Todo |
| NFR-014 | Reliability | Database sessions always closed after use (SQLAlchemy generator) | P0 | 🟢 Done |
| NFR-015 | Maintainability | All SQLAlchemy migrations reversible (upgrade + downgrade) | P0 | ⚪ Todo |
| NFR-016 | Maintainability | No raw SQL outside Om's repository layer | P0 | ⚪ Todo (enforced by rule; partially violated in `vector.py` via `text()`) |
| NFR-017 | Logging | Structured JSON logging with request_id middleware | P0 | 🟢 Done |
| NFR-018 | Logging | Every LLM call logged: model, tokens, latency, success/failure | P0 | 🟢 Done |
| NFR-019 | Privacy | Sensitive data redacted before storage in memory | P0 | ⚪ Todo |
| NFR-020 | Usability | Frontend provides real-time sync status feedback | P1 | ⚪ Todo |
| NFR-021 | Data Retention | Agent audit log retained permanently | P0 | ⚪ Todo |
| NFR-022 | Availability | Health endpoint returns 200 without DB dependency | P0 | 🟢 Done |
