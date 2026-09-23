"""content_tables

Revision ID: aef3bb17eb34
Revises: 5f6dc031921b
Create Date: 2026-09-23 18:47:45.129530

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aef3bb17eb34'
down_revision: Union[str, Sequence[str], None] = '5f6dc031921b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # repository_files
    op.create_table(
        'repository_files',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.Column('language', sa.String(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('line_count', sa.Integer(), nullable=False),
        sa.Column('content_hash', sa.String(), nullable=False),
        sa.Column('last_indexed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_repository_files_repository_id'), 'repository_files', ['repository_id'], unique=False)

    # code_symbols
    op.create_table(
        'code_symbols',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('file_id', sa.UUID(), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('start_line', sa.Integer(), nullable=False),
        sa.Column('end_line', sa.Integer(), nullable=False),
        sa.Column('signature', sa.String(), nullable=True),
        sa.Column('parent_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['file_id'], ['repository_files.id'], ),
        sa.ForeignKeyConstraint(['parent_id'], ['code_symbols.id'], ),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_code_symbols_file_id_start_line', 'code_symbols', ['file_id', 'start_line'], unique=False)
    op.create_index(op.f('ix_code_symbols_repository_id'), 'code_symbols', ['repository_id'], unique=False)

    # symbol_edges
    op.create_table(
        'symbol_edges',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('source_symbol_id', sa.UUID(), nullable=False),
        sa.Column('target_symbol_id', sa.UUID(), nullable=False),
        sa.Column('edge_type', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ),
        sa.ForeignKeyConstraint(['source_symbol_id'], ['code_symbols.id'], ),
        sa.ForeignKeyConstraint(['target_symbol_id'], ['code_symbols.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_symbol_edges_repository_id'), 'symbol_edges', ['repository_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_symbol_edges_repository_id'), table_name='symbol_edges')
    op.drop_table('symbol_edges')
    op.drop_index(op.f('ix_code_symbols_repository_id'), table_name='code_symbols')
    op.drop_index('ix_code_symbols_file_id_start_line', table_name='code_symbols')
    op.drop_table('code_symbols')
    op.drop_index(op.f('ix_repository_files_repository_id'), table_name='repository_files')
    op.drop_table('repository_files')
