# Engineering Specification 26: Project Memory Entries & MCP Resources (F36 / Issue #217)

> **Feature:** F36 — Project Memory Entries  
> **Status:** Production Ready  
> **Milestone:** Milestone 3 Hardening / Episodic Knowledge  
> **Primary Components:** `MemoryRepository`, `ProjectMemoryService`, `TaskExecutionOrchestrator`, `memories.py`, `ProjectMemoryPanel.tsx`

---

## 1. Executive Summary & Problem Statement

Prior to this work, the `memory_entries` schema and database tables existed in a dormant state. While `MemoryEntry` models were referenced by `ContextBuilder`, there were no active writers or API surfaces to store, retrieve, or query episodic learnings. Downstream reasoning engines lacked persistent access to:
1. **Successful Task Summaries:** Key modifications, verification results, and repair counts from past tasks.
2. **Failure Diagnoses:** Root causes of rejected verification runs, broken invariants, or exhausted repair attempts (preventing repeating identical failure modes).
3. **Architectural Conventions & Pinned Rules:** Project standards (e.g. "All Redis locks must have explicit TTLs", "Never write plaintext secrets").
4. **Semantic Retrieval:** Vector search across repository memories using pgvector cosine similarity.
5. **Model Context Protocol (MCP) Resource Exposure:** Standardized resource URIs (e.g. `memory://repo/{id}/rules`) readable by external agents and MCP tools.

This feature activates episodic project memory, adds pgvector `vector(768)` embeddings with HNSW indexing, hooks automated memory writers into task completion and failure workflows, and exposes a Project Memory management panel in the frontend alongside MCP 2025-11-25 resource interfaces.

---

## 2. Architecture & Data Flow

```mermaid
flowchart TD
    subgraph Execution ["Task Execution Lifecycle"]
        TEO[TaskExecutionOrchestrator]
        IV[IndependentVerifier]
        REP[Self-Repair Engine]
    end

    subgraph Memory ["Episodic Memory System (F36)"]
        PMS[ProjectMemoryService]
        MRepo[MemoryRepository]
        PG[(PostgreSQL + pgvector<br/>memory_entries)]
    end

    subgraph Surfaces ["Interfaces & Consumers"]
        API[FastAPI Memories Router<br/>/repositories/{id}/memories]
        MCP[MCP Resource Server<br/>memory://repo/{id}/*]
        UI[Frontend ProjectMemoryPanel]
        CB[ContextBuilder / Agents]
    end

    IV -- "Verification Passed" --> PMS
    IV -- "Verification Failed" --> PMS
    REP -- "Attempts Exhausted" --> PMS

    PMS --> MRepo
    MRepo --> PG

    PG --> MRepo
    MRepo --> PMS
    PMS --> API
    PMS --> MCP
    PMS --> CB
    API --> UI
```

---

## 3. Database Schema & Migration

### Migration `i6f7a8b9c0d1_add_memory_entries_embedding_and_hnsw.py`
Extends `memory_entries` with an embedding vector column and HNSW index:

```sql
ALTER TABLE memory_entries
ADD COLUMN IF NOT EXISTS embedding vector(768);

CREATE INDEX IF NOT EXISTS ix_memory_entries_embedding_hnsw
ON memory_entries
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

### SQLAlchemy Model: `MemoryEntry`
```python
class MemoryEntry(TimestampedModel, Base):
    __tablename__ = "memory_entries"

    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    type_: Mapped[MemoryType] = mapped_column("type", Enum(MemoryType))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String)
    status: Mapped[MemoryStatus] = mapped_column(Enum(MemoryStatus), default=MemoryStatus.active)
    embedding: Mapped[Any] = mapped_column(Vector(768), nullable=True)

    __table_args__ = (
        Index(
            "ix_memory_entries_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
```

---

## 4. Automated Memory Writers

The automated memory writers implement Reflexion-style episodic summaries:

| Trigger Point | Memory Type | Content Summary | Source |
|---|---|---|---|
| `IndependentVerifier` passes all required gates | `task_summary` | Task title, verification checks passed, repair count, files modified | `task:{task_id}` |
| `IndependentVerifier` fails / blocking findings | `failure` | Task title, verification failure reason, blocking findings count | `task:{task_id}` |
| Self-repair loop exhausts attempt budget | `failure` | Task title, error diagnostic, repair attempts count | `task:{task_id}` |
| User / agent pins convention | `rule` | Markdown text of convention (idempotently deduplicated) | `user_pinned` / `architectural_rfc` |

---

## 5. Model Context Protocol (MCP) Resource Endpoints

Under Model Context Protocol (MCP Spec 2025-11-25), memory entries are exposed as structured markdown resources:

| Resource URI | Category | Description |
|---|---|---|
| `memory://repo/{repo_id}/rules` | Pinned Rules | Active conventions, coding standards, and architectural constraints |
| `memory://repo/{repo_id}/decisions` | Decisions | Architectural Decision Records (ADRs) and design choices |
| `memory://repo/{repo_id}/task-summaries` | Task Summaries | Episodic records of completed task implementations |
| `memory://repo/{repo_id}/failures` | Failures | Known negative examples, anti-patterns, and failure diagnoses |
| `memory://repo/{repo_id}/all` | Complete Ledger | Complete active repository episodic memory ledger |

---

## 6. REST API Endpoints

All endpoints are mounted under `/api/v1/repositories/{repository_id}/memories` and enforce strict multi-tenant boundary checks (`_verify_owned_repository`):

- `GET /` — List and filter memories (supports `query`, `type`, `status`, `page`, `page_size`).
- `POST /` — Manually create a memory entry.
- `GET /{entry_id}` — Retrieve a memory entry by ID.
- `PATCH /{entry_id}` — Update memory content, lifecycle status (`active`, `stale`, `archived`), or type.
- `DELETE /{entry_id}` — Remove a memory entry.
- `POST /rules` — Pin an architectural convention (with automatic deduplication).
- `POST /automated/task-completion` — Record task completion memory.
- `POST /automated/task-failure` — Record task failure memory.
- `POST /semantic-search` — Query entries via pgvector cosine distance `<=>`.
- `GET /mcp-resources` — Enumerate exposed MCP memory resources.
- `GET /mcp-resources/{resource_slug}` — Read and format specific MCP markdown resource.

---

## 7. Frontend User Interface

The `ProjectMemoryPanel` component provides:
1. **Interactive Categorization Tabs:** All, Rules, Decisions, Summaries, Failures, and MCP Resources.
2. **Instant Search:** Lexical and semantic query filtering across memory content and sources.
3. **Pin Rule Action:** Quick-action form to add conventions with immediate reactivity.
4. **Lifecycle Management:** Inline editing of status (`active`, `stale`, `archived`) and content.
5. **MCP Inspector:** View exposed `memory://` URIs with one-click clipboard copying and markdown preview.

---

## 8. Verification & Test Evidence

- **Backend Unit & Integration Suite (`test_project_memory_service.py`):**
  - `test_memory_repository_crud_and_search`: Repository CRUD, repository boundary isolation, and pagination.
  - `test_automated_memory_writers`: Task completion, failure, and rule idempotency deduplication.
  - `test_multi_tenant_repository_isolation`: Cross-repository access prevention.
  - `test_api_memory_endpoints`: HTTP REST API lifecycle.
  - `test_semantic_vector_search_and_ranking`: Cosine similarity ranking and multi-tenant isolation.
  - `test_mcp_memory_resource_exposure`: Resource enumeration and URI resolution.
  - `test_api_semantic_and_mcp_endpoints`: REST endpoints for semantic search and MCP resources.
- **Frontend Integration Suite (`projectMemory.test.tsx`):**
  - 10 comprehensive tests covering service methods, MSW mocking, badge rendering, tab filtering, rule pinning, and MCP URI inspection.
