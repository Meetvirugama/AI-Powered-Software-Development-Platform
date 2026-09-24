# 07. Database Documentation
> **Version:** 1.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-24 | **Status:** Draft

> [!WARNING]
> Database models are **not yet implemented** in `backend/app/models/`. This document is based on the design specification in `Docs/daily_tasks.md` (Om's Day 1–3 tasks). Tables marked `⚪ Planned` do not yet exist.
>
> When Om creates migrations, update this document to match the actual schema.

---

## Infrastructure

- **Database:** PostgreSQL 15
- **Extension:** `pgvector` (for vector similarity search)
- **ORM:** SQLAlchemy 2.0 (AsyncSession)
- **Migration tool:** Alembic 1.13
- **Connection:** `DATABASE_URL` env var → `postgresql+psycopg://platform:platform@localhost:5432/agent_platform`
- **Vector index type:** HNSW (on `code_chunks.embedding`)

---

## ER Diagram

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

    symbols {
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

    users ||--o{ github_installations : "has"
    users ||--o{ repositories : "owns"
    github_installations ||--o{ repositories : "grants access to"
    repositories ||--o{ repository_files : "contains"
    repository_files ||--o{ symbols : "defines"
    symbols ||--o{ symbol_edges : "source of"
    symbols ||--o{ symbol_edges : "target of"
    repository_files ||--o{ code_chunks : "indexed as"
    symbols ||--o{ code_chunks : "represented as"
```

---

## Table Documentation

### `users`

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Internal user ID |
| `github_id` | VARCHAR | No | — | — | — | GitHub user numeric ID (unique) |
| `login` | VARCHAR | No | — | — | — | GitHub username |
| `email` | VARCHAR | Yes | NULL | — | — | GitHub email (may be private) |
| `avatar_url` | VARCHAR | Yes | NULL | — | — | GitHub avatar URL |
| `created_at` | TIMESTAMPTZ | No | NOW() | — | — | Record creation time |
| `updated_at` | TIMESTAMPTZ | No | NOW() | — | — | Last update time |

**Indexes:** `UNIQUE (github_id)`
**Used by:** Auth API, all user-scoped queries
**Status:** ⚪ Planned

---

### `github_installations`

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Internal installation ID |
| `user_id` | UUID | No | — | — | `users.id` | Installing user |
| `installation_id` | VARCHAR | No | — | — | — | GitHub App installation ID |
| `account_login` | VARCHAR | No | — | — | — | GitHub account that installed the App |
| `permissions` | JSONB | Yes | NULL | — | — | GitHub App permission set |
| `installed_at` | TIMESTAMPTZ | No | NOW() | — | — | Installation timestamp |

**Indexes:** `UNIQUE (installation_id)`
**Used by:** GitHub integration, InstallationTokenManager
**Status:** ⚪ Planned

---

### `repositories`

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Internal repository ID |
| `user_id` | UUID | No | — | — | `users.id` | Owner |
| `installation_id` | UUID | No | — | — | `github_installations.id` | GitHub App installation |
| `github_repo_id` | VARCHAR | No | — | — | — | GitHub repository numeric ID |
| `owner` | VARCHAR | No | — | — | — | GitHub owner login |
| `name` | VARCHAR | No | — | — | — | Repository name |
| `default_branch` | VARCHAR | No | `'main'` | — | — | Default branch |
| `language` | VARCHAR | Yes | NULL | — | — | Primary detected language |
| `sync_status` | ENUM | No | `'NOT_SYNCED'` | — | — | Current sync state |
| `last_synced_at` | TIMESTAMPTZ | Yes | NULL | — | — | Last successful sync time |
| `created_at` | TIMESTAMPTZ | No | NOW() | — | — | Record creation |
| `updated_at` | TIMESTAMPTZ | No | NOW() | — | — | Last update |

**Enums:** `SyncStatus: NOT_SYNCED | SYNCING | SYNCED | FAILED`
**Indexes:** `(user_id)`, `UNIQUE (github_repo_id)`
**Used by:** Repository API, sync worker, scanner
**Status:** ⚪ Planned

---

### `repository_files`

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | File ID |
| `repository_id` | UUID | No | — | — | `repositories.id` | Parent repository |
| `path` | VARCHAR | No | — | — | — | Repository-relative path (e.g. `src/auth/service.ts`) |
| `language` | VARCHAR | Yes | NULL | — | — | Detected language |
| `size_bytes` | INTEGER | No | — | — | — | File size in bytes |
| `line_count` | INTEGER | No | — | — | — | Total line count (used by GroundingValidator) |
| `content_hash` | VARCHAR | No | — | — | — | SHA-256 of file content for change detection |
| `indexed_at` | TIMESTAMPTZ | Yes | NULL | — | — | When file was last indexed |

**Indexes:** `(repository_id)`, `UNIQUE (repository_id, path)`
**Used by:** GroundingValidator, scanner, indexer
**Status:** ⚪ Planned

---

### `symbols`

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Symbol ID |
| `file_id` | UUID | No | — | — | `repository_files.id` | Source file |
| `repository_id` | UUID | No | — | — | `repositories.id` | Denormalized for fast scoping |
| `name` | VARCHAR | No | — | — | — | Symbol name (e.g. `AuthService`) |
| `kind` | VARCHAR | No | — | — | — | `class | function | method | import | constant` |
| `start_line` | INTEGER | No | — | — | — | First line (1-indexed) |
| `end_line` | INTEGER | No | — | — | — | Last line (inclusive) |
| `signature` | TEXT | Yes | NULL | — | — | Full signature string |
| `parent_id` | UUID | Yes | NULL | — | `symbols.id` | Parent symbol (e.g. method → class) |

**Indexes:** `(repository_id)`, `(file_id)`
**Used by:** Indexer, dependency graph, blast radius analysis
**Status:** ⚪ Planned

---

### `symbol_edges`

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Edge ID |
| `source_id` | UUID | No | — | — | `symbols.id` | Caller / importer / child |
| `target_id` | UUID | No | — | — | `symbols.id` | Callee / imported / parent |
| `edge_type` | VARCHAR | No | — | — | — | `calls | imports | extends | implements` |

**Indexes:** `(source_id)`, `(target_id)`
**Used by:** Dependency graph, blast radius analysis
**Status:** ⚪ Planned

---

### `code_chunks`

> **Critical table** — used by `VectorRetriever` for cosine similarity search.

| Column | Type | Nullable | Default | PK | FK | Description |
|---|---|---|---|---|---|---|
| `id` | UUID | No | gen_random_uuid() | ✓ | — | Chunk ID |
| `repository_id` | UUID | No | — | — | `repositories.id` | Scoping key (ALL queries filter by this) |
| `file_id` | UUID | No | — | — | `repository_files.id` | Source file |
| `symbol_id` | UUID | Yes | NULL | — | `symbols.id` | Optional parent symbol |
| `content` | TEXT | No | — | — | — | Raw code text |
| `token_count` | INTEGER | No | — | — | — | Approximate token count |
| `start_line` | INTEGER | No | — | — | — | First line in source file |
| `end_line` | INTEGER | No | — | — | — | Last line in source file |
| `content_hash` | VARCHAR | No | — | — | — | For deduplication and change detection |
| `embedding` | VECTOR(1536) | Yes | NULL | — | — | OpenAI text-embedding-3-small vector |
| `metadata` | JSONB | Yes | `'{}'` | — | — | Includes `file_path` for convenience |
| `created_at` | TIMESTAMPTZ | No | NOW() | — | — | Index time |

**Indexes:**
- `(repository_id)` — required; all queries scope to a repository
- `HNSW (embedding vector_cosine_ops)` — for fast pgvector `<=>` cosine search

**Critical constraint:** Every SELECT on this table MUST include `WHERE repository_id = :repository_id`. (Enforced by `VectorRetriever` SQL, team rule.)

**Used by:** VectorRetriever, LexicalRetriever, GroundingValidator
**Related APIs:** Chat API (planned)
**Status:** ⚪ Planned (dimension 1536 assumed for `text-embedding-3-small`)

---

## Data Dictionary

| Term | Definition |
|---|---|
| `repository_id` | UUID scoping key attached to all data objects — prevents cross-repo data leakage |
| `code_chunk` | A piece of source code (function, class, or module section) extracted from a file and embedded for semantic search |
| `symbol` | A named code entity extracted by tree-sitter: class, function, method, import, constant |
| `symbol_edge` | A directed dependency relationship between two symbols |
| `sync_status` | Current indexing state of a repository (NOT_SYNCED → SYNCING → SYNCED/FAILED) |
| `embedding` | A float vector (1536 dimensions) produced by OpenAI `text-embedding-3-small` |
| `content_hash` | SHA-256 hash of file/chunk content for incremental update detection |
| `grounded source` | An LLM citation whose file path and line range have been verified to exist in the DB |

---

## Relationships Summary

| Relationship | Type |
|---|---|
| `users` → `repositories` | One-to-many |
| `users` → `github_installations` | One-to-many |
| `github_installations` → `repositories` | One-to-many |
| `repositories` → `repository_files` | One-to-many |
| `repository_files` → `symbols` | One-to-many |
| `symbols` → `symbol_edges` | One-to-many (as source) |
| `symbols` → `symbol_edges` | One-to-many (as target) |
| `repository_files` → `code_chunks` | One-to-many |
| `symbols` → `code_chunks` | One-to-many (optional) |

---

## Schema Change Protocol

1. **Only Om creates migration files.** Others open a GitHub issue describing the needed change.
2. **Migration naming:** `YYYYMMDD_HHMMSS_description.py`
3. **Every migration must be reversible** — both `upgrade()` and `downgrade()` required.
4. **Never drop a column in production without a two-step migration.**
5. **Notify team 24 hours before renaming/removing model fields.**

**When schema changes, update:**
1. ER diagram (this document)
2. Data dictionary (this document)
3. Related API documentation (→ `08_api_documentation.md`)
4. Feature documentation (→ `09_feature_documentation.md`)
5. Class diagram (→ `06_uml_diagrams.md`) if SQLAlchemy models change
6. Sequence diagrams if query patterns change
