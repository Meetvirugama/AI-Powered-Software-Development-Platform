# 07. Database Documentation
> **Version:** 3.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-10-15 | **Status:** Synchronized & Live

> [!NOTE]
> Database models are implemented in `backend/app/models/`. Tables reflect the actual SQLAlchemy model definitions and Alembic migrations.

---

## Infrastructure

- **Database:** PostgreSQL 15
- **Extension:** `pgvector` (for vector similarity search)
- **ORM:** SQLAlchemy 2.0 (AsyncSession with `asyncpg`/`psycopg`)
- **Migration tool:** Alembic 1.13+
- **Connection:** `DATABASE_URL` env var → `postgresql+psycopg://platform:platform@localhost:5433/agent_platform` (port 5433/5432)
- **Vector index type:** HNSW (on `code_chunks.embedding` using `vector_cosine_ops`)

---

## ER Diagram (All 9 Tables)

```mermaid
erDiagram
    users {
        uuid id PK
        string github_id
        string login
        string email
        string avatar_url
        timestamp created_at
        timestamp updated_at
    }

    github_installations {
        uuid id PK
        uuid user_id FK
        string installation_id
        string account_login
        json permissions
        timestamp installed_at
    }

    repositories {
        uuid id PK
        uuid user_id FK
        uuid installation_id FK
        string github_repo_id
        string owner
        string name
        string default_branch
        string language
        enum sync_status
        timestamp last_synced_at
        timestamp created_at
        timestamp updated_at
    }

    sync_jobs {
        uuid id PK
        uuid repository_id FK
        uuid user_id FK
        enum status
        timestamp created_at
        timestamp updated_at
    }

    repository_files {
        uuid id PK
        uuid repository_id FK
        string path
        string language
        int size_bytes
        int line_count
        string content_hash
        timestamp indexed_at
    }

    code_symbols {
        uuid id PK
        uuid file_id FK
        uuid repository_id FK
        string name
        string kind
        int start_line
        int end_line
        string signature
        uuid parent_id FK
    }

    symbol_edges {
        uuid id PK
        uuid source_id FK
        uuid target_id FK
        string edge_type
    }

    code_chunks {
        uuid id PK
        uuid repository_id FK
        uuid file_id FK
        uuid symbol_id FK
        text content
        int token_count
        int start_line
        int end_line
        string content_hash
        vector embedding
        json metadata
        timestamp created_at
    }

    memory_entries {
        uuid id PK
        uuid repository_id FK
        enum type
        text content
        string source
        enum status
        timestamp created_at
        timestamp updated_at
    }

    users ||--o{ github_installations : "has"
    users ||--o{ repositories : "owns"
    users ||--o{ sync_jobs : "triggers"
    github_installations ||--o{ repositories : "grants access to"
    repositories ||--o{ repository_files : "contains"
    repositories ||--o{ sync_jobs : "tracked by"
    repositories ||--o{ memory_entries : "remembers"
    repository_files ||--o{ code_symbols : "defines"
    code_symbols ||--o{ symbol_edges : "source of"
    code_symbols ||--o{ symbol_edges : "target of"
    repository_files ||--o{ code_chunks : "indexed as"
    code_symbols ||--o{ code_chunks : "represented as"
```

---

## Complete Table Specifications

### 1. `users`
Stores authenticated GitHub users.

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | User ID |
| `github_id` | VARCHAR | No | — | — | — | GitHub numeric user ID (unique) |
| `login` | VARCHAR | No | — | — | — | GitHub username |
| `email` | VARCHAR | Yes | NULL | — | — | Primary email |
| `avatar_url` | VARCHAR | Yes | NULL | — | — | GitHub avatar URL |
| `created_at` | TIMESTAMPTZ | No | NOW() | — | — | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | No | NOW() | — | — | Last update timestamp |

---

### 2. `github_installations`
Stores GitHub App installations granting repository permissions.

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Installation record ID |
| `user_id` | UUID | No | — | — | `users.id` | Owner user |
| `installation_id` | VARCHAR | No | — | — | — | GitHub App installation ID (unique) |
| `account_login` | VARCHAR | No | — | — | — | Organization or user account login |
| `permissions` | JSONB | Yes | `'{}'` | — | — | Granted repository permissions |
| `installed_at` | TIMESTAMPTZ | No | NOW() | — | — | Installation timestamp |

---

### 3. `repositories`
Stores connected repositories and their indexing state.

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Repository ID (primary scoping key) |
| `user_id` | UUID | No | — | — | `users.id` | Connected user |
| `installation_id` | UUID | Yes | NULL | — | `github_installations.id` | App installation reference |
| `github_repo_id` | VARCHAR | No | — | — | — | GitHub repository ID |
| `owner` | VARCHAR | No | — | — | — | Repository owner / organization |
| `name` | VARCHAR | No | — | — | — | Repository name |
| `default_branch` | VARCHAR | No | `'main'` | — | — | Default branch |
| `language` | VARCHAR | Yes | NULL | — | — | Primary detected language |
| `sync_status` | ENUM | No | `'NOT_SYNCED'` | — | — | `NOT_SYNCED`, `SYNCING`, `SYNCED`, `FAILED` |
| `last_synced_at` | TIMESTAMPTZ | Yes | NULL | — | — | Last sync timestamp |
| `created_at` | TIMESTAMPTZ | No | NOW() | — | — | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | No | NOW() | — | — | Last update timestamp |

---

### 4. `sync_jobs`
Tracks background repository cloning, scanning, and indexing executions.

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Sync job ID |
| `repository_id` | UUID | No | — | — | `repositories.id` | Target repository |
| `user_id` | UUID | No | — | — | `users.id` | Triggering user |
| `status` | ENUM | No | `'QUEUED'` | — | — | `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED` |
| `created_at` | TIMESTAMPTZ | No | NOW() | — | — | Queue timestamp |
| `updated_at` | TIMESTAMPTZ | No | NOW() | — | — | Status update timestamp |

---

### 5. `repository_files`
Stores file tree metadata and content characteristics.

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | File record ID |
| `repository_id` | UUID | No | — | — | `repositories.id` | Scoping repository |
| `path` | VARCHAR | No | — | — | — | Relative path within repository |
| `language` | VARCHAR | Yes | NULL | — | — | Detected programming language |
| `size_bytes` | INTEGER | No | 0 | — | — | File size |
| `line_count` | INTEGER | No | 0 | — | — | Total line count |
| `content_hash` | VARCHAR | No | — | — | — | SHA-256 hash for incremental sync |
| `indexed_at` | TIMESTAMPTZ | No | NOW() | — | — | File index timestamp |

---

### 6. `code_symbols`
Stores AST-extracted symbols (functions, methods, classes).

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Symbol ID |
| `file_id` | UUID | No | — | — | `repository_files.id` | Source file |
| `repository_id` | UUID | No | — | — | `repositories.id` | Scoping repository |
| `name` | VARCHAR | No | — | — | — | Symbol name (e.g., `ContextBuilder`) |
| `kind` | VARCHAR | No | — | — | — | `class`, `function`, `method`, `import` |
| `start_line` | INTEGER | No | — | — | — | Starting line number (1-indexed) |
| `end_line` | INTEGER | No | — | — | — | Ending line number (inclusive) |
| `signature` | TEXT | Yes | NULL | — | — | Extracted declaration signature |
| `parent_id` | UUID | Yes | NULL | — | `code_symbols.id` | Parent symbol (e.g., method → class) |

---

### 7. `symbol_edges`
Stores caller-callee and dependency graph relationships.

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Edge ID |
| `source_id` | UUID | No | — | — | `code_symbols.id` | Caller / source symbol |
| `target_id` | UUID | No | — | — | `code_symbols.id` | Callee / referenced symbol |
| `edge_type` | VARCHAR | No | — | — | — | `calls`, `imports`, `extends`, `implements` |

---

### 8. `code_chunks`
Stores chunked code with pgvector dense embeddings for vector retrieval.

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Chunk ID |
| `repository_id` | UUID | No | — | — | `repositories.id` | Mandatory scoping key |
| `file_id` | UUID | No | — | — | `repository_files.id` | Source file |
| `symbol_id` | UUID | Yes | NULL | — | `code_symbols.id` | Associated symbol |
| `content` | TEXT | No | — | — | — | Raw code chunk content |
| `token_count` | INTEGER | No | — | — | — | Token count (`cl100k_base`) |
| `start_line` | INTEGER | No | — | — | — | First line in source file |
| `end_line` | INTEGER | No | — | — | — | Last line in source file |
| `content_hash` | VARCHAR | No | — | — | — | Content hash |
| `embedding` | VECTOR(1536) | Yes | NULL | — | — | pgvector embedding |
| `metadata` | JSONB | Yes | `'{}'` | — | — | Extra context (`file_path`, language) |
| `created_at` | TIMESTAMPTZ | No | NOW() | — | — | Creation timestamp |

**Indexes:**
- `CREATE INDEX ON code_chunks USING hnsw (embedding vector_cosine_ops);`
- `CREATE INDEX ON code_chunks USING gin(to_tsvector('english', content));`
- `CREATE INDEX ON code_chunks (repository_id);`

---

### 9. `memory_entries`
Stores long-term architectural memory, rules, and project learnings.

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Memory entry ID |
| `repository_id` | UUID | No | — | — | `repositories.id` | Scoping repository |
| `type` | ENUM | No | — | — | — | `project`, `decision`, `rule`, `task_summary`, `failure` |
| `content` | TEXT | No | — | — | — | Memory content |
| `source` | VARCHAR | No | — | — | — | Source identifier |
| `status` | ENUM | No | `'active'` | — | — | `active`, `stale`, `archived` |
| `created_at` | TIMESTAMPTZ | No | NOW() | — | — | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | No | NOW() | — | — | Update timestamp |

---

## Applied Alembic Migrations

| Revision | Name | Description |
|---|---|---|
| `24498ac67b3e` | `24498ac67b3e_add_pgvector_extension.py` | Installs `pgvector` extension in PostgreSQL |
| `5f6dc031921b` | `5f6dc031921b_identity_schema.py` | Creates `users`, `github_installations`, `repositories` |
| `aef3bb17eb34` | `aef3bb17eb34_content_tables.py` | Creates `repository_files`, `code_symbols`, `symbol_edges`, `code_chunks` |
| `cb4e2a7d0f31` | `cb4e2a7d0f31_add_sync_jobs.py` | Creates `sync_jobs` table |
| `e7b8c9d0f1a2` | `e7b8c9d0f1a2_add_code_chunks_and_memory.py` | Creates `memory_entries` table and pgvector chunk enhancements |
