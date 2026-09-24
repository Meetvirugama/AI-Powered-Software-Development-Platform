# 05. System Architecture
> **Version:** 1.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-24 | **Status:** Draft

---

## High-Level Architecture

```mermaid
flowchart TD
    subgraph Client["Frontend (Vite + React 19)"]
        UI[Pages: Login / Dashboard / Repositories / RepositoryChat]
        Stores[Zustand Stores: AuthStore / RepositoryStore]
        API_Client[Axios API Client]
    end

    subgraph Backend["Backend (FastAPI)"]
        Router[API Router /api/v1]
        Auth_API[Auth API\n/auth/*]
        Health_API[Health API\n/health]
        Repo_API[Repositories API\n/repositories/*]
        Chat_API[Chat API\n/chat/*]
        Middleware[RequestIdMiddleware\nStructured Logging]
    end

    subgraph AI_Layer["AI Pipeline (backend/ai/)"]
        LLM_GW[LLM Gateway\nclient.py]
        OpenAI_P[OpenAI Provider\nopenai_provider.py]
        Embed_SVC[Embedding Service\nservice.py]
        Vec_RET[Vector Retriever\nvector.py]
        Lex_RET[Lexical Retriever\nlexical.py]
        RRF[RRF Fusion\nfusion.py]
        Reranker[Cross-Encoder Reranker\nreranker.py]
        CTX_B[Context Builder\nbuilder.py]
        Prompt_B[Prompt Builder\nprompt_builder.py]
        Out_Val[Output Validator\nvalidator.py]
        Ground_Val[Grounding Validator\ngrounding.py]
    end

    subgraph Scanner["Repository Engine (backend/scanner/)"]
        Walker[FileWalker\nwalker.py]
        Detector[LanguageDetector\ndetector.py]
        Parser[tree-sitter Parser\nparser.py]
        Symbols[Symbol Extractor\nsymbols.py]
        Graph[Dependency Graph\ngraph.py]
    end

    subgraph Indexer["Indexer (backend/indexer/)"]
        Chunker[SymbolChunker\nchunker.py]
    end

    subgraph Infra["Infrastructure"]
        PG[(PostgreSQL 15\n+ pgvector)]
        Redis[(Redis 7)]
        GitHub_API[GitHub API]
    end

    Client --> Backend
    Backend --> AI_Layer
    Backend --> Scanner
    Backend --> Indexer
    AI_Layer --> Infra
    Backend --> Infra
    Scanner --> Indexer
    Backend --> GitHub_API
```

---

## Backend Module Ownership

| Module | Path | Owner | Status |
|---|---|---|---|
| API Router | `backend/app/api/v1/` | Yug | 🟢 Skeleton done |
| Core Config | `backend/app/core/config.py` | Yug | 🟢 Done |
| Core Database | `backend/app/core/database.py` | Yug | 🟢 Done |
| Core Logging | `backend/app/core/logging.py` | Yug | 🟢 Done |
| App Models | `backend/app/models/` | Om | ⚪ Todo |
| App Repositories | `backend/app/repositories/` | Om | ⚪ Todo |
| App Schemas | `backend/app/schemas/` | Yug + Dev | 🟢 Partial |
| App Services | `backend/app/services/` | Module owners | ⚪ Todo |
| GitHub Integration | `backend/app/integrations/github/` | Parth | ⚪ Todo |
| Workers | `backend/app/workers/` | Yug | ⚪ Todo |
| LLM Gateway | `backend/ai/llm/` | Meet | 🟢 Done |
| Embedding Service | `backend/ai/embeddings/` | Meet | 🟢 Done |
| Vector Retriever | `backend/ai/retrieval/vector.py` | Meet | 🟢 Done |
| Lexical Retriever | `backend/ai/retrieval/lexical.py` | Meet | 🔵 Stub |
| RRF Fusion | `backend/ai/retrieval/fusion.py` | Meet | 🔵 Stub |
| Cross-Encoder Reranker | `backend/ai/retrieval/reranker.py` | Meet | 🔵 Stub |
| Context Builder | `backend/ai/context/builder.py` | Meet | 🔵 Stub |
| Prompt Builder | `backend/ai/schemas/prompt_builder.py` | Dev | 🟢 Done |
| Output Validator | `backend/ai/schemas/validator.py` | Dev | 🟢 Done |
| Grounding Validator | `backend/ai/schemas/grounding.py` | Dev | 🟢 Skeleton |
| Output Schemas | `backend/ai/schemas/output.py` | Dev | 🟢 Done |
| Prompts | `backend/ai/prompts/` | Dev | 🟢 Files exist |
| Scanner | `backend/scanner/` | Prit | 🔵 Walker done |
| Indexer | `backend/indexer/` | Divu | 🟢 Chunker done |
| Agent (future) | `backend/agent/` | Multiple | ⚪ Todo |
| Tests | `backend/tests/` | Keval | 🔵 In Progress |

---

## Component Data Flow: RAG Pipeline

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant ChatAPI as Chat API
    participant EmbSvc as EmbeddingService
    participant VecRet as VectorRetriever
    participant LexRet as LexicalRetriever
    participant RRF as RRFFusion
    participant Rerank as CrossEncoderReranker
    participant CtxB as ContextBuilder
    participant PB as PromptBuilder
    participant LLM as LLMGateway
    participant GV as GroundingValidator

    Dev->>ChatAPI: POST /chat (question, repository_id)
    ChatAPI->>EmbSvc: embed(question)
    EmbSvc-->>ChatAPI: query_vector

    par Vector Search
        ChatAPI->>VecRet: retrieve(query, repo_id, top_k=30)
        VecRet-->>ChatAPI: list[CodeChunk] (cosine sim)
    and Lexical Search
        ChatAPI->>LexRet: retrieve(query, repo_id, top_k=30)
        LexRet-->>ChatAPI: list[CodeChunk] (ts_rank)
    end

    ChatAPI->>RRF: fuse(vector_chunks, lexical_chunks)
    RRF-->>ChatAPI: list[CodeChunk] (RRF score, top-30)

    ChatAPI->>Rerank: rerank(query, chunks, top_n=8)
    Rerank-->>ChatAPI: list[CodeChunk] (top-8)

    ChatAPI->>CtxB: build(chunks, memory, history)
    CtxB-->>ChatAPI: AgentContext

    ChatAPI->>PB: build_chat_prompt(context, question)
    PB-->>ChatAPI: [system_msg, user_msg]

    ChatAPI->>LLM: generate(LLMRequest)
    LLM-->>ChatAPI: LLMResponse

    ChatAPI->>GV: validate_sources(answer, repo_id)
    GV-->>ChatAPI: RepositoryAnswer (hallucinations removed)

    ChatAPI-->>Dev: RepositoryAnswer (answer, sources, confidence)
```

---

## Deployment Architecture (Current)

```mermaid
flowchart TD
    Dev[Developer Browser] --> FE[Frontend\nVite Dev Server\nlocalhost:5173]
    Dev --> BE[Backend\nuvicorn\nlocalhost:8000]
    BE --> PG[(PostgreSQL 15 + pgvector\nDocker\nlocalhost:5432)]
    BE --> Redis[(Redis 7\nDocker\nlocalhost:6379)]
    BE --> OAI[OpenAI API\nhttps://api.openai.com]
    BE --> GH[GitHub API\nhttps://api.github.com]
```

**Current environment:** Local development only.

**Docker Compose services:**
- `postgres`: `pgvector/pgvector:pg15`, port 5432, volume `postgres_data`
- `redis`: `redis:7-alpine`, port 6379, volume `redis_data`

**Backend startup:** `uvicorn app.main:app --reload` from `backend/`

**Config source:** `pydantic-settings` reads from `.env` file at project root.

---

## Key Architectural Rules

1. **LLM Gateway is the ONLY entry point** for LLM calls. No module imports the LLM SDK directly. Source: `team_rules.md`
2. **Repository content is DATA, never SYSTEM instructions.** Prompt injection prevention. Source: `prompt_architecture.md`
3. **Repository queries must filter by `repository_id`.** No cross-repository data leakage. Source: `vector.py` comment.
4. **Raw SQL only inside Om's repository layer** (exception: `VectorRetriever` uses `text()` for pgvector's `<=>` operator).
5. **Every migration must be reversible.** Source: `team_rules.md`
6. **Agents can only read production; writes happen in sandboxes.** Source: `project_idea.md`
7. **Nothing reaches GitHub without two human approvals** (plan approval + push approval). Source: `project_idea.md`
