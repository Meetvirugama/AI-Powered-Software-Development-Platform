# Database Migrations Workflow

We use Alembic for managing database migrations with PostgreSQL.

## Migration Files (Current)

| Migration | File | Description |
|---|---|---|
| `24498ac67b3e` | `24498ac67b3e_add_pgvector_extension.py` | Adds pgvector extension to PostgreSQL |
| `5f6dc031921b` | `5f6dc031921b_identity_schema.py` | Identity schema — users, github_installations, repositories |
| `aef3bb17eb34` | `aef3bb17eb34_content_tables.py` | Content tables — repository_files, code_symbols, symbol_edges, code_chunks |
| `cb4e2a7d0f31` | `cb4e2a7d0f31_add_sync_jobs.py` | Adds sync_jobs table for repository sync tracking |
| `e7b8c9d0f1a2` | `e7b8c9d0f1a2_add_code_chunks_and_memory.py` | Adds memory_entries table, vector indexes, and chunk enhancements |
| `f1c2d3e4b5a6` | `f1c2d3e4b5a6_add_analysis_runs_and_findings.py` | Developer Intelligence Suite — analysis_runs & analysis_findings |

## How to Create a Migration

When you create or modify an SQLAlchemy model in `app/models/`, you need to generate a new migration script:

```bash
cd backend
alembic revision --autogenerate -m "description_of_your_changes"
```

> [!IMPORTANT]
> Only **Om** creates migration files. Never create a migration without Om's review — schema conflicts can corrupt the database.

## How to Run Migrations

To apply all pending migrations and update your database to the latest schema:

```bash
cd backend
alembic upgrade head
```

## How to Rollback Migrations

If you need to revert the database schema to a previous state:

```bash
cd backend
# Revert the last applied migration
alembic downgrade -1

# Revert to a specific migration version
alembic downgrade <revision_id>
```

## Table → Migration Map

| DB Table | Created In Migration | Notes |
|---|---|---|
| `users` | `5f6dc031921b_identity_schema` | GitHub user profiles & auth |
| `github_installations` | `5f6dc031921b_identity_schema` | GitHub App installation permissions & tokens |
| `repositories` | `5f6dc031921b_identity_schema` | Synced repository records & status |
| `repository_files` | `aef3bb17eb34_content_tables` | File tree & file content metadata |
| `code_symbols` | `aef3bb17eb34_content_tables` | AST-extracted symbols (functions, classes, methods) |
| `symbol_edges` | `aef3bb17eb34_content_tables` | Dependency graph & caller-callee edges |
| `code_chunks` | `aef3bb17eb34_content_tables` | Chunked code with pgvector `vector(1536)` embeddings |
| `sync_jobs` | `cb4e2a7d0f31_add_sync_jobs` | Background sync job tracking & statuses |
| `memory_entries` | `e7b8c9d0f1a2_add_code_chunks_and_memory` | Repository memory, architectural decisions, and learnings |
| `analysis_runs` | `f1c2d3e4b5a6_add_analysis_runs_and_findings` | Analysis execution runs, targets, source revisions & outputs |
| `analysis_findings` | `f1c2d3e4b5a6_add_analysis_runs_and_findings` | Categorized defect & review findings with source references |

## Week 2 Day 7 — Migration Consistency & Index Audit

On Week 2 Day 7, Om verified the entire migration chain and composite index inventory (`backend/tests/test_om_w2_d7_acceptance_regression.py::TestDay7MigrationConsistency`):
1. **Unbroken, Acyclic Chain:** Verified 6 linear nodes: `24498ac67b3e` (root) -> `5f6dc031921b` -> `aef3bb17eb34` -> `cb4e2a7d0f31` -> `e7b8c9d0f1a2` -> `f1c2d3e4b5a6` (head). No split heads or cycles exist.
2. **Schema & Model Parity:** All 16 columns of `AnalysisRun` and 13 columns of `AnalysisFinding` have exact type and nullability parity with `f1c2d3e4b5a6`.
3. **Composite Index Parity:** All 7 high-performance query indexes verified:
   - `ix_analysis_runs_repo_created` (`repository_id`, `created_at DESC`)
   - `ix_analysis_runs_repo_feature_status` (`repository_id`, `feature_type`, `status`)
   - `ix_analysis_runs_repo_revision` (`repository_id`, `source_revision`)
   - `ix_analysis_runs_repo_target_path` (`repository_id`, `target_path`)
   - `ix_analysis_findings_run_severity` (`analysis_run_id`, `severity`)
   - `ix_analysis_findings_repo_file` (`repository_id`, `file_path`)
   - `ix_analysis_findings_repo_category` (`repository_id`, `category`)
4. **Cascading Referentials:** `ON DELETE CASCADE` verified on repository and run boundaries; `ON DELETE SET NULL` verified on user references.

Make sure your local PostgreSQL database (via `docker compose up -d`) is running before executing these commands.
