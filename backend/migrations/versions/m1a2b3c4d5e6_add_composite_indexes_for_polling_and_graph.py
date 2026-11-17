"""add_composite_indexes_for_polling_and_graph

Revision ID: m1a2b3c4d5e6
Revises: daf0c05ab34b
Create Date: 2026-11-17 10:30:00.000000

Issue F-45 (#265): Composite indexes for worker queue polling, repository lookups, and graph traversals.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'daf0c05ab34b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema with composite indexes to optimize high-frequency worker queries."""
    # 1. SyncJob polling optimization: index status and (status, created_at)
    op.create_index('ix_sync_jobs_status', 'sync_jobs', ['status'], unique=False)
    op.create_index('ix_sync_jobs_status_created', 'sync_jobs', ['status', 'created_at'], unique=False)

    # 2. Webhook worker draining optimization: (status, available_at)
    op.create_index('ix_webhook_events_status_available', 'github_webhook_events', ['status', 'available_at'], unique=False)

    # 3. Repository lookups by owner/name: (owner, name)
    op.create_index('ix_repositories_owner_name', 'repositories', ['owner', 'name'], unique=False)

    # 4. SymbolEdge graph traversal optimization: (repository_id, source_symbol_id) and (repository_id, target_symbol_id)
    op.create_index('ix_symbol_edges_repo_source', 'symbol_edges', ['repository_id', 'source_symbol_id'], unique=False)
    op.create_index('ix_symbol_edges_repo_target', 'symbol_edges', ['repository_id', 'target_symbol_id'], unique=False)

    # 5. MemoryEntry filtering by convention type and active status: (repository_id, type, status)
    op.create_index('ix_memory_entries_repo_type_status', 'memory_entries', ['repository_id', 'type', 'status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_memory_entries_repo_type_status', table_name='memory_entries')
    op.drop_index('ix_symbol_edges_repo_target', table_name='symbol_edges')
    op.drop_index('ix_symbol_edges_repo_source', table_name='symbol_edges')
    op.drop_index('ix_repositories_owner_name', table_name='repositories')
    op.drop_index('ix_webhook_events_status_available', table_name='github_webhook_events')
    op.drop_index('ix_sync_jobs_status_created', table_name='sync_jobs')
    op.drop_index('ix_sync_jobs_status', table_name='sync_jobs')

