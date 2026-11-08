# Database Migrations Workflow

We use Alembic for managing database migrations with PostgreSQL.

## Migration Files (Current — 12 Total)

| Migration | File | Description |
|---|---|---|
| `24498ac67b3e` | `24498ac67b3e_add_pgvector_extension.py` | Adds pgvector extension to PostgreSQL |
| `5f6dc031921b` | `5f6dc031921b_identity_schema.py` | Identity schema — users, github_installations, repositories |
| `aef3bb17eb34` | `aef3bb17eb34_content_tables.py` | Content tables — repository_files, code_symbols, symbol_edges, code_chunks |
| `cb4e2a7d0f31` | `cb4e2a7d0f31_add_sync_jobs.py` | Adds sync_jobs table for repository sync tracking |
| `e7b8c9d0f1a2` | `e7b8c9d0f1a2_add_code_chunks_and_memory.py` | Adds memory_entries table, vector indexes, and chunk enhancements |
| `f1c2d3e4b5a6` | `f1c2d3e4b5a6_add_analysis_runs_and_findings.py` | Developer Intelligence Suite — analysis_runs & analysis_findings |
| `b627460d74e0` | `b627460d74e0_add_pull_requests_table.py` | Pull Requests — pull_requests table for commit staging and PR metadata |
| `b3c4d5e6f7a8` | `b3c4d5e6f7a8_add_workflow_automation_tables.py` | Workflow Automation & Tasks — tasks, task_plans, approvals, workspaces, checkpoints |
| `c94e1f8a2d73` | `c94e1f8a2d73_add_week3_task_and_issue_tables.py` | Tasks & Issues — adds github_issues and task relationship enhancements |
| `d5e6f7a8b9c0` | `d5e6f7a8b9c0_fix_constraints_and_add_indexes.py` | Constraint fixes, cascading foreign keys, and query index hardening |
| `e1f2a3b4c5d6` | `e1f2a3b4c5d6_add_github_webhook_events_and_repo_automation.py` | Durable GitHub Webhook Ingestion — github_webhook_events table & repository automation flags |
| `e8f9a0b1c2d3` | `e8f9a0b1c2d3_add_code_search_text_and_index_generation.py` | Multi-Stage Retrieval — code_search_text column on code_chunks & active_index_generation tracking |

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
| `pull_requests` | `b627460d74e0_add_pull_requests_table` | Pull request metadata records and commit staging linkage |
| `tasks` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Development tasks with source traceability and repair counters |
| `task_plans` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Versioned implementation steps, expected files, test targets, and risks |
| `task_approvals` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Immutable human plan approvals and rejections |
| `workspaces` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Task workspace environments, isolation paths, and branches |
| `task_executions` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Worker execution attempts and execution statuses |
| `tool_invocations` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Controlled tool router executions and audit logs |
| `test_runs` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Test execution commands, outcomes, exit codes, and sanitized logs |
| `repair_attempts` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Bounded repair loop accounting (max 3 attempts) |
| `verification_results` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Multi-dimensional checks tied strictly to verified revisions |
| `task_checkpoints` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Recovery state snapshots with automated credential scrubbing |
| `task_events` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Chronological audit timeline and state transition events |
| `task_pull_requests` | `b3c4d5e6f7a8_add_workflow_automation_tables` | Created GitHub Draft PR records and head revisions |
| `github_issues` | `c94e1f8a2d73_add_week3_task_and_issue_tables` | Imported and synchronized GitHub issues |
| `github_webhook_events` | `e1f2a3b4c5d6_add_github_webhook_events_and_repo_automation` | Durable webhook event queue with status, leases, and retry backoff |

## Production Migration Consistency & Acyclic Chain

The entire 12-node migration chain is verified as continuous, unbroken, and acyclic (`backend/tests/test_migration_smoke.py::test_alembic_chain_is_unbroken_and_acyclic`):
1. **Unbroken, Linear Chain:** `24498ac67b3e` (root) → `5f6dc031921b` → `aef3bb17eb34` → `cb4e2a7d0f31` → `e7b8c9d0f1a2` → `f1c2d3e4b5a6` → `b627460d74e0` → `b3c4d5e6f7a8` → `c94e1f8a2d73` → `d5e6f7a8b9c0` → `e1f2a3b4c5d6` → `e8f9a0b1c2d3` (head). Exactly one leaf head revision exists.
2. **Schema & Model Parity:** All models in `backend/app/models/` have exact column and constraint parity with migrations, including:
   - `repositories`: `active_index_generation`, `active_commit_sha`, `last_indexed_commit_sha`, `auto_sync_enabled`, `pr_review_enabled`, `pr_review_drafts`.
   - `code_chunks`: `code_search_text` column with GIN simple text search index for code-aware lexical search.
   - `github_webhook_events`: `id`, `event_type`, `action`, `delivery_id`, `repository_id`, `status` (Enum: `PENDING`, `PROCESSING`, `SUCCEEDED`, `RETRY`, `DEAD_LETTER`), `attempts`, `max_attempts`, `available_at`, `claimed_at`, `lease_expires_at`, `last_error`.
3. **Cascading Referentials:** `ON DELETE CASCADE` verified on repository and run boundaries; `ON DELETE SET NULL` verified on user references.

Make sure your local PostgreSQL database (via `docker compose up -d`) is running before executing these commands.
