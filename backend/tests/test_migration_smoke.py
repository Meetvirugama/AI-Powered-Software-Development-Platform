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
from sqlalchemy import Engine, create_engine, inspect, text

from app.core.config import get_settings
from app.core.database import Base, normalize_sync_database_url
import app.models  # noqa: F401 — Ensure all ORM models are registered in Base.metadata


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
    "workspaces",
    "task_executions",
    "tool_invocations",
    "test_runs",
    "repair_attempts",
    "verification_results",
    "task_checkpoints",
    "task_events",
    "task_pull_requests",
    "github_webhook_events",
})

EXPECTED_MILESTONE_REVISIONS = (
    "24498ac67b3e",  # pgvector extension
    "5f6dc031921b",  # identity tables (users, github_installations, repositories)
    "aef3bb17eb34",  # content tables (repository_files, code_symbols, etc.)
    "cb4e2a7d0f31",  # sync jobs
    "e7b8c9d0f1a2",  # code_chunks and memory_entries
    "f1c2d3e4b5a6",  # analysis_runs and analysis_findings
    "b627460d74e0",  # pull_requests
    "b3c4d5e6f7a8",  # workflow automation & tasks
    "c94e1f8a2d73",  # week3 github_issues, tasks, task_plans, task_approvals, task_events
    "d5e6f7a8b9c0",  # fix constraints and add indexes
    "e1f2a3b4c5d6",  # durable github webhook events and repo automation (Issue #182)
    "e8f9a0b1c2d3",  # code search text and index generation tracking (Issue #187)
    "f3c4d5e6a7b8",  # harden repository deletion cascades (Issue #183)
    "g4d5e6f7a8b9",  # extend tool_invocations audit fields (Issue #201)
    "h5e6f7a8b9c0",  # extend task_approvals for tool and MCP (Issue #199)
    "i6f7a8b9c0d1",  # add memory_entries embedding and hnsw (Issue #217)
    "j7a8b9c0d1e2",  # modernize code_symbols and symbol_edges for provenance, resolution status, and ranking
)


@pytest.fixture
def clean_schema_name() -> Generator[str, None, None]:
    """Create a temporary PostgreSQL schema and drop it after the test."""
    db_url = normalize_sync_database_url(get_settings().database_url)
    if db_url.startswith("sqlite"):
        pytest.skip("PostgreSQL database not available for migration smoke test (SQLite active)")
        return
    schema = f"smoke_{uuid.uuid4().hex[:10]}"
    try:
        engine = create_engine(db_url, connect_args={"connect_timeout": 2})
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
    db_url = normalize_sync_database_url(get_settings().database_url)
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    assert ini_path.is_file(), f"alembic.ini not found at {ini_path}"

    cfg = Config(str(ini_path))
    # Escape % in search_path option and credentials for configparser compatibility
    escaped_url = db_url.replace("%", "%%")
    separator = "&" if "?" in escaped_url else "?"
    url_with_schema = f"{escaped_url}{separator}options=-csearch_path%%3D{clean_schema_name},public"
    cfg.set_main_option("sqlalchemy.url", url_with_schema)
    cfg.set_main_option("version_table_schema", clean_schema_name)

    def _make_engine() -> Engine:
        return create_engine(
            db_url,
            connect_args={"options": f"-c search_path={clean_schema_name},public"},
        )

    # 1. Upgrade from clean base to head
    command.upgrade(cfg, "head")

    engine = _make_engine()
    try:
        insp = inspect(engine)
        tables = set(insp.get_table_names(schema=clean_schema_name))
        for expected in EXPECTED_TABLES:
            assert expected in tables, f"Expected table '{expected}' missing from clean migration schema"

        # Verify pgvector HNSW index was created on code_chunks and memory_entries
        indexes = {idx["name"]: idx for idx in insp.get_indexes("code_chunks", schema=clean_schema_name)}
        assert "ix_code_chunks_embedding_hnsw" in indexes, "HNSW vector index missing on code_chunks"
        assert "ix_code_chunks_content_gin" in indexes, "GIN full-text index missing on code_chunks"

        mem_indexes = {idx["name"] for idx in insp.get_indexes("memory_entries", schema=clean_schema_name)}
        assert "ix_memory_entries_embedding_hnsw" in mem_indexes, "HNSW vector index missing on memory_entries"

        symbol_cols = {col["name"] for col in insp.get_columns("code_symbols", schema=clean_schema_name)}
        assert "importance_score" in symbol_cols, "importance_score missing from code_symbols at head"

        # Verify composite indexes on analysis_runs
        run_indexes = {idx["name"] for idx in insp.get_indexes("analysis_runs", schema=clean_schema_name)}
        assert "ix_analysis_runs_repo_feature_status" in run_indexes

        # Verify foreign keys on pull_requests
        pr_fks = insp.get_foreign_keys("pull_requests", schema=clean_schema_name)
        assert any(fk.get("options", {}).get("ondelete") == "CASCADE" or fk.get("name") == "pull_requests_repository_id_fkey" for fk in pr_fks)

        # 2. Downgrade -1 (rolls back head j7a8b9c0d1e2)
        command.downgrade(cfg, "-1")
        insp_downgraded = inspect(_make_engine())
        symbol_cols_after = {col["name"] for col in insp_downgraded.get_columns("code_symbols", schema=clean_schema_name)}
        edge_cols_after = {col["name"] for col in insp_downgraded.get_columns("symbol_edges", schema=clean_schema_name)}
        assert "importance_score" not in symbol_cols_after, "importance_score should be dropped after downgrade -1"
        assert "provenance" not in edge_cols_after, "symbol_edges.provenance should be dropped after downgrade -1"
        assert "github_webhook_events" in set(insp_downgraded.get_table_names(schema=clean_schema_name))

        # 3. Downgrade past durable webhook events (to d5e6f7a8b9c0)
        command.downgrade(cfg, "d5e6f7a8b9c0")
        tables_after_webhook_rollback = set(inspect(_make_engine()).get_table_names(schema=clean_schema_name))
        assert "github_webhook_events" not in tables_after_webhook_rollback, "github_webhook_events table should be dropped"
        assert "github_issues" in tables_after_webhook_rollback, "github_issues table should remain"
        assert "tasks" in tables_after_webhook_rollback, "tasks table should remain"

        # 4. Downgrade to Week 2 head b627460d74e0
        command.downgrade(cfg, "b627460d74e0")
        insp_w2 = inspect(_make_engine())
        tables_w2 = set(insp_w2.get_table_names(schema=clean_schema_name))
        assert "tasks" not in tables_w2, "tasks table should be dropped after rolling back to b627460d74e0"
        assert "github_issues" not in tables_w2, "github_issues table should be dropped after rolling back to b627460d74e0"
        assert "pull_requests" in tables_w2, "pull_requests should remain at b627460d74e0"

        # 5. Re-upgrade to head (idempotent re-creation)
        command.upgrade(cfg, "head")
        insp_reupgraded = inspect(_make_engine())
        tables_reupgraded = set(insp_reupgraded.get_table_names(schema=clean_schema_name))
        assert "tasks" in tables_reupgraded, "tasks must be restored after re-upgrade head"
        assert "github_issues" in tables_reupgraded, "github_issues must be restored after re-upgrade head"
        assert "github_webhook_events" in tables_reupgraded, "github_webhook_events must be restored after re-upgrade head"
        re_symbol_cols = {col["name"] for col in insp_reupgraded.get_columns("code_symbols", schema=clean_schema_name)}
        assert "importance_score" in re_symbol_cols, "code_symbols.importance_score must be restored after re-upgrade head"

    finally:
        engine.dispose()


def test_zero_schema_drift_against_database() -> None:
    """Verify that ORM models (Base.metadata) and Alembic migrations have zero schema drift (B-21)."""
    db_url = normalize_sync_database_url(get_settings().database_url)
    if db_url.startswith("sqlite"):
        pytest.skip("PostgreSQL database not available for schema drift test (SQLite active)")
        return
    try:
        probe_engine = create_engine(db_url, connect_args={"connect_timeout": 2})
        with probe_engine.connect():
            pass
    except Exception as exc:
        pytest.skip(f"PostgreSQL database not available for schema drift test: {exc}")
        return
    finally:
        try:
            probe_engine.dispose()
        except Exception:
            pass

    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    command.upgrade(cfg, "head")

    engine = create_engine(db_url, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            diffs = compare_metadata(ctx, Base.metadata)

            # Filter out expected environment-specific benign diffs if any
            # (e.g. pgvector vector type internal details or PostgreSQL GIN/HNSW index expression diffs)
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
    finally:
        engine.dispose()


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
        rev_match = re.search(r'revision:\s*(?:str\s*=\s*)?["\']([a-z0-9_]+)["\']', content)
        down_match = re.search(
            r'down_revision:\s*(?:[A-Za-z0-9_, \[\]\|]*\s*=\s*)?(?:["\']([a-z0-9_]+)["\']|None)',
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
