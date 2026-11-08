# 18. Repository Deletion Cascades & Resource Cleanup Audit

## Executive Summary

Issue #183 audits and hardens the complete repository deletion lifecycle across the relational database (PostgreSQL), search & vector representations (pgvector), filesystem storage (workspaces, clones, intelligence snapshots), in-memory cache/queues (Redis), and background asynchronous execution workers.

Prior to this hardening, deleting a repository relied on manual procedural ORM `session.execute(delete(...))` queries. The underlying PostgreSQL foreign keys lacked database-level `ON DELETE CASCADE` clauses on several core tables (`repository_files`, `code_symbols`, `symbol_edges`, `code_chunks`, `memory_entries`, and `sync_jobs`). Direct database deletions failed with foreign key violations, and external resources (such as cloned working directories, `.workspaces/repository-intelligence` physical artifacts, and Redis caches) were left orphaned. Furthermore, background synchronization workers had no safeguard preventing stale in-flight indexing jobs from writing orphaned records after a repository was deleted.

This document details the complete resource dependency map, confirms observed defects, defines a formal deletion and retention policy, outlines the database migration and worker safety enhancements, and provides automated verification procedures.

---

## 1. Resource Dependency Map

The following map catalogs all resources associated with a repository, detailing relational constraints, external storage, cleanup mechanisms, retention policies, and audit findings.

| # | Resource / Model | Association to Repository | Relationship Type | DB FK Behavior (Initial) | ORM Cascade (Initial) | External Storage | Existing Cleanup | Retention Policy | Audit Finding |
|---|---|---|---|---|---|---|---|---|---|
| **1** | `Repository` (`repositories`) | Root entity | Direct | N/A | None | Database (`repositories` table) | `session.delete(repo)` | **DELETE** | Root record; deletion was not cascading down to DB-level FKs. |
| **2** | `RepositoryFile` (`repository_files`) | `repository_id` | Direct | `NO ACTION` (Migration `aef3bb17eb34`) | `ondelete="CASCADE"` on model only | PostgreSQL | Manual SQL `delete` in repository repo | **DELETE** | **Defect**: Migration lacked `ondelete="CASCADE"`; direct DB delete failed. |
| **3** | `CodeSymbol` (`code_symbols`) | `repository_id`, `file_id`, `parent_id` | Direct & Indirect | `NO ACTION` (Migration `aef3bb17eb34`) | None | PostgreSQL | Manual SQL `delete` | **DELETE** | **Defect**: Lacked `CASCADE` on `repository_id` and `file_id`; lacked `SET NULL` on `parent_id`. |
| **4** | `SymbolEdge` (`symbol_edges`) | `repository_id`, `source_symbol_id`, `target_symbol_id` | Direct & Indirect | `NO ACTION` (Migration `aef3bb17eb34`) | None | PostgreSQL | Manual SQL `delete` | **DELETE** | **Defect**: Lacked `CASCADE` on `repository_id`, `source_symbol_id`, and `target_symbol_id`. |
| **5** | `CodeChunk` (`code_chunks`) | `repository_id`, `file_id`, `symbol_id` | Direct & Indirect | `NO ACTION` (Migration `e7b8c9d0f1a2`) | None | PostgreSQL + pgvector HNSW index | Manual SQL `delete` | **DELETE** | **Defect**: Lacked `CASCADE` on `repository_id`, `file_id`; lacked `SET NULL` on `symbol_id`. |
| **6** | `MemoryEntry` (`memory_entries`) | `repository_id` | Direct | `NO ACTION` (Migration `e7b8c9d0f1a2`) | None | PostgreSQL | Manual SQL `delete` | **DELETE** | **Defect**: Lacked `CASCADE` on `repository_id`. |
| **7** | `SyncJob` (`sync_jobs`) | `repository_id` | Direct | `NO ACTION` (Migration `cb4e2a7d0f31`) | None | PostgreSQL | Manual SQL `delete` | **DELETE** | **Defect**: Lacked `CASCADE` on `repository_id`. |
| **8** | `PullRequest` (`pull_requests`) | `repository_id` | Direct | `ON DELETE CASCADE` (`b627460d74e0`) | `ondelete="CASCADE"` | PostgreSQL | DB Cascade + Manual SQL | **DELETE** | Correct in migration and model. |
| **9** | `AnalysisRun` (`analysis_runs`) | `repository_id` | Direct | `ON DELETE CASCADE` (`f1c2d3e4b5a6`) | `ondelete="CASCADE"` | PostgreSQL | DB Cascade + Manual SQL | **DELETE** | Correct in migration and model. |
| **10** | `AnalysisFinding` (`analysis_findings`) | `repository_id`, `run_id` | Direct & Indirect | `ON DELETE CASCADE` (`f1c2d3e4b5a6`) | `ondelete="CASCADE"` | PostgreSQL | DB Cascade + Manual SQL | **DELETE** | Correct in migration and model. |
| **11** | `GitHubIssue` (`github_issues`) | `repository_id` | Direct | `ON DELETE CASCADE` (`c94e1f8a2d73`) | `ondelete="CASCADE"` | PostgreSQL | DB Cascade + Manual SQL | **DELETE** | Correct in migration and model. |
| **12** | `Task` (`tasks`) | `repository_id` | Direct | `ON DELETE CASCADE` (`b3c4d5e6f7a8`) | `ondelete="CASCADE"` | PostgreSQL | DB Cascade + ORM delete | **DELETE** | Correct in migration and model. Cascades child task tables. |
| **13** | Task Child Records (`task_plans`, `task_steps`, `task_approvals`, `task_checkpoints`, etc.) | `task_id` -> `tasks.id` | Indirect | `ON DELETE CASCADE` (`b3c4d5e6f7a8`) | `ondelete="CASCADE"` | PostgreSQL | DB Cascade via `Task` | **DELETE** | Correct in migrations and models. |
| **14** | `TaskVerification` (`task_verifications`) | `task_id`, `repository_id` | Direct & Indirect | `ON DELETE CASCADE` (`b3c4d5e6f7a8`) | `ondelete="CASCADE"` | PostgreSQL | DB Cascade via `Task` | **DELETE** | Correct in migration and model. |
| **15** | `WebhookEvent` (`github_webhook_events`) | `repository_id` | Direct | `ON DELETE SET NULL` (`e1f2a3b4c5d6`) | `ondelete="SET NULL"` | PostgreSQL | Retained with nullified repo_id | **RETAIN** | Correct in migration and model. Preserves audit logs. |
| **16** | Repository Intelligence Snapshots | `repository_id` | Direct | N/A | N/A | Disk: `.workspaces/repository-intelligence/{repo_id}` | None | **DELETE** | **Defect**: Snapshot directory was never removed upon deletion. |
| **17** | Temporary Git Clones | `repository_id`, `job_id` | Direct | N/A | N/A | Disk: `/tmp/ai_platform_workspaces/repo_{repo_id}_*` | None on delete | **DELETE** | **Defect**: Abandoned or stale clone directories lingered. |
| **18** | Task Workspaces | `task_id` (belonging to repository) | Indirect | N/A | N/A | Disk: `.workspaces/task-{task_id}` | None on repo delete | **DELETE** | **Defect**: Disposable sandboxes lingered on disk. |
| **19** | Source Revision Cache | `repository_id` | Direct | N/A | N/A | Redis: `gh_src:{repo_id}:*` | None | **INVALIDATE** | **Defect**: Redis cache keys remained cached up to 1 hour. |
| **20** | Retrieval Result Cache | `repository_id` | Direct | N/A | N/A | Redis: `retrieval:v2:default:{repo_id}:*` | None | **INVALIDATE** | **Defect**: Retrieval cache keys remained cached up to TTL. |
| **21** | Sync Worker Repository Lock | `repository_id` | Direct | N/A | N/A | Redis: `sync_lock:repo:{repo_id}` | None | **INVALIDATE** | **Defect**: Lock lingered until expiry. |
| **22** | Sync Job Queue | `repository_id` | Direct | N/A | N/A | Redis: `sync_jobs` list | None | **INVALIDATE** | **Defect**: Queued jobs for deleted repository could execute. |
| **23** | Global Embedding Cache | Hash of text content | Independent / Content-addressed | N/A | N/A | Redis: `emb:v1:*` | None | **RETAIN** | Correct. Content-addressed vectors are shared across all repositories. |

---

## 2. Resource Cleanup and Retention Policy

The cleanup lifecycle enforces three explicit states:

### 1. DELETE (Permanent Destruction)
All resources strictly proprietary to the deleted repository must be permanently removed:
- **Relational Tables:** All rows in `repositories`, `repository_files`, `code_symbols`, `symbol_edges`, `code_chunks`, `memory_entries`, `sync_jobs`, `pull_requests`, `analysis_runs`, `analysis_findings`, `github_issues`, `tasks`, and task child entities.
- **pgvector Vector Chunks:** Deleted atomically with `code_chunks` rows.
- **Filesystem Artifacts:**
  - Intelligence snapshot root: `.workspaces/repository-intelligence/{repository_id}`.
  - Lingering clone roots: `repo_{repository_id}_*` under `/tmp/ai_platform_workspaces` and `/tmp/ai_platform_repos`.
  - Task workspace sandboxes: `.workspaces/task-{task_id}` for tasks owned by the repository.

### 2. INVALIDATE (Immediate Purge from Memory / Queues)
Ephemeral keys and in-flight queue payloads referencing the repository must be purged:
- **`gh_src:{repository_id}:*`:** Evaluated and deleted using cursor-based `SCAN` via `SourceRevisionCache.invalidate_repository`.
- **`retrieval:v2:default:{repository_id}:*`:** Evaluated and deleted using cursor-based `SCAN` via `RetrievalResultCache.invalidate_repository`.
- **`sync_lock:repo:{repository_id}`:** Deleted immediately from Redis.
- **`sync_jobs` (Redis List):** Any queued JSON payloads matching `"repository_id": str(repository_id)` are removed via atomic filtering, and worker loops verify repository presence before work begins.

### 3. RETAIN (Historical Audit Preservation & Shared Protection)
- **`github_webhook_events`:** Retained for audit and security analysis. The foreign key `repository_id` is automatically set to `NULL` (`ON DELETE SET NULL`), preserving delivery logs, HMAC signatures, and payloads without dangling keys.
- **Shared Content-Addressed Embeddings (`emb:v1:*`):** Embeddings cached by SHA-256 hash are shared across repositories and files containing identical code. They are preserved according to the global LRU/TTL policy.
- **Shared GitHub Installations (`github_installations`) and Users (`users`):** Retained untouched; only the association to the deleted repository is removed.

---

## 3. Database Cascade Verification and Migration

### Confirmed Schema Defects
An inspection of `backend/migrations/versions/` confirmed that early migrations did not specify `ondelete="CASCADE"`:
- Migration `aef3bb17eb34_content_tables.py`:
  - `repository_files.repository_id` -> missing `CASCADE`.
  - `code_symbols.repository_id` -> missing `CASCADE`.
  - `code_symbols.file_id` -> missing `CASCADE`.
  - `code_symbols.parent_id` -> missing `SET NULL`.
  - `symbol_edges.repository_id` -> missing `CASCADE`.
  - `symbol_edges.source_symbol_id` -> missing `CASCADE`.
  - `symbol_edges.target_symbol_id` -> missing `CASCADE`.
- Migration `e7b8c9d0f1a2_add_code_chunks_and_memory.py`:
  - `code_chunks.repository_id` -> missing `CASCADE`.
  - `code_chunks.file_id` -> missing `CASCADE`.
  - `code_chunks.symbol_id` -> missing `SET NULL`.
  - `memory_entries.repository_id` -> missing `CASCADE`.
- Migration `cb4e2a7d0f31_add_sync_jobs.py`:
  - `sync_jobs.repository_id` -> missing `CASCADE`.

### Migration `f3c4d5e6a7b8_harden_repository_deletion_cascades.py`
A new linear migration with `down_revision = "e8f9a0b1c2d3"` drops the legacy constraints and recreates them with explicit `ON DELETE CASCADE` and `ON DELETE SET NULL`. The migration supports PostgreSQL and SQLite batch mode, ensuring full idempotency and clean bidirectional upgrade/downgrade behavior.

---

## 4. External Resource Cleanup Architecture

External cleanup is decoupled from the database transaction and executes in a post-commit hook:

```
[DELETE /repositories/{id}]
        │
        ▼
[Authorization Check] ──> 401 Unauthorized / 404 Not Found
        │
        ▼
[Pre-Delete Inspection] ──> Collect dependent task_ids & workspace paths
        │
        ▼
[Database Transaction] ──> Atomic delete of Repository & DB Cascades
        │
        ├── Rollback on DB Error (raises 500, state preserved)
        ▼
[Post-Commit Cleanup]
  ├── 1. Filesystem Cleanup:
  │      ├── Remove .workspaces/repository-intelligence/{repo_id}
  │      ├── Remove /tmp/ai_platform_*/repo_{repo_id}_*
  │      └── Remove .workspaces/task-{task_id} (path traversal guarded)
  │
  ├── 2. Redis Cache & Queue Invalidation:
  │      ├── Invalidate gh_src:{repo_id}:*
  │      ├── Invalidate retrieval:v2:default:{repo_id}:*
  │      ├── Delete sync_lock:repo:{repo_id}
  │      └── Drain sync_jobs matching repo_id
  │
  └── 3. Publish Event:
         └── platform_events -> repository.updated
```

### Path Traversal Guard
Workspaces and intelligence directory deletions employ strict containment validation:
1. `path.resolve()` resolves all symlinks and relative segments.
2. Verified that `resolved_target.is_relative_to(allowed_root)` is `True`.
3. Verified that `resolved_target != allowed_root` (never deletes root container).
4. `shutil.rmtree` handles missing directories gracefully without raising errors or leaking server paths.

---

## 5. Background Job & Worker Safety

To prevent background sync workers or indexing jobs from recreating data for a repository deleted while indexing was in-flight:
1. **Pre-Run Check:** `IncrementalIndexer._run_sync` checks `SELECT 1 FROM repositories WHERE id = :repo_id`. If absent, indexing aborts immediately.
2. **Pre-Commit Revalidation:** Before committing indexed files, chunks, and symbols in `IncrementalIndexer._run_sync`, the worker re-validates that `SELECT 1 FROM repositories WHERE id = :repo_id`. If the repository was deleted while symbols were parsing or embeddings were computing, the transaction rolls back and aborts.
3. **Worker Completion Guard:** `sync_worker.process_sync_job` checks `repo = db.get(Repository, repository_id)` before and after indexing. If missing, it cleans up temporary clone directories and terminates without modifying database status.
4. **Queue Purge:** Stale jobs for deleted repositories are filtered out from the `sync_jobs` queue during deletion and dropped on pop by the worker.

---

## 6. Verification and Test Results

Automated regression and lifecycle tests in `backend/tests/test_repository_deletion_cascades.py` verify:
1. **Tenant Authorization:**
   - Repository owner can delete repository.
   - Non-owner delete attempt returns 404 without leaking existence.
   - Unauthenticated delete attempt returns 401.
   - Invalid repository UUID returns 422/404.
   - Repeated deletion returns 404 consistently.
2. **Database Cascades:**
   - Raw SQL `DELETE FROM repositories WHERE id = ...` cascades across all tables without foreign key violations.
   - ORM `session.delete(repo)` cascades cleanly.
   - Audit webhooks retain logs with `repository_id = NULL`.
3. **External Cleanup:**
   - Intelligence snapshot directory `.workspaces/repository-intelligence/{repo_id}` deleted.
   - Temporary clone directories removed.
   - Redis `gh_src:*` and `retrieval:*` keys wiped.
   - `sync_lock:repo:*` removed.
4. **Multi-Tenancy & Isolation:**
   - Deleting Repo A preserves all records, files, chunks, and Redis keys of Repo B.
   - Shared embedding vectors in `emb:v1:*` remain intact.
5. **Worker Safety:**
   - Running job during deletion aborts without resurrecting data.
   - Pending queued job for deleted repo is discarded cleanly.
