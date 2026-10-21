# 02. Requirements Documentation
> **Version:** 3.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-10-15 | **Status:** Live & Synchronized

---

## Functional Requirements

### Authentication & GitHub Integration

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-001 | GitHub OAuth Login | System provides `GET /api/v1/auth/github/login` that redirects user to GitHub OAuth | Developer | P0 | 🟢 Done | Auth API |
| FR-002 | OAuth Callback & JWT | System exchanges OAuth code for token, creates/updates user, returns JWT via httpOnly cookie | Developer | P0 | 🟢 Done | Auth API |
| FR-003 | Current User Info | `GET /api/v1/auth/me` returns authenticated user object from JWT | Developer | P0 | 🟢 Done | Auth API |
| FR-004 | Logout | `POST /api/v1/auth/logout` invalidates session via Redis blocklist | Developer | P0 | 🟢 Done | Auth API |
| FR-005 | GitHub App Installation | System receives installation_id and stores in DB (`github_installations` table) | Developer | P0 | 🟢 Done | GitHub App |
| FR-006 | Installation Token Cache | System caches GitHub installation tokens in Redis with 55-minute TTL | System | P0 | 🟢 Done | TokenManager |

### Repository Management

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-010 | List Repositories | `GET /api/v1/repositories` lists user's accessible repositories | Developer | P0 | 🟢 Done | Repository API |
| FR-011 | Repository Detail | `GET /api/v1/repositories/{id}` returns repository metadata and sync status | Developer | P0 | 🟢 Done | Repository API |
| FR-012 | Repository Sync | System can clone and scan a repository, tracking sync status (`sync_jobs` table) | System | P0 | 🟢 Done | Sync Service |
| FR-013 | File Walking | System traverses repository, skips `.git`, `node_modules`, `venv`, `__pycache__`, `dist`, `build`, `.next`, `.cache` | System | P0 | 🟢 Done | `FileWalker` |
| FR-014 | Gitignore Respect | File walker respects `.gitignore` using `pathspec` | System | P0 | 🟢 Done | `FileWalker` |
| FR-015 | Binary Skip | File walker skips binary files (null byte detection) | System | P0 | 🟢 Done | `FileWalker` |
| FR-016 | File Size Limit | File walker skips files >1 MB | System | P0 | 🟢 Done | `FileWalker` |

### Code Intelligence & AST Parsing

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-020 | AST Symbol Extraction | System parses Python, TS, JS, Java, Go, Rust, C, C++ via `tree-sitter` and extracts functions, classes, methods with line numbers | System | P0 | 🟢 Done | `tree-sitter Parser` |
| FR-021 | Symbol Chunking | System creates chunks from symbols: function/method → `function` type, class → `class` type, module → `module` type | System | P0 | 🟢 Done | `SymbolChunker` |
| FR-022 | Dependency Graph | System builds symbol dependency graph (calls, imports, extends, implements) | System | P0 | 🟢 Done | `DependencyGraph` |
| FR-023 | Language Detection | System detects language per file via extension mapping and shebang detection | System | P0 | 🟢 Done | `LanguageDetector` |
| FR-024 | Test Mapping | System maps source files to existing test files via path conventions | System | P0 | 🟢 Done | `TestMapper` |

### Embeddings & Vector Storage

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-030 | Single Text Embedding | System embeds a single text string via configured provider | System | P0 | 🟢 Done | `EmbeddingService.embed` |
| FR-031 | Batch Embedding | System embeds batches of up to 100 texts per API call with concurrency | System | P0 | 🟢 Done | `EmbeddingService.embed_batch` |
| FR-032 | Dimension Validation | Embedding service validates vector dimensions; mismatches are non-retryable | System | P0 | 🟢 Done | `EmbeddingService` |
| FR-033 | Vector Cosine Search | System queries `code_chunks` via pgvector `<=>` cosine distance, strictly scoped by `repository_id` | System | P0 | 🟢 Done | `VectorRetriever` |
| FR-034 | Lexical Search | System queries `code_chunks` via PostgreSQL FTS `ts_rank`, normalised to [0,1] | System | P0 | 🟢 Done | `LexicalRetriever` |
| FR-035 | RRF Fusion | System combines vector + lexical results via Reciprocal Rank Fusion (k=60) | System | P0 | 🟢 Done | `RRFFusion` |
| FR-036 | Cross-Encoder Rerank | System reranks candidate chunks to top-k using `cross-encoder/ms-marco-MiniLM-L-6-v2` | System | P0 | 🟢 Done | `CrossEncoderReranker` |

### LLM Gateway & Approved Provider Policy

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-040 | Single LLM Entry Point | All LLM calls go through `LLMGateway.generate()` | System | P0 | 🟢 Done | `LLMGateway` |
| FR-041 | Approved Provider Restriction | Strict restriction to Google Gemini (`gemini-flash-lite-latest`) & Groq (`llama-3.3-70b-versatile`) | System | P0 | 🟢 Done | LLM Gateway |
| FR-042 | LLM Retry & Backoff | Provider retries up to 3 times on 429/5xx with exponential backoff | System | P0 | 🟢 Done | Provider Adapters |
| FR-043 | LLM Timeout | Per-request timeout of 30 seconds enforced on all requests | System | P0 | 🟢 Done | Provider Adapters |
| FR-044 | Structured Output | LLM gateway supports JSON mode + Pydantic schema validation | System | P0 | 🟢 Done | AI Schemas |

### AI Output Quality & Grounding

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-050 | Output Validation | `OutputValidator.validate()` parses JSON and validates against Pydantic schema | System | P0 | 🟢 Done | `OutputValidator` |
| FR-051 | Output Repair | `OutputValidator.repair()` asks LLM to fix invalid JSON, max 2 retries | System | P0 | 🟢 Done | `OutputValidator` |
| FR-052 | Grounding Validation | `GroundingValidator` removes hallucinated file and line citations | System | P0 | 🟢 Done | `GroundingValidator` |
| FR-053 | Confidence Downgrade | If >50% of citations are ungrounded, confidence automatically downgrades to "low" | System | P0 | 🟢 Done | `GroundingValidator` |

### Prompts & Context Builder

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-060 | System/Data Separation | Repository content NEVER goes into the system prompt; tagged in user turn | Dev (Policy) | P0 | 🟢 Done | `PromptBuilder` |
| FR-061 | Chat Prompt Build | `PromptBuilder.build_chat_prompt()` returns `[system_msg, user_msg]` | System | P0 | 🟢 Done | `PromptBuilder` |
| FR-062 | Context Assembly | `ContextBuilder.build()` assembles code chunks + memory + conversation history | System | P0 | 🟢 Done | `ContextBuilder` |
| FR-063 | Token Limit Enforcement | Context builder truncates input to stay within token window (tiktoken `cl100k_base`) | System | P0 | 🟢 Done | `ContextBuilder` |
| FR-064 | Memory Continuity | Memory entries deduplicated and sorted by recency (`memory_entries` table) | System | P0 | 🟢 Done | `MemoryRepository` |

### Week 2 — Developer Intelligence Suite (Active)

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-100 | Shared `IntelligenceContext` | Context container with `TargetSnippet`, `SymbolContext`, caller references, and token bounding | System | P0 | 🟢 Done | `ContextBuilder` |
| FR-101 | Code Explanation Service | Explain purpose, logic flow, key symbols, inputs/outputs, dependencies, and limitations | Developer | P0 | 🔵 In Progress | `CodeExplanationService` |
| FR-102 | Dedicated Bug Detection | Detect off-by-one, null safety, unhandled exceptions, and resource leaks with static + AI reasoning | Developer | P0 | 🔵 In Progress | `BugDetectionEngine` |
| FR-103 | Framework-Aware Test Gen | Detect `pytest`, `unittest`, or `jest` and generate executable test files with positive/negative/edge cases | Developer | P0 | 🔵 In Progress | `TestGenerationService` |
| FR-104 | Standalone AI Code Review | Review single file, commit SHA, or GitHub PR diff across Correctness, Security, Performance, and Reliability | Developer | P0 | 🔵 In Progress | `AICodeReviewEngine` |
| FR-105 | Analysis Persistence | Persist analysis runs and categorized findings in `analysis_runs` and `code_findings` | System | P0 | 🔵 In Progress | Om (Models & Migration) |

### Week 3 — Workflow Automation & Production Hardening (Upcoming)

| ID | Requirement | Description | Actor | Priority | Status | Related Feature |
|---|---|---|---|---|---|---|
| FR-110 | GitHub Issue Import & Creation | Import authorized issues or convert approved findings into GitHub issues | Developer | P0 | ⚪ Todo | F31 (Parth) |
| FR-111 | Structured Task Planning | Convert requirements into ordered steps, affected files, tests, and verification strategy | System | P0 | ⚪ Todo | F32 (Meet) |
| FR-112 | Mandatory Human Approval Gate | Explicit human approval required before entering isolated workspace execution | Developer | P0 | ⚪ Todo | F32 (Meet / Dhramraj) |
| FR-113 | Isolated Workspace Management | Disposable `.workspaces/task-<id>` directory with Git worktree and path traversal guards | System | P0 | ⚪ Todo | F33 (Prit) |
| FR-114 | Policy-Guarded Tool Router | Explicit command template allowlist, sanitized argument validation, and audit logging | System | P0 | ⚪ Todo | F34 (Devu / Sukun) |
| FR-115 | Bounded Self-Repair Loop | Re-run tests on failure, apply targeted repairs with hard ceiling of 3 task-level attempts | System | P0 | ⚪ Todo | F35 (Meet / Dev) |
| FR-116 | Independent Verification | Separate verification check evaluating tests, static checks, and AI code review | System | P0 | ⚪ Todo | F36 (Dev) |
| FR-117 | Human Push Authorization & Draft PR | Require explicit publication authorization, push `agent/task-<id>`, and create GitHub Draft PR | Developer | P0 | ⚪ Todo | F37 (Parth) |

---

## Non-Functional Requirements

| ID | Category | Requirement | Priority | Status |
|---|---|---|---|---|
| NFR-001 | Performance | LLM response timeout ≤ 30s per request | P0 | 🟢 Done |
| NFR-002 | Performance | Embedding batch processing ≤ 100 items per API call | P0 | 🟢 Done |
| NFR-003 | Performance | Vector search executed via HNSW index on `code_chunks.embedding` | P0 | 🟢 Done |
| NFR-004 | Security | No secrets committed to source code (`.secrets.baseline` + pre-commit hook) | P0 | 🟢 Done |
| NFR-005 | Security | All configuration loaded from environment variables (`app/core/config.py`) | P0 | 🟢 Done |
| NFR-006 | Security | JWT authentication for all non-health, non-auth endpoints | P0 | 🟢 Done |
| NFR-007 | Security | Multi-tenant repository isolation strictly enforced (`repository_id` filtering) | P0 | 🟢 Done |
| NFR-008 | Security | Repository content treated as untrusted data (prompt-injection defense) | P0 | 🟢 Done |
| NFR-009 | Security | Workspace execution confined to task directory (no host credential escape) | P0 | ⚪ Todo (Week 3) |
| NFR-010 | Scalability | Asynchronous batch processing using `asyncio` across retrieval and embeddings | P0 | 🟢 Done |
| NFR-011 | Scalability | Redis used for session token caching and background sync job queue | P0 | 🟢 Done |
| NFR-012 | Reliability | LLM retries on 429/5xx with exponential backoff (1s, 2s, 4s) | P0 | 🟢 Done |
| NFR-013 | Reliability | Reversible database migrations with `upgrade` and `downgrade` (5 migrations) | P0 | 🟢 Done |
| NFR-014 | Logging | Structured JSON logging with `request_id` context middleware | P0 | 🟢 Done |
| NFR-015 | Usability | Fixed-viewport React 19 Workbench with real-time sync status feedback | P0 | 🟢 Done |
| NFR-016 | Availability | Health check endpoint (`GET /api/v1/health`) returns 200 without DB dependency | P0 | 🟢 Done |
| NFR-017 | Test Quality | Backend test suite must maintain ≥ 70% coverage (currently 71.31%) | P0 | 🟢 Done |
