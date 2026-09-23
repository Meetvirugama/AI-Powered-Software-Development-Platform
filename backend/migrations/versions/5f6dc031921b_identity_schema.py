"""identity_schema

Revision ID: 5f6dc031921b
Revises: 24498ac67b3e
Create Date: 2026-09-23 18:40:03.923843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f6dc031921b'
down_revision: Union[str, Sequence[str], None] = '24498ac67b3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('github_id', sa.String(), nullable=False),
        sa.Column('login', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('avatar_url', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_github_id'), 'users', ['github_id'], unique=True)
    op.create_index(op.f('ix_users_login'), 'users', ['login'], unique=True)

    # GitHub Installations table
    op.create_table(
        'github_installations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('installation_id', sa.String(), nullable=False),
        sa.Column('account_login', sa.String(), nullable=False),
        sa.Column('permissions', sa.JSON(), nullable=False),
        sa.Column('installed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_github_installations_installation_id'), 'github_installations', ['installation_id'], unique=True)
    op.create_index(op.f('ix_github_installations_user_id'), 'github_installations', ['user_id'], unique=False)

    # SyncStatus enum
    sync_status = sa.Enum('NOT_SYNCED', 'SYNCING', 'SYNCED', 'FAILED', name='syncstatus')
    sync_status.create(op.get_bind(), checkfirst=True)

    # Repositories table
    op.create_table(
        'repositories',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('installation_id', sa.UUID(), nullable=False),
        sa.Column('github_repo_id', sa.String(), nullable=False),
        sa.Column('owner', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('default_branch', sa.String(), nullable=False),
        sa.Column('language', sa.String(), nullable=True),
        sa.Column('sync_status', sync_status, nullable=False),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['installation_id'], ['github_installations.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_repositories_github_repo_id'), 'repositories', ['github_repo_id'], unique=False)
    op.create_index(op.f('ix_repositories_installation_id'), 'repositories', ['installation_id'], unique=False)
    op.create_index(op.f('ix_repositories_user_id'), 'repositories', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_repositories_user_id'), table_name='repositories')
    op.drop_index(op.f('ix_repositories_installation_id'), table_name='repositories')
    op.drop_index(op.f('ix_repositories_github_repo_id'), table_name='repositories')
    op.drop_table('repositories')
    sa.Enum('NOT_SYNCED', 'SYNCING', 'SYNCED', 'FAILED', name='syncstatus').drop(op.get_bind(), checkfirst=True)
    op.drop_index(op.f('ix_github_installations_user_id'), table_name='github_installations')
    op.drop_index(op.f('ix_github_installations_installation_id'), table_name='github_installations')
    op.drop_table('github_installations')
    op.drop_index(op.f('ix_users_login'), table_name='users')
    op.drop_index(op.f('ix_users_github_id'), table_name='users')
    op.drop_table('users')
