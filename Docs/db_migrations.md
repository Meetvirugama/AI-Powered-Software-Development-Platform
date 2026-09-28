# Database Migrations Workflow

We use Alembic for managing database migrations with PostgreSQL.

## Migration Files (Current)

| Migration | File | Description |
|---|---|---|
| `24498ac67b3e` | `24498ac67b3e_add_pgvector_extension.py` | Adds pgvector extension to PostgreSQL |
| `5f6dc031921b` | `5f6dc031921b_identity_schema.py` | Identity schema — users, github_installations, repositories |
| `aef3bb17eb34` | `aef3bb17eb34_content_tables.py` | Content tables — repository_files, code_symbols, symbol_edges, code_chunks |
| `cb4e2a7d0f31` | `cb4e2a7d0f31_add_sync_jobs.py` | Adds sync_jobs table for repository sync tracking |

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

| DB Table | Created In Migration |
|---|---|
| `users` | `5f6dc031921b_identity_schema` |
| `github_installations` | `5f6dc031921b_identity_schema` |
| `repositories` | `5f6dc031921b_identity_schema` |
| `repository_files` | `aef3bb17eb34_content_tables` |
| `code_symbols` | `aef3bb17eb34_content_tables` |
| `symbol_edges` | `aef3bb17eb34_content_tables` |
| `code_chunks` | `aef3bb17eb34_content_tables` |
| `sync_jobs` | `cb4e2a7d0f31_add_sync_jobs` |

Make sure your local PostgreSQL database (via `docker-compose up -d postgres`) is running before executing these commands.
