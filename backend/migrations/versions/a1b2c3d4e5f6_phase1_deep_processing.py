"""phase1 deep processing fields

Adds:
  - bookmarks.full_text           TEXT       (readability-extracted article)
  - bookmarks.item_type           VARCHAR(20)(action/thought/content/reference)
  - bookmarks.key_ideas           JSONB      (list[str])
  - bookmarks.entities            JSONB      (list[str])
  - bookmarks.open_questions      JSONB      (list[str])
  - bookmarks.takeaway            TEXT       (one-line essence)

Revision ID: a1b2c3d4e5f6
Revises: 8d256fb5e13e
Create Date: 2026-04-17 18:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '8d256fb5e13e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bookmarks', sa.Column('full_text', sa.Text(), nullable=True))
    op.add_column('bookmarks', sa.Column('item_type', sa.String(length=20), nullable=True))
    op.add_column('bookmarks', sa.Column('key_ideas', JSONB(), nullable=True))
    op.add_column('bookmarks', sa.Column('entities', JSONB(), nullable=True))
    op.add_column('bookmarks', sa.Column('open_questions', JSONB(), nullable=True))
    op.add_column('bookmarks', sa.Column('takeaway', sa.Text(), nullable=True))

    # Index for filtering by intent (e.g. "show my actions")
    op.create_index(
        'idx_bookmarks_item_type',
        'bookmarks',
        ['user_id', 'item_type'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('idx_bookmarks_item_type', table_name='bookmarks')
    op.drop_column('bookmarks', 'takeaway')
    op.drop_column('bookmarks', 'open_questions')
    op.drop_column('bookmarks', 'entities')
    op.drop_column('bookmarks', 'key_ideas')
    op.drop_column('bookmarks', 'item_type')
    op.drop_column('bookmarks', 'full_text')
