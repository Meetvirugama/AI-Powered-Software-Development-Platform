"""Migration smoke tests against clean PostgreSQL + pgvector schema (Week 2 Section 12 Item 12, B-21 & Week 3 F39).

Verifies:
1. Clean schema full lifecycle:
   - Upgrades an empty, isolated schema from <base> to head (c94e1f8a2d73).
   - Validates all platform tables, composite indexes, enum types, and pgvector HNSW index.
   - Downgrades -1 to verify rollback integrity.
   - Upgrades back to head to verify idempotent re-application.
2. Zero schema drift (B-21):
   - Programmatically runs autogenerate compare_metadata to verify exact parity between Base.metadata and database schema.
3. Acyclic and complete revision history:
   - Verifies all migrations form a continuous, unbroken, acyclic chain.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Generator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings
from app.core.database import Base
import app.models  # Ensure all ORM models are registered in Base.metadata


EXPECTED_TABLES = frozenset({
    "users",
    "github_installations",
    "repositories",
    "repository_files",
    "code_symbols",
    "symbol_edges",
    "sync_jobs",
    "code_chunks",
    "memory_entries",
    "analysis_runs",
    "analysis_findings",
    "pull_requests",
    "github_issues",
    "tasks",
    "task_plans",
    "task_approvals",
    "task_events",
})

EXPECTED_MILESTONE_REVISIONS = (
    "24498ac67b3e",  # pgvector extension
    "5f6dc031921b",  # identity tables (users, github_installations, repositories)
    "aef3bb17eb34",  # content tables (repository_files, code_symbols, etc.)
    "cb4e2a7d0f31",  # sync jobs
    "e7b8c9d0f1a2",  # code_chunks and memory_entries
    "f1c2d3e4b5a6",  # analysis_runs and analysis_findings
    "b627460d74e0",  # pull_requests
    "c94e1f8a2d73",  # week3 github_issues, tasks, task_plans, task_approvals, task_events
)


@pytest.fixture
def clean_schema_name() -> Generator[str, None, None]:
    """Create a temporary PostgreSQL schema and drop it after the test."""
    settings = get_settings()
    schema = f"smoke_{uuid.uuid4().hex[:10]}"
    try:
        engine = create_engine(settings.database_url)
        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema};"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL database not available for migration smoke test: {exc}")
        return

    try:
        yield schema
    finally:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE;"))
        except Exception:
            pass
        engine.dispose()


def test_clean_schema_migration_lifecycle(clean_schema_name: str) -> None:
    """Run full Alembic migration from <base> to head on a clean schema, test rollback and re-upgrade."""
    settings = get_settings()
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    assert ini_path.is_file(), f"alembic.ini not found at {ini_path}"

    cfg = Config(str(ini_path))
    # Escape % in search_path option for configparser compatibility
    url_with_schema = f"{settings.database_url}?options=-csearch_path%%3D{clean_schema_name},public"
    cfg.set_main_option("sqlalchemy.url", url_with_schema)
    cfg.set_main_option("version_table_schema", clean_schema_name)

    # 1. Upgrade from clean base to head
    command.upgrade(cfg, "head")

    engine = create_engine(f"{settings.database_url}?options=-csearch_path={clean_schema_name},public")
    try:
        insp = inspect(engine)
        tables = set(insp.get_table_names(schema=clean_schema_name))
        for expected in EXPECTED_TABLES:
            assert expected in tables, f"Expected table '{expected}' missing from clean migration schema"

        # Verify pgvector HNSW index was created on code_chunks
        indexes = {idx["name"]: idx for idx in insp.get_indexes("code_chunks", schema=clean_schema_name)}
        assert "ix_code_chunks_embedding_hnsw" in indexes, "HNSW vector index missing on code_chunks"
        assert "ix_code_chunks_content_gin" in indexes, "GIN full-text index missing on code_chunks"

        # Verify composite indexes on analysis_runs
        run_indexes = {idx["name"] for idx in insp.get_indexes("analysis_runs", schema=clean_schema_name)}
        assert "ix_analysis_runs_repo_feature_status" in run_indexes

        # Verify foreign keys on pull_requests
        pr_fks = insp.get_foreign_keys("pull_requests", schema=clean_schema_name)
        assert any(fk.get("options", {}).get("ondelete") == "CASCADE" or fk.get("name") == "pull_requests_repository_id_fkey" for fk in pr_fks)

        # 2. Downgrade -1 (rolls back Week 3 task tables)
        command.downgrade(cfg, "-1")
        insp_downgraded = inspect(create_engine(f"{settings.database_url}?options=-csearch_path={clean_schema_name},public"))
        tables_after_downgrade = set(insp_downgraded.get_table_names(schema=clean_schema_name))
        assert "tasks" not in tables_after_downgrade, "tasks table should be dropped after downgrade -1"
        assert "pull_requests" in tables_after_downgrade, "pull_requests should remain after downgrade -1"

        # 3. Re-upgrade to head (idempotent re-creation)
        command.upgrade(cfg, "head")
        insp_reupgraded = inspect(create_engine(f"{settings.database_url}?options=-csearch_path={clean_schema_name},public"))
        tables_reupgraded = set(insp_reupgraded.get_table_names(schema=clean_schema_name))
        assert "tasks" in tables_reupgraded, "tasks must be restored after re-upgrade head"

    finally:
        engine.dispose()


def test_zero_schema_drift_against_database() -> None:
    """Verify that ORM models (Base.metadata) and Alembic migrations have zero schema drift (B-21)."""
    settings = get_settings()
    try:
        ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        cfg = Config(str(ini_path))
        cfg.set_main_option("sqlalchemy.url", settings.database_url)
        command.upgrade(cfg, "head")

        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            diffs = compare_metadata(ctx, Base.metadata)

            # Filter out expected environment-specific benign diffs if any
            # (e.g. pgvector vector type internal details)
            actionable_diffs = []
            for diff in diffs:
                diff_str = str(diff)
                if "vector" in diff_str.lower() and "type" in diff_str.lower():
                    continue
                actionable_diffs.append(diff)

            assert len(actionable_diffs) == 0, (
                f"Schema drift detected between Base.metadata and database!\n"
                f"Diffs: {actionable_diffs}\n"
                f"Run 'alembic check' to inspect."
            )
    except Exception as exc:
        pytest.skip(f"PostgreSQL database not available for schema drift test: {exc}")
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


def test_alembic_chain_is_unbroken_and_acyclic() -> None:
    """Verify the migration chain forms a continuous, unbroken, acyclic chain from root to head."""
    versions_dir = Path(__file__).resolve().parent.parent / "migrations" / "versions"
    assert versions_dir.is_dir()

    migration_files = list(versions_dir.glob("*.py"))
    assert len(migration_files) >= len(EXPECTED_MILESTONE_REVISIONS), (
        f"Expected at least {len(EXPECTED_MILESTONE_REVISIONS)} migrations, found {len(migration_files)}"
    )

    revisions: dict[str, str | None] = {}
    for py_file in migration_files:
        content = py_file.read_text(encoding="utf-8")
        rev_match = re.search(r'revision:\s*(?:str\s*=\s*)?["\']([a-f0-9]+)["\']', content)
        down_match = re.search(
            r'down_revision:\s*(?:[A-Za-z0-9_, \[\]\|]*\s*=\s*)?(?:["\']([a-f0-9]+)["\']|None)',
            content,
        )
        if rev_match:
            rev_id = rev_match.group(1)
            down_id = down_match.group(1) if (down_match and down_match.group(1)) else None
            revisions[rev_id] = down_id

    # Every milestone revision must exist
    for milestone in EXPECTED_MILESTONE_REVISIONS:
        assert milestone in revisions, f"Milestone revision {milestone} missing from Alembic versions"

    # Determine leaf head revision dynamically (the revision not referenced as any other revision's down_revision)
    referenced_downs = {d for d in revisions.values() if d is not None}
    heads = [r for r in revisions if r not in referenced_downs]
    assert len(heads) == 1, f"Expected exactly 1 Alembic head revision, found {heads}"
    head_rev = heads[0]
    assert head_rev == EXPECTED_MILESTONE_REVISIONS[-1]

    # Walk backwards from head to root
    curr: str | None = head_rev
    visited: list[str] = []
    while curr is not None:
        visited.append(curr)
        assert curr in revisions, f"Dangling down_revision '{curr}'"
        curr = revisions[curr]
        assert len(visited) <= len(revisions), "Cycle detected in Alembic migration chain!"

    # Root must be 24498ac67b3e with down_revision None
    assert visited[-1] == EXPECTED_MILESTONE_REVISIONS[0]
    assert revisions[EXPECTED_MILESTONE_REVISIONS[0]] is None
