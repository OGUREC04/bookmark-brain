"""add_folders

Revision ID: 8d256fb5e13e
Revises: 001
Create Date: 2026-04-16 17:15:00.340059

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '8d256fb5e13e'
down_revision: Union[str, Sequence[str], None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('folders',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('emoji', sa.String(length=10), nullable=True),
        sa.Column('bookmarks_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_folder_user_name')
    )
    op.create_index('idx_folders_user', 'folders', ['user_id'], unique=False)
    op.add_column('bookmarks', sa.Column('folder_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_bookmarks_folder_id', 'bookmarks', 'folders', ['folder_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_bookmarks_folder_id', 'bookmarks', type_='foreignkey')
    op.drop_column('bookmarks', 'folder_id')
    op.drop_index('idx_folders_user', table_name='folders')
    op.drop_table('folders')
