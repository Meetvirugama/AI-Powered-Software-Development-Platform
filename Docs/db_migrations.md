# Database Migrations Workflow

We use Alembic for managing database migrations with PostgreSQL.

## How to Create a Migration

When you create or modify an SQLAlchemy model in `app/models/`, you need to generate a new migration script:

```bash
cd backend
alembic revision --autogenerate -m "description_of_your_changes"
```

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

Make sure your local PostgreSQL database (via `docker-compose up -d postgres`) is running before executing these commands.
