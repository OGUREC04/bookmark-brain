"""add embedding_retry_count and embedding_last_attempt

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-03 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bookmarks",
        sa.Column("embedding_retry_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "bookmarks",
        sa.Column("embedding_last_attempt", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bookmarks", "embedding_last_attempt")
    op.drop_column("bookmarks", "embedding_retry_count")
