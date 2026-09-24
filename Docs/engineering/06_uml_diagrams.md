# 06. UML Diagrams
> **Version:** 1.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-24

---

## Diagram Registry

| Diagram | Type | Status | Last Updated |
|---|---|---|---|
| Use Case Diagram | Use Case | ✓ Current | 2026-09-24 |
| Activity: RAG Pipeline | Activity | ✓ Current | 2026-09-24 |
| Activity: Agentic Loop | Activity | ✓ Based on design | 2026-09-24 |
| Class Diagram (AI Layer) | Class | ✓ Current | 2026-09-24 |
| Class Diagram (App Layer) | Class | Partial (stubs) | 2026-09-24 |
| Sequence: LLM Gateway Call | Sequence | ✓ Current | 2026-09-24 |
| Sequence: Repository Chat | Sequence | ✓ Current | 2026-09-24 |
| State: Agent Execution | State | Based on design | 2026-09-24 |
| State: Repository Sync | State | Based on design | 2026-09-24 |
| Component Diagram | Component | ✓ Current | 2026-09-24 |

---

## 6.1 Use Case Diagram

**Purpose:** Shows what each actor can do with the platform.
**Source:** `project_idea.md`, `team_rules.md`, `App.tsx`

```mermaid
graph LR
    Dev(Developer)
    SYS(System)

    subgraph Auth["Authentication"]
        UC1[Login via GitHub OAuth]
        UC2[View Profile]
        UC3[Logout]
    end

    subgraph Repos["Repository Management"]
        UC4[List Repositories]
        UC5[View Repository Detail]
        UC6[Trigger Repository Sync]
    end

    subgraph Chat["Repository Chat"]
        UC7[Ask Question About Codebase]
        UC8[View Grounded Answer with Sources]
    end

    subgraph Agent["Agentic Tasks"]
        UC9[Submit Natural Language Task]
        UC10[Review Agent Plan]
        UC11[Approve Plan]
        UC12[Cancel Agent]
        UC13[View Agent Activity Timeline]
        UC14[Approve Push to GitHub]
        UC15[Review Draft PR]
    end

    subgraph Memory["Memory"]
        UC16[View Project Memory]
        UC17[Edit Memory Entry]
        UC18[Delete Memory Entry]
    end

    Dev --> UC1
    Dev --> UC2
    Dev --> UC3
    Dev --> UC4
    Dev --> UC5
    Dev --> UC6
    Dev --> UC7
    Dev --> UC8
    Dev --> UC9
    Dev --> UC10
    Dev --> UC11
    Dev --> UC12
    Dev --> UC13
    Dev --> UC14
    Dev --> UC15
    Dev --> UC16
    Dev --> UC17
    Dev --> UC18

    SYS --> UC7
    SYS --> UC8
```

---

## 6.2 Activity Diagram: RAG Pipeline

**Purpose:** Shows the exact retrieval flow for repository-aware chat.
**Source:** `backend/ai/retrieval/`, `backend/ai/context/`, `backend/ai/llm/`

```mermaid
flowchart TD
    START([Developer submits question]) --> EMBED[EmbeddingService.embed\nquery → vector]
    EMBED --> PAR{Parallel retrieval}
    PAR --> VEC[VectorRetriever.retrieve\npgvector cosine search\ntop_k=30]
    PAR --> LEX[LexicalRetriever.retrieve\nPostgreSQL FTS ts_rank\ntop_k=30]
    VEC --> RRF[RRFFusion.fuse\nRRF k=60\nMerge + deduplicate → top-30]
    LEX --> RRF
    RRF --> RERANK[CrossEncoderReranker.rerank\ncross-encoder/ms-marco-MiniLM-L-6-v2\ntop-8 selected]
    RERANK --> CTX[ContextBuilder.build\nAssemble: chunks + memory + history\nEnforce 100k token limit]
    CTX --> PROMPT[PromptBuilder.build_chat_prompt\nSystem message: instructions only\nUser message: REPOSITORY DATA + question]
    PROMPT --> LLM[LLMGateway.generate\nOpenAI gpt-4o\nJSON mode if schema provided]
    LLM --> VALID{OutputValidator.validate\nParse JSON + Pydantic validate}
    VALID -- fail --> REPAIR[OutputValidator.repair\nAsk LLM to fix JSON\nMax 2 retries]
    REPAIR --> VALID2{Valid?}
    VALID2 -- no --> ERR([Raise LLMValidationError])
    VALID2 -- yes --> GROUND
    VALID -- pass --> GROUND[GroundingValidator.validate_sources\nCheck file + line existence in DB]
    GROUND --> CONF{>50% ungrounded?}
    CONF -- yes --> DOWNGRADE[Downgrade confidence to 'low']
    CONF -- no --> RETURN
    DOWNGRADE --> RETURN([Return RepositoryAnswer\nanswer + grounded sources + confidence])
```

---

## 6.3 Activity Diagram: Agentic Task Execution Loop

**Purpose:** Full agent lifecycle from task submission to memory storage.
**Source:** `project_idea.md` section 5 & 6

```mermaid
flowchart TD
    TASK([Developer submits task]) --> UNDERSTAND[Parse task\nnatural language or GitHub issue]
    UNDERSTAND --> CTX[Load project context\nRAG + memory + rules + history]
    CTX --> PLAN[Generate step-by-step plan\nidentify files, tools, tests per step]
    PLAN --> APPROVAL{Human approves plan?}
    APPROVAL -- reject --> END1([Task cancelled])
    APPROVAL -- approve --> EXEC[Execute in isolated sandbox\nDocker container]
    EXEC --> GEN_TESTS[Generate + update tests]
    GEN_TESTS --> RUN_TESTS[Run tests in sandbox]
    RUN_TESTS --> TEST_RESULT{Tests pass?}
    TEST_RESULT -- fail / retry < 3 --> DIAGNOSE[Diagnose failure\nIdentify root cause\nGenerate fix]
    DIAGNOSE --> EXEC
    TEST_RESULT -- fail / retry = 3 --> PAUSE([Pause agent\nNotify developer])
    TEST_RESULT -- pass --> VERIFY[Independent Verifier\nSeparate LLM call\nCheck: requirement match, test coverage]
    VERIFY --> REVIEW[Code Review Engine\nStatic + LLM review\nBlast radius analysis]
    REVIEW --> PUSH_GATE{Human approves push?}
    PUSH_GATE -- reject --> END2([Discard sandbox changes])
    PUSH_GATE -- approve --> PR[Create draft PR on GitHub\nWith: diff, test results, review findings]
    PR --> HR{Human reviews PR on GitHub}
    HR --> MEM[Memory Extraction\nStore: decisions, failures, outcomes]
    MEM --> AUDIT[Audit Log\nComplete traceability chain]
    AUDIT --> END3([Task complete])
```

---

## 6.4 Class Diagram: AI Layer

**Purpose:** Shows actual classes and their relationships in `backend/ai/`.
**Source:** Direct reading of source files.

```mermaid
classDiagram
    class LLMProvider {
        <<abstract>>
        +provider_name() str
        +generate(request: LLMRequest) LLMResponse
    }

    class OpenAIProvider {
        -_api_key: str
        -_timeout: float
        -_chat_url: str
        +provider_name() str
        +generate(request: LLMRequest) LLMResponse
        -_build_payload(request) dict
        -_parse_response(data, latency_ms, request) LLMResponse
        -_validate_structured_output(content, schema)
    }

    class LLMGateway {
        -_provider: LLMProvider
        +generate(request: LLMRequest) LLMResponse
    }

    class LLMRequest {
        +model: str
        +messages: list~Message~
        +temperature: float
        +max_tokens: int
        +response_schema: type~BaseModel~ | None
    }

    class LLMResponse {
        +content: str
        +model: str
        +input_tokens: int
        +output_tokens: int
        +latency_ms: float
    }

    class Message {
        +role: "system" | "user" | "assistant"
        +content: str
    }

    class LLMError {
        +retryable: bool
    }
    class LLMTimeoutError
    class LLMRateLimitError
    class LLMUnavailableError
    class LLMValidationError

    class EmbeddingProvider {
        <<abstract>>
        +provider_name() str
        +embedding_dimensions() int
        +embed(text: str) list~float~
        +embed_batch(texts: list~str~) list~list~float~~
    }

    class EmbeddingService {
        -_provider: EmbeddingProvider
        +embed(text: str) list~float~
        +embed_batch(texts: list~str~) list~list~float~~
        -_validate_dimensions(vector)
    }

    class Retriever {
        <<abstract>>
        +retrieve(query, repository_id, top_k) list~CodeChunk~
    }

    class VectorRetriever {
        -_db: AsyncSession
        -_embedding_service: EmbeddingService
        +retrieve(query, repository_id, top_k) list~CodeChunk~
    }

    class LexicalRetriever {
        +retrieve(query, repository_id, top_k) list~CodeChunk~
    }

    class CodeChunk {
        +id: UUID
        +repository_id: UUID
        +file_id: UUID
        +symbol_id: UUID | None
        +content: str
        +token_count: int
        +start_line: int
        +end_line: int
        +content_hash: str
        +score: float
        +file_path: str
    }

    class RRFFusion {
        +fuse(*result_lists, k) list~CodeChunk~
    }

    class CrossEncoderReranker {
        -_model_name: str
        +rerank(query, candidates, top_n) list~CodeChunk~
    }

    class ContextBuilder {
        -_max_tokens: int
        +build(chunks, memory, history, related_files) AgentContext
    }

    class AgentContext {
        +code_chunks: list~CodeChunk~
        +memory_chunks: list~MemoryEntry~
        +related_files: list~RepositoryFile~
        +recent_history: list~ChatMessage~
        +total_tokens: int
    }

    class PromptBuilder {
        +build_chat_prompt(context, question) list~Message~
        +build_summary_prompt(file_path, start_line, end_line, code_content) list~Message~
    }

    class OutputValidator {
        -_gateway: LLMGateway | None
        +validate(raw, schema) tuple~BaseModel|None, bool~
        +repair(raw, schema, error) BaseModel
    }

    class GroundingValidator {
        -_db: object | None
        +validate_sources(answer, repository_id) RepositoryAnswer
        -_check_source(source, repository_id) GroundingResult
    }

    class RepositoryAnswer {
        +answer: str
        +sources: list~SourceReference~
        +confidence: "high"|"medium"|"low"
    }

    class SourceReference {
        +file: str
        +start_line: int
        +end_line: int
        +symbol: str | None
        +line_range() str
    }

    LLMProvider <|-- OpenAIProvider
    LLMGateway --> LLMProvider
    LLMRequest --> Message
    LLMError <|-- LLMTimeoutError
    LLMError <|-- LLMRateLimitError
    LLMError <|-- LLMUnavailableError
    LLMError <|-- LLMValidationError
    EmbeddingService --> EmbeddingProvider
    Retriever <|-- VectorRetriever
    Retriever <|-- LexicalRetriever
    VectorRetriever --> EmbeddingService
    VectorRetriever --> CodeChunk
    RRFFusion --> CodeChunk
    CrossEncoderReranker --> CodeChunk
    ContextBuilder --> AgentContext
    OutputValidator --> LLMGateway
    GroundingValidator --> RepositoryAnswer
    RepositoryAnswer --> SourceReference
```

---

## 6.5 Class Diagram: Scanner & Indexer

**Purpose:** Classes in `backend/scanner/` and `backend/indexer/`.
**Source:** Direct reading of source files.

```mermaid
classDiagram
    class FileInfo {
        +path: str
        +size_bytes: int
        +language: str
        +is_binary: bool
    }

    class FileWalker {
        -MAX_FILE_SIZE_BYTES: int = 1048576
        -SKIP_DIRS: set
        +walk(root_path: str) list~FileInfo~
        -_is_binary(filepath: str) bool
    }

    class Chunk {
        +repository_id
        +file_id
        +symbol_id
        +content: str
        +start_line: int
        +end_line: int
        +language: str
        +chunk_type: str
        +token_count: int
        +content_hash: str
        +metadata: dict
    }

    class SymbolChunker {
        +chunk_symbols(repository_id, file_id, symbols, content, language) list~Chunk~
    }

    FileWalker --> FileInfo
    SymbolChunker --> Chunk
```

---

## 6.6 Sequence Diagram: LLM Gateway Call

**Purpose:** Shows internal flow through LLMGateway and OpenAIProvider.
**Source:** `backend/ai/llm/client.py`, `backend/ai/llm/openai_provider.py`

```mermaid
sequenceDiagram
    participant Caller as Any Module
    participant GW as LLMGateway
    participant Provider as OpenAIProvider
    participant OpenAI as OpenAI API
    participant Logger as Logger

    Caller->>GW: generate(request: LLMRequest)
    GW->>GW: start timer
    GW->>Provider: generate(request)

    loop Retry (max 3 times)
        Provider->>OpenAI: POST /v1/chat/completions
        alt HTTP 200
            OpenAI-->>Provider: response JSON
            Provider->>Provider: _parse_response()
            Note over Provider: If response_schema set → validate JSON against Pydantic schema
            Provider-->>GW: LLMResponse
        else HTTP 429 / 5xx
            OpenAI-->>Provider: error
            Provider->>Provider: sleep(exponential backoff)
        else Timeout
            Provider->>Provider: catch TimeoutException
        end
    end

    alt Success
        GW->>GW: success = True
        GW->>Logger: log(model, tokens, latency, success=True)
        GW-->>Caller: LLMResponse
    else Failure
        GW->>Logger: log(model, None, latency, success=False, error_type)
        GW-->>Caller: raise LLMError
    end
```

---

## 6.7 State Diagram: Agent Execution

**Purpose:** Agent FSM states.
**Source:** `project_idea.md` section 6 (agent responsibilities)

> [!NOTE]
> Agent FSM is not yet implemented. States are derived from design documentation.

```mermaid
stateDiagram-v2
    [*] --> IDLE
    IDLE --> UNDERSTANDING : task submitted
    UNDERSTANDING --> CONTEXTUALIZING : task parsed
    CONTEXTUALIZING --> PLANNING : context loaded
    PLANNING --> AWAITING_APPROVAL : plan generated
    AWAITING_APPROVAL --> EXECUTING : human approves
    AWAITING_APPROVAL --> CANCELLED : human rejects
    EXECUTING --> TESTING : changes complete
    TESTING --> EXECUTING : test fails, retry < 3
    TESTING --> PAUSED : test fails, retry = 3
    TESTING --> VERIFYING : tests pass
    VERIFYING --> REVIEWING : verification complete
    REVIEWING --> AWAITING_PUSH_APPROVAL : review complete
    AWAITING_PUSH_APPROVAL --> PUSHING : human approves push
    AWAITING_PUSH_APPROVAL --> CANCELLED : human rejects
    PUSHING --> COMPLETED : PR created
    PAUSED --> EXECUTING : human resumes
    PAUSED --> CANCELLED : human cancels
    COMPLETED --> [*]
    CANCELLED --> [*]
```

---

## 6.8 State Diagram: Repository Sync

**Purpose:** Sync status of a repository.
**Source:** `Docs/daily_tasks.md` (Om Day 2 — SyncStatus enum)

```mermaid
stateDiagram-v2
    [*] --> NOT_SYNCED : repository added
    NOT_SYNCED --> SYNCING : sync triggered
    SYNCING --> SYNCED : scan + index complete
    SYNCING --> FAILED : error during sync
    FAILED --> SYNCING : retry triggered
    SYNCED --> SYNCING : re-sync triggered
```

---

## 6.9 Component Diagram

**Purpose:** Major system components and their relationships.
**Source:** Directory structure + team_rules.md

```mermaid
graph TB
    subgraph FE["Frontend"]
        Pages[Pages]
        Stores[Zustand Stores]
        APIClient[API Client\nAxios]
    end

    subgraph BE["Backend App"]
        Router[FastAPI Router]
        Config[Config / Settings]
        DB_Session[DB Session]
        Logging[Structured Logging]
    end

    subgraph AI["AI Pipeline"]
        LLM[LLM Gateway]
        Embed[Embedding Service]
        Retrieval[Retrieval Pipeline\nVector + Lexical + RRF + Rerank]
        Context[Context Builder]
        Prompts[Prompt Builder]
        Validation[Output + Grounding Validator]
    end

    subgraph Engine["Repository Engine"]
        Scanner[File Walker + Language Detector]
        Parser[AST Parser\ntree-sitter]
        SymExtract[Symbol Extractor]
        DepGraph[Dependency Graph]
    end

    subgraph Idx["Indexer"]
        Chunker[Symbol Chunker]
        EmbQueue[Embedding Queue]
    end

    subgraph Infra["Infrastructure"]
        PG[PostgreSQL + pgvector]
        Redis[Redis]
    end

    subgraph Ext["External Services"]
        OpenAI[OpenAI API]
        GH[GitHub API]
    end

    FE --> BE
    BE --> AI
    BE --> Engine
    BE --> Idx
    AI --> Infra
    AI --> OpenAI
    BE --> Infra
    BE --> GH
    Engine --> Idx
    Idx --> Infra
```
