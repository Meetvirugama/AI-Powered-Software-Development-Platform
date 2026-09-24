# 13. Architecture Decision Records
> **Version:** 1.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-24

---

## ADR-001: Single LLM Gateway Pattern

| Field | Value |
|---|---|
| **Title** | All LLM calls route through a single LLMGateway |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Meet |

**Context:**
Multiple features (chat, agent planner, code review, verification, output repair) all need to call an LLM. Without centralization, each would implement its own retry, logging, and error handling differently.

**Problem:**
How do we ensure consistent retry behavior, structured logging, and token tracking across every LLM call in the system?

**Options Considered:**
1. Each module calls the OpenAI SDK directly
2. Single centralized gateway that all modules use
3. Per-feature LLM wrapper classes

**Decision:**
Option 2 — `LLMGateway` in `backend/ai/llm/client.py` is the single entry point.

**Reason:**
- Consistent logging: model, tokens, latency, success/failure on every call
- Single place to add/modify retry policy
- Providers are injectable → testable without real API keys
- Future provider swap (OpenAI → Anthropic) requires changing only one class

**Trade-offs:**
- Adds an indirection layer
- All callers must depend on `LLMGateway` (enforced by `team_rules.md`)

**Consequences:**
- `team_rules.md` rule: "The LLM Gateway is the ONLY place in the codebase that calls an LLM API."
- `OpenAIProvider` handles retry/timeout; `LLMGateway` handles logging
- Adding new providers requires implementing `LLMProvider` abstract class only

**Related Components:**
[`client.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/llm/client.py), [`provider.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/llm/provider.py), [`openai_provider.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/llm/openai_provider.py)

---

## ADR-002: System/Data Prompt Separation

| Field | Value |
|---|---|
| **Title** | Repository content is always DATA — never in the system prompt |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Dev |

**Context:**
The system processes untrusted repository content (code from user repositories). If this content were placed in the system prompt, it could override the AI's instructions (prompt injection).

**Problem:**
How do we prevent repository content from being used as a prompt injection vector?

**Options Considered:**
1. Place repository content in the system prompt for context
2. Strict separation: system message = instructions only; user message = repository data + question
3. Sanitize repository content before including it anywhere

**Decision:**
Option 2 — `PromptBuilder` enforces: system message = instructions only, user message = `REPOSITORY DATA:` section + question.

**Reason:**
- If an attacker embeds `IGNORE ALL PREVIOUS INSTRUCTIONS` in their repo, the LLM sees it as user data, not as a system command
- Clear audit trail: system prompt never changes at runtime
- Every prompt change is reviewed by Dev before merging

**Trade-offs:**
- Slightly longer prompts (labeled sections)
- Developers must always use `PromptBuilder` — can't build prompts ad-hoc

**Consequences:**
- `team_rules.md` rule: "Repository content is always DATA, never SYSTEM instructions."
- `PromptBuilder.build_chat_prompt()` is the only valid way to build chat prompts
- Prompt template changes require regression tests

**Related Components:**
[`prompt_builder.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/schemas/prompt_builder.py), [`prompt_architecture.md`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/Docs/prompt_architecture.md)

---

## ADR-003: PostgreSQL + pgvector for Vector Storage

| Field | Value |
|---|---|
| **Title** | Use PostgreSQL 15 + pgvector extension for vector similarity search |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Om / Meet |

**Context:**
The RAG pipeline requires fast cosine similarity search over millions of code embeddings (1536 dimensions).

**Problem:**
Which vector store to use: a dedicated vector DB (Pinecone, Weaviate, Qdrant) or extend the existing PostgreSQL database?

**Options Considered:**
1. Dedicated vector database (Pinecone, Qdrant, Weaviate)
2. PostgreSQL + pgvector extension

**Decision:**
Option 2 — PostgreSQL 15 with pgvector.

**Reason:**
- Single database for relational data and vectors — no extra infrastructure
- HNSW index support in pgvector for fast approximate nearest neighbor search
- `repository_id` scoping is enforced at SQL level — no cross-repo leakage
- Simpler operational model — team already uses PostgreSQL

**Trade-offs:**
- Performance ceiling is lower than dedicated vector DB at extreme scale
- pgvector `<=>` operator requires raw SQL (`text()`) since SQLAlchemy ORM doesn't support it cleanly

**Consequences:**
- `code_chunks.embedding` column is `VECTOR(1536)`
- HNSW index created on `embedding` column
- `VectorRetriever` uses `sqlalchemy.text()` with pgvector's `<=>` operator
- Cross-repo leakage prevented by `WHERE repository_id = :repository_id` in all queries

**Related Components:**
[`docker-compose.yml`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/docker-compose.yml), [`vector.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/vector.py)

---

## ADR-004: Hybrid Retrieval — Vector + Lexical + RRF + Reranker

| Field | Value |
|---|---|
| **Title** | Use hybrid retrieval (vector + lexical) with RRF fusion and cross-encoder reranking |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Meet |

**Context:**
Repository-aware chat requires finding the most relevant code chunks for a query. Pure vector search misses exact keyword matches; pure lexical search misses semantic matches.

**Problem:**
How do we maximize retrieval quality for code queries that may be semantic ("where is auth handled?") or lexical ("find all AuthService")?

**Options Considered:**
1. Vector-only search
2. Lexical-only (FTS) search
3. Hybrid: vector + lexical → RRF fusion → cross-encoder rerank

**Decision:**
Option 3 — Full hybrid pipeline:
1. Vector search (top-30) via pgvector
2. Lexical search (top-30) via PostgreSQL FTS
3. RRF fusion (k=60) → merged top-30 unique chunks
4. Cross-encoder rerank → top-8 final chunks for LLM context

**Reason:**
- Vector: handles semantic/conceptual queries
- Lexical: handles exact identifier and keyword searches
- RRF: merges without needing normalized scores from heterogeneous retrievers
- Cross-encoder: more accurate than bi-encoder similarity; runs only on small candidate set (30)

**Trade-offs:**
- More complex pipeline with more failure points
- Cross-encoder adds ~100ms latency (runs locally)
- RRF and reranker are stubs (Day 5 implementation)

**Consequences:**
- Default `top_k=30` for each retriever (RRF input)
- Default `top_n=8` for reranker (LLM context)
- `RRFFusion` uses k=60 constant (do not change without benchmarking)

**Related Components:**
[`vector.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/vector.py), [`lexical.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/lexical.py), [`fusion.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/fusion.py), [`reranker.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/reranker.py)

---

## ADR-005: JWT with httpOnly Cookie (No Bearer Token in Frontend)

| Field | Value |
|---|---|
| **Title** | Store JWT in httpOnly cookie, not localStorage or JS-accessible memory |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Yug / Dhramraj |

**Context:**
After GitHub OAuth, the backend must give the frontend a way to authenticate subsequent requests.

**Problem:**
How should the JWT be stored and transmitted?

**Options Considered:**
1. JWT in `localStorage` (XSS-vulnerable)
2. JWT in JS memory (lost on refresh)
3. JWT in httpOnly cookie (XSS-safe, persistent across tabs)

**Decision:**
Option 3 — httpOnly cookie set by backend. Frontend never reads the raw token.

**Reason:**
- httpOnly cookies are not accessible from JavaScript (XSS protection)
- Browser automatically sends cookie with `credentials: include`
- `useAuthStore.token` field intentionally `null` — the cookie is the token

**Trade-offs:**
- Requires `withCredentials: true` on all Axios requests
- CSRF protection needed if using cookie-based auth (TBD)
- More complex logout (must blocklist JWT in Redis)

**Related Components:**
[`useAuthStore.ts`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/stores/useAuthStore.ts), `backend/app/api/v1/auth.py`

---

## ADR-006: Frontend Framework — Vite + React 19 + TypeScript

| Field | Value |
|---|---|
| **Title** | Use Vite + React 19 + TypeScript for frontend |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Dhramraj |

**Context:**
Team needs a modern, fast frontend framework for the developer dashboard and chat UI.

**Decision:**
Vite + React 19 + TypeScript with:
- Zustand 5 for client state
- TanStack Query 5 for server state  
- Axios for HTTP
- MSW 2 for API mocking during development
- Tailwind CSS 4 for styling

**Reason:**
- Vite: fast HMR, native ESM
- React 19: latest stable with concurrent features
- Zustand: minimal, no boilerplate
- TanStack Query: handles caching, loading, error states for server data
- MSW: enables frontend development before backend endpoints are ready

**Related Components:**
[`package.json`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/package.json), [`App.tsx`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/App.tsx)

---

## ADR-007: Agent Sandbox Isolation

| Field | Value |
|---|---|
| **Title** | All agent code execution runs in isolated Docker containers |
| **Date** | 2026-09-24 |
| **Status** | Proposed |
| **Owner** | Prit |

**Context:**
The agent needs to execute arbitrary code (run tests, write files) without affecting the developer's machine or the live repository.

**Problem:**
How do we safely execute untrusted agent actions?

**Decision:**
Docker-based sandbox (or gVisor for stronger isolation):
- Resource limits: 2 vCPU, 4 GiB RAM, 10 GiB disk, 512 processes
- Network egress: denied by default
- Host filesystem: completely invisible
- Workspace destroyed after task completion/failure/cancellation

**Status:** Proposed — not yet implemented (Week 2).

**Related Components:**
`backend/sandbox/` (not yet created)
