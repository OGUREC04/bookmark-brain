"""phase2 structured_data column

Adds:
  - bookmarks.structured_data  JSONB  (task lists, plans, ideas etc.)

Shape for task_list:
  {"type":"task_list","tasks":[{"text":"...","done":false,"deadline":null}]}

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-18 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bookmarks', sa.Column('structured_data', JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('bookmarks', 'structured_data')
